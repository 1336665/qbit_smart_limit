import threading
import time
import os
import json
import subprocess
import re
import sys
import html
from .consts import C
from .utils import logger, fmt_speed, fmt_size, fmt_duration, safe_div

class FlexGetWorker(threading.Thread):
    def __init__(self, controller):
        super().__init__(name="FlexGet", daemon=True)
        self.c = controller
        
    def execute(self) -> bool:
        """执行一次 FlexGet 任务"""
        # 1. 检查配置
        if not os.path.exists(C.FLEXGET_CONFIG):
            logger.warning(f"FlexGet 配置文件未找到: {C.FLEXGET_CONFIG}")
            return False

        # 2. 确保日志文件存在
        try:
            if not os.path.exists(C.FLEXGET_LOG):
                os.makedirs(os.path.dirname(C.FLEXGET_LOG), exist_ok=True)
                with open(C.FLEXGET_LOG, 'a') as f: f.write("")
        except: pass

        # 3. 构造命令 (关键修复)
        # 不使用 -m flexget，而是构建一个内联 Python 脚本来调用 flexget.main()
        # 这样可以 100% 确保调用的是当前 Python 环境中的 flexget
        
        py_script = (
            "import sys; "
            "from flexget import main; "
            "sys.argv=['flexget', '-c', '{}', '--logfile', '{}', 'execute']; "
            "main()"
        ).format(C.FLEXGET_CONFIG, C.FLEXGET_LOG)

        cmd = [sys.executable, "-c", py_script]
        
        start_ts = time.time()
        try:
            # 运行命令
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            duration = time.time() - start_ts
            
            # FlexGet 成功时通常返回 0
            if proc.returncode == 0:
                # 解析标准输出寻找 "Accepted: N"
                # 注意：如果使用了 --logfile，大部分输出会在日志里，stdout 可能只有少量信息
                # 但为了通知，我们尝试读一下
                accepted = re.findall(r'Accepted:\s+(\d+)', proc.stdout)
                count = sum(int(x) for x in accepted) if accepted else 0
                
                # 另外检查日志文件的最后几行来确认结果 (因为 stdout 可能被重定向了)
                log_content = ""
                try:
                    with open(C.FLEXGET_LOG, 'r') as f:
                        # 读取最后 2KB
                        f.seek(0, 2)
                        size = f.tell()
                        f.seek(max(0, size - 2048), 0)
                        log_content = f.read()
                        
                    acc_log = re.findall(r'Accepted:\s+(\d+)', log_content)
                    if acc_log:
                        count = max(count, sum(int(x) for x in acc_log))
                except: pass

                if count > 0:
                    logger.info(f"FlexGet 抓取成功: {count} 个 (耗时 {duration:.1f}s)")
                    if hasattr(self.c, 'notifier'):
                        self.c.notifier.flexget_notify(count, duration)
                else:
                    logger.info(f"FlexGet 运行完成 (耗时 {duration:.1f}s)")
                return True
            else:
                # 运行失败，记录 stderr
                err_msg = proc.stderr.strip() or proc.stdout.strip() or "未知错误"
                logger.error(f"FlexGet 运行失败 (Code {proc.returncode}): {err_msg[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"FlexGet 执行异常: {e}")
            return False

    def run(self):
        logger.info("🛠️ FlexGet 模块已就绪")
        while self.c.running:
            if not self.c.config.flexget_enabled:
                time.sleep(10); continue
            
            try:
                self.execute()
            except Exception as e:
                logger.error(f"FlexGet 循环异常: {e}")
            
            # 等待间隔
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
        try:
            st = os.statvfs(path)
            return st.f_bavail * st.f_frsize
        except: return 0

    def execute(self, dry_run=False):
        """执行一次 AutoRemove 检查"""
        if not os.path.exists(C.AUTORM_RULES):
            if not dry_run: logger.warning("AutoRemove 规则文件不存在")
            return

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

        if dry_run: 
            print(f"\n{'[状态]':<10} {'[规则]':<20} {'[种子名称]'}\n" + "-"*60)

        for t in torrents:
            thash = t.hash
            save_path = getattr(t, 'save_path', '/')
            free_space = self.get_disk_free(save_path)
            
            # 获取种子属性
            upspeed = getattr(t, 'upspeed', 0)
            progress = getattr(t, 'progress', 0)
            
            for idx, r in enumerate(rules):
                min_free = float(r.get("min_free_gb", 0)) * 1024**3
                max_up = int(r.get("max_up_bps", 0))
                min_time = int(r.get("min_low_sec", 60))
                req_comp = bool(r.get("require_complete", False))
                
                rule_key = f"{thash}:{idx}"
                
                # 1. 空间检查 (如果空间足够，直接跳过此规则)
                if min_free > 0 and free_space >= min_free:
                    if not dry_run: self.state["since"].pop(rule_key, None)
                    continue
                
                # 2. 完成度检查
                if req_comp and progress < 0.999:
                    if not dry_run: self.state["since"].pop(rule_key, None)
                    continue

                # 3. 速度检查
                if upspeed <= max_up:
                    if dry_run:
                        print(f"{'PREVIEW':<10} {r.get('name')[:20]:<20} {t.name[:40]}")
                        break # 预览模式下，只要匹配一条规则就显示并跳过该种子
                    else:
                        since = self.state["since"].get(rule_key)
                        if not since:
                            self.state["since"][rule_key] = now
                        elif now - since >= min_time:
                            deletions.append((t, r.get("name", f"Rule #{idx}")))
                            # 匹配到删除就不再匹配其他规则
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
            
            # 写独立日志
            try:
                with open(C.AUTORM_LOG, "a") as lf:
                    lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] DELETE: {t.name} | Reason: {reason} | Free: {fmt_size(free_space)}\n")
            except: pass

            try:
                if hasattr(self.c, 'notifier'): self.c.notifier.autoremove_notify(info)
                # 物理删除
                self.c.client.torrents_delete(delete_files=True, torrent_hashes=t.hash)
                self.c.db.delete_torrent_state(t.hash)
                
                # 清理计时器
                keys_to_remove = [k for k in self.state["since"] if k.startswith(t.hash)]
                for k in keys_to_remove: self.state["since"].pop(k, None)
                
                deleted_hashes.add(t.hash)
            except Exception as e:
                logger.error(f"删除失败: {e}")

        self._save_state()

    def run(self):
        logger.info("🛠️ AutoRemove 模块已就绪")
        while self.c.running:
            if not self.c.config.autoremove_enabled:
                time.sleep(10); continue
            
            try:
                self.execute(dry_run=False)
            except Exception as e:
                logger.error(f"AutoRemove 循环异常: {e}")
            
            interval = max(60, int(self.c.config.autoremove_interval_sec))
            for _ in range(interval):
                if not self.c.running: break
                time.sleep(1)
