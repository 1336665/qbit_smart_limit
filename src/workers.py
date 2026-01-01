import threading
import time
import os
import json
import subprocess
import re
from .consts import C
from .utils import logger, fmt_speed, fmt_size, fmt_duration

class FlexGetWorker(threading.Thread):
    def __init__(self, controller):
        super().__init__(name="FlexGet", daemon=True)
        self.c = controller
        
    def execute(self) -> bool:
        """执行一次 FlexGet 任务 (供外部或内部循环调用)"""
        if not os.path.exists(C.FLEXGET_CONFIG):
            logger.warning(f"FlexGet 配置文件未找到: {C.FLEXGET_CONFIG}")
            return False

        # 确保日志文件存在
        if not os.path.exists(C.FLEXGET_LOG):
            open(C.FLEXGET_LOG, 'a').close()

        # 调用模块运行，确保环境一致
        cmd = [f"python3", "-m", "flexget", "-c", C.FLEXGET_CONFIG, "--logfile", C.FLEXGET_LOG, "execute"]
        
        start_ts = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            duration = time.time() - start_ts
            
            if proc.returncode == 0:
                accepted = re.findall(r'Accepted:\s+(\d+)', proc.stdout)
                count = sum(int(x) for x in accepted) if accepted else 0
                if count > 0:
                    logger.info(f"FlexGet 抓取成功: {count} 个 (耗时 {duration:.1f}s)")
                    if self.c.notifier:
                        self.c.notifier.flexget_notify(count, duration)
                else:
                    logger.info(f"FlexGet 运行完成，无新任务 (耗时 {duration:.1f}s)")
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
            
            self.execute()
            
            # 等待间隔
            for _ in range(int(self.c.config.flexget_interval_sec)):
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

        # 确保日志文件存在
        if not os.path.exists(C.AUTORM_LOG) and not dry_run:
            open(C.AUTORM_LOG, 'a').close()

        try: rules = json.load(open(C.AUTORM_RULES))
        except: return

        if not rules: return
        if not self.c.client: 
            try: self.c._connect() # 尝试连接
            except: return

        torrents = self.c.client.torrents_info()
        now = time.time()
        deletions = []

        # 写入日志头 (仅 Dry Run)
        if dry_run: print(f"{'[状态]':<10} {'[规则]':<20} {'[种子名称]'}\n" + "-"*60)

        for t in torrents:
            thash = t.hash
            save_path = getattr(t, 'save_path', '/')
            free_space = self.get_disk_free(save_path)
            
            for idx, r in enumerate(rules):
                min_free = float(r.get("min_free_gb", 0)) * 1024**3
                max_up = int(r.get("max_up_bps", 0))
                min_time = int(r.get("min_low_sec", 60))
                req_comp = bool(r.get("require_complete", False))
                
                rule_key = f"{thash}:{idx}"
                
                if min_free > 0 and free_space >= min_free:
                    if not dry_run: self.state["since"].pop(rule_key, None)
                    continue
                if req_comp and getattr(t, 'progress', 0) < 0.999:
                    if not dry_run: self.state["since"].pop(rule_key, None)
                    continue

                if getattr(t, 'upspeed', 0) <= max_up:
                    if dry_run:
                        print(f"{'PREVIEW':<10} {r.get('name')[:20]:<20} {t.name[:40]}")
                        break # 预览模式匹配一条即可
                    else:
                        since = self.state["since"].get(rule_key)
                        if not since: self.state["since"][rule_key] = now
                        elif now - since >= min_time:
                            deletions.append((t, r.get("name", f"Rule #{idx}")))
                else:
                    if not dry_run: self.state["since"].pop(rule_key, None)

        if dry_run:
            print("-" * 60 + f"\n共发现 {len(deletions) if not dry_run else 'N/A'} 个目标 (预览模式不显示具体计数)")
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
            # 记录到独立日志
            try:
                with open(C.AUTORM_LOG, "a") as lf:
                    lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] DELETE: {t.name} | {reason}\n")
            except: pass

            try:
                if self.c.notifier: self.c.notifier.autoremove_notify(info)
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
            
            self.execute(dry_run=False)
            
            for _ in range(int(self.c.config.autoremove_interval_sec)):
                if not self.c.running: break
                time.sleep(1)
