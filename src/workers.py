import threading
import time
import os
import json
import subprocess
import re
import html
from .consts import C
from .utils import logger, fmt_speed, fmt_size, fmt_duration, safe_div

class FlexGetWorker(threading.Thread):
    def __init__(self, controller):
        super().__init__(name="FlexGet", daemon=True)
        self.c = controller
        
    def run(self):
        logger.info("🛠️ FlexGet 模块已就绪")
        while self.c.running:
            if not self.c.config.flexget_enabled:
                time.sleep(10); continue
                
            interval = self.c.config.flexget_interval_sec
            
            try:
                if not os.path.exists(C.FLEXGET_CONFIG):
                    time.sleep(60); continue

                # 执行 FlexGet
                cmd = ["flexget", "-c", C.FLEXGET_CONFIG, "--logfile", C.FLEXGET_LOG, "execute"]
                
                start_ts = time.time()
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                duration = time.time() - start_ts
                
                if proc.returncode == 0:
                    # 解析 "Accepted: N"
                    accepted = re.findall(r'Accepted:\s+(\d+)', proc.stdout)
                    count = sum(int(x) for x in accepted) if accepted else 0
                    
                    if count > 0:
                        logger.info(f"FlexGet 抓取到 {count} 个任务")
                        # 发送摘要通知，详细信息由 Controller 的监控逻辑负责
                        self.c.notifier.flexget_notify(count, duration)
                else:
                    logger.error(f"FlexGet 运行失败: {proc.stderr[:100]}")
            except Exception as e:
                logger.error(f"FlexGet 异常: {e}")
            
            # 等待间隔
            for _ in range(int(interval)):
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

    def run(self):
        logger.info("🛠️ AutoRemove 模块已就绪")
        while self.c.running:
            if not self.c.config.autoremove_enabled:
                time.sleep(10); continue
                
            interval = self.c.config.autoremove_interval_sec
            
            try:
                if not os.path.exists(C.AUTORM_RULES):
                    time.sleep(60); continue
                
                try: rules = json.load(open(C.AUTORM_RULES))
                except: time.sleep(60); continue

                if not rules: time.sleep(60); continue

                if not self.c.client: time.sleep(10); continue

                torrents = self.c.client.torrents_info()
                now = time.time()
                deletions = []

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
                        
                        # 空间充足或未完成则跳过
                        if min_free > 0 and free_space >= min_free:
                            self.state["since"].pop(rule_key, None); continue
                        if req_comp and getattr(t, 'progress', 0) < 0.999:
                            self.state["since"].pop(rule_key, None); continue

                        # 检查速度
                        if getattr(t, 'upspeed', 0) <= max_up:
                            since = self.state["since"].get(rule_key)
                            if not since: self.state["since"][rule_key] = now
                            elif now - since >= min_time:
                                deletions.append((t, r.get("name", f"Rule #{idx}")))
                        else:
                            self.state["since"].pop(rule_key, None)

                deleted_hashes = set()
                for t, reason in deletions:
                    if t.hash in deleted_hashes: continue
                    
                    # 收集信息用于通知
                    info = {
                        'name': t.name,
                        'reason': reason,
                        'size': getattr(t, 'total_size', 0),
                        'uploaded': getattr(t, 'uploaded', 0),
                        'ratio': getattr(t, 'ratio', 0),
                        'seed_time': now - getattr(t, 'added_on', now)
                    }
                    
                    logger.warning(f"AutoRemove 删除: {t.name} ({reason})")
                    try:
                        self.c.notifier.autoremove_notify(info)
                        self.c.client.torrents_delete(delete_files=True, torrent_hashes=t.hash)
                        self.c.db.delete_torrent_state(t.hash)
                        deleted_hashes.add(t.hash)
                    except Exception as e:
                        logger.error(f"删除失败: {e}")

                self._save_state()
            except Exception as e:
                logger.error(f"AutoRemove 异常: {e}")

            for _ in range(int(interval)):
                if not self.c.running: break
                time.sleep(1)
