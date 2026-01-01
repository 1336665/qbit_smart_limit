import threading
import time
import os
import json
import subprocess
import re
import sys
from .consts import C
from .utils import logger, fmt_speed, fmt_size, fmt_duration

class FlexGetWorker(threading.Thread):
    def __init__(self, controller):
        super().__init__(name="FlexGet", daemon=True)
        self.c = controller
        
    def execute(self) -> bool:
        """执行 FlexGet"""
        if not os.path.exists(C.FLEXGET_CONFIG):
            logger.warning(f"FlexGet 配置文件未找到: {C.FLEXGET_CONFIG}")
            return False

        try:
            if not os.path.exists(C.FLEXGET_LOG):
                os.makedirs(os.path.dirname(C.FLEXGET_LOG), exist_ok=True)
                with open(C.FLEXGET_LOG, 'a') as f: f.write("")
        except: pass

        # 使用内联 Python 调用，确保环境一致
        py_script = (
            "import sys; "
            "from flexget import main; "
            "sys.argv=['flexget', '-c', '{}', '--logfile', '{}', 'execute']; "
            "main()"
        ).format(C.FLEXGET_CONFIG, C.FLEXGET_LOG)

        cmd = [sys.executable, "-c", py_script]
        
        start_ts = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            duration = time.time() - start_ts
            
            if proc.returncode == 0:
                accepted = re.findall(r'Accepted:\s+(\d+)', proc.stdout)
                count = sum(int(x) for x in accepted) if accepted else 0
                
                # 补充检查日志末尾
                try:
                    with open(C.FLEXGET_LOG, 'r') as f:
                        f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 2048), 0)
                        log_content = f.read()
                    acc_log = re.findall(r'Accepted:\s+(\d+)', log_content)
                    if acc_log: count = max(count, sum(int(x) for x in acc_log))
                except: pass

                if count > 0:
                    logger.info(f"FlexGet 抓取成功: {count} 个 (耗时 {duration:.1f}s)")
                    if hasattr(self.c, 'notifier'): self.c.notifier.flexget_notify(count, duration)
                else:
                    logger.info(f"FlexGet 运行完成 (耗时 {duration:.1f}s)")
                return True
            else:
                logger.error(f"FlexGet 运行失败: {proc.stderr[:200]}")
                return False
        except Exception as e:
            logger.error(f"FlexGet 执行异常: {e}")
            return False

    def run(self):
        logger.info("🛠️ FlexGet 模块已就绪")
        while self.c.running:
            if not self.c.config.flexget_enabled:
                time.sleep(10); continue
            try: self.execute()
            except Exception as e: logger.error(f"FlexGet 循环异常: {e}")
            interval = max(60, int(self.c.config.flexget_interval_sec))
            for _ in range(interval):
                if not self.c.running: break
                time.sleep(1)

class AutoRemoveWorker(threading.Thread):
    def __init__(self, controller):
        super().__init__(name="AutoRemove", daemon=True)
        self.c = controller
        self.state = {"since": {}}
        self._load_state()

    def _load_state(self):
        if os.path.exists(C.AUTORM_STATE):
            try: self.state = json.load(open(C.AUTORM_STATE))
            except: pass

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(C.AUTORM_STATE), exist_ok=True)
            with open(C.AUTORM_STATE, 'w') as f: json.dump(self.state, f)
        except: pass

    def get_disk_free(self, path):
        """
        获取磁盘剩余空间 (智能回退版)
        1. 尝试获取 qB 报告路径的空间
        2. 如果失败 (Snap/Docker 隔离)，自动回退监控根目录 /
        """
        try:
            st = os.statvfs(path)
            return st.f_bavail * st.f_frsize
        except:
            # === 关键修复：路径不存在时，尝试监控根目录 ===
            try:
                # 这里你可以修改为你真正想监控的挂载点，比如 "/home" 或 "/mnt/data"
                # 默认为 "/" (系统根目录)，通常能反映整体磁盘情况
                fallback_path = "/" 
                st = os.statvfs(fallback_path)
                # 仅在调试时打印，避免刷屏
                # print(f"DEBUG: 路径 [{path}] 不存在，已回退监控 [{fallback_path}]") 
                return st.f_bavail * st.f_frsize
            except:
                return 0 # 彻底失败才返回 0

    def execute(self, dry_run=False):
        if not os.path.exists(C.AUTORM_RULES): return
        try:
            if not os.path.exists(C.AUTORM_LOG) and not dry_run:
                os.makedirs(os.path.dirname(C.AUTORM_LOG), exist_ok=True)
                with open(C.AUTORM_LOG, 'a') as f: f.write("")
        except: pass

        try: rules = json.load(open(C.AUTORM_RULES))
        except: return
        if not rules: return
        
        if not self.c.client: 
            try: self.c._connect()
            except: return

        torrents = self.c.client.torrents_info()
        now = time.time()
        deletions = []

        if dry_run: print(f"\n{'[状态]':<10} {'[规则]':<20} {'[种子名称]'}\n" + "-"*60)

        for t in torrents:
            thash = t.hash
            save_path = getattr(t, 'save_path', '/')
            
            # 这里调用了新的智能检测函数
            free_space = self.get_disk_free(save_path)
            
            upspeed = getattr(t, 'upspeed', 0)
            progress = getattr(t, 'progress', 0)
            
            for idx, r in enumerate(rules):
                min_free = float(r.get("min_free_gb", 0)) * 1024**3
                max_up = int(r.get("max_up_bps", 0))
                min_time = int(r.get("min_low_sec", 60))
                req_comp = bool(r.get("require_complete", False))
                
                rule_key = f"{thash}:{idx}"
                
                # 如果检测到的空间 (可能是根目录的空间) 足够，就跳过
                if min_free > 0 and free_space >= min_free:
                    if not dry_run: self.state["since"].pop(rule_key, None)
                    continue
                
                if req_comp and progress < 0.999:
                    if not dry_run: self.state["since"].pop(rule_key, None)
                    continue

                if upspeed <= max_up:
                    if dry_run:
                        print(f"{'PREVIEW':<10} {r.get('name')[:20]:<20} {t.name[:40]}")
                        break
                    else:
                        since = self.state["since"].get(rule_key)
                        if not since: self.state["since"][rule_key] = now
                        elif now - since >= min_time:
                            deletions.append((t, r.get("name", f"Rule #{idx}")))
                            break
                else:
                    if not dry_run: self.state["since"].pop(rule_key, None)

        if dry_run:
            print("-" * 60 + f"\n共发现 {len(deletions) if not dry_run else 'N/A'} 个目标")
            return

        # 执行删除
        deleted_hashes = set()
        for t, reason in deletions:
            if t.hash in deleted_hashes: continue
            
            info = {
                'name': t.name, 'reason': reason,
                'size': getattr(t, 'total_size', 0),
                'uploaded': getattr(t, 'uploaded', 0),
                'ratio': getattr(t, 'ratio', 0),
                'seed_time': now - getattr(t, 'added_on', now)
            }
            logger.warning(f"AutoRemove 删除: {t.name} ({reason})")
            try:
                with open(C.AUTORM_LOG, "a") as lf:
                    lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] DELETE: {t.name} | {reason} | FreeSpace: {fmt_size(free_space)}\n")
            except: pass

            try:
                if hasattr(self.c, 'notifier'): self.c.notifier.autoremove_notify(info)
                self.c.client.torrents_delete(delete_files=True, torrent_hashes=t.hash)
                self.c.db.delete_torrent_state(t.hash)
                deleted_hashes.add(t.hash)
            except Exception as e:
                logger.error(f"删除失败: {e}")

        self._save_state()

    def run(self):
        logger.info("🛠️ AutoRemove 模块已就绪")
        while self.c.running:
            if not self.c.config.autoremove_enabled:
                time.sleep(10); continue
            try: self.execute(dry_run=False)
            except Exception as e: logger.error(f"AutoRemove 循环异常: {e}")
            interval = max(60, int(self.c.config.autoremove_interval_sec))
            for _ in range(interval):
                if not self.c.running: break
                time.sleep(1)
