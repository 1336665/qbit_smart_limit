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
        if not os.path.exists(C.FLEXGET_CONFIG): return False
        try:
            if not os.path.exists(C.FLEXGET_LOG):
                os.makedirs(os.path.dirname(C.FLEXGET_LOG), exist_ok=True)
                with open(C.FLEXGET_LOG, 'a') as f: f.write("")
        except: pass

        py_script = (
            "import sys; from flexget import main; "
            "sys.argv=['flexget', '-c', '{}', '--logfile', '{}', 'execute']; main()"
        ).format(C.FLEXGET_CONFIG, C.FLEXGET_LOG)

        cmd = [sys.executable, "-c", py_script]
        start_ts = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            duration = time.time() - start_ts
            if proc.returncode == 0:
                accepted = re.findall(r'Accepted:\s+(\d+)', proc.stdout)
                count = sum(int(x) for x in accepted) if accepted else 0
                try:
                    with open(C.FLEXGET_LOG, 'r') as f:
                        f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 2048), 0); log_content = f.read()
                    acc_log = re.findall(r'Accepted:\s+(\d+)', log_content)
                    if acc_log: count = max(count, sum(int(x) for x in acc_log))
                except: pass
                if count > 0:
                    logger.info(f"FlexGet 抓取成功: {count} 个 (耗时 {duration:.1f}s)")
                    if hasattr(self.c, 'notifier'): self.c.notifier.flexget_notify(count, duration)
                else: logger.info(f"FlexGet 运行完成 (耗时 {duration:.1f}s)")
                return True
            else: logger.error(f"FlexGet 失败: {proc.stderr[:200]}"); return False
        except Exception as e: logger.error(f"FlexGet 异常: {e}"); return False

    def run(self):
        while self.c.running:
            if not self.c.config.flexget_enabled: time.sleep(10); continue
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
        try: st = os.statvfs(path); return st.f_bavail * st.f_frsize
        except:
            try: return os.statvfs("/").f_bavail * os.statvfs("/").f_frsize
            except: return 0

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

        # 获取种子列表
        torrents = list(self.c.client.torrents_info())
        
        # === 核心优化 1: 按上传速度从慢到快排序 ===
        # 这样确保如果只能删一个，一定先删最慢的那个，保留速度快的
        torrents.sort(key=lambda x: getattr(x, 'upspeed', 0))

        now = time.time()
        deletions = []

        if dry_run: print(f"\n{'[状态]':<10} {'[规则]':<20} {'[种子名称]'}\n" + "-"*60)

        for t in torrents:
            thash = t.hash
            save_path = getattr(t, 'save_path', '/')
            free_space = self.get_disk_free(save_path)
            
            upspeed = getattr(t, 'upspeed', 0)
            dlspeed = getattr(t, 'dlspeed', 0)
            progress = getattr(t, 'progress', 0)
            
            for idx, r in enumerate(rules):
                min_free = float(r.get("min_free_gb", 0)) * 1024**3
                max_up = int(r.get("max_up_bps", 0))
                min_time = int(r.get("min_low_sec", 60))
                req_comp = bool(r.get("require_complete", False))
                max_dl = int(r.get("max_dl_bps", 0)) 
                min_dl = int(r.get("min_dl_bps", 0))
                dl_up_ratio = float(r.get("min_dl_up_ratio", 0))

                rule_key = f"{thash}:{idx}"
                should_delete = True

                if min_free > 0 and free_space >= min_free: should_delete = False
                if req_comp and progress < 0.999: should_delete = False
                if max_up > 0 and upspeed > max_up: should_delete = False
                if max_dl > 0 and dlspeed > max_dl: should_delete = False
                if min_dl > 0 and dlspeed < min_dl: should_delete = False
                if dl_up_ratio > 0:
                    if upspeed == 0:
                        if dlspeed == 0: should_delete = False
                    else:
                        if dlspeed <= (upspeed * dl_up_ratio): should_delete = False

                if should_delete:
                    if dry_run:
                        print(f"{'PREVIEW':<10} {r.get('name')[:20]:<20} {t.name[:40]}")
                        break
                    else:
                        since = self.state["since"].get(rule_key)
                        if not since: self.state["since"][rule_key] = now
                        elif now - since >= min_time:
                            deletions.append((t, r.get("name", f"Rule #{idx}")))
                            break # 命中一个规则就退出规则循环
                else:
                    if not dry_run: self.state["since"].pop(rule_key, None)
            
            # === 核心优化 2: 点杀模式 ===
            # 如果不是预览模式，且已经找到了 1 个待删除的种子，
            # 立即停止检查剩余种子。
            if not dry_run and len(deletions) >= 1:
                break

        if dry_run:
            print("-" * 60 + f"\n共发现 {len(deletions) if not dry_run else 'N/A'} 个目标")
            return

        deleted_hashes = set()
        for t, reason in deletions:
            if t.hash in deleted_hashes: continue
            info = {'name': t.name, 'reason': reason, 'size': getattr(t, 'total_size', 0)}
            logger.warning(f"AutoRemove 删除: {t.name} ({reason})")
            try:
                with open(C.AUTORM_LOG, "a") as lf:
                    lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] DELETE: {t.name} | {reason}\n")
            except: pass
            try:
                if hasattr(self.c, 'notifier'): self.c.notifier.autoremove_notify(info)
                self.c.client.torrents_delete(delete_files=True, torrent_hashes=t.hash)
                self.c.db.delete_torrent_state(t.hash)
                keys_to_remove = [k for k in self.state["since"] if k.startswith(t.hash)]
                for k in keys_to_remove: self.state["since"].pop(k, None)
                deleted_hashes.add(t.hash)
            except Exception as e: logger.error(f"删除失败: {e}")
        self._save_state()

    def run(self):
        while self.c.running:
            if not self.c.config.autoremove_enabled: time.sleep(10); continue
            try: self.execute(dry_run=False)
            except Exception as e: logger.error(f"AutoRemove 循环异常: {e}")
            # 由于每次只删一个，建议缩短检查间隔，防止删得太慢赶不上下载
            interval = max(30, int(self.c.config.autoremove_interval_sec))
            for _ in range(interval):
                if not self.c.running: break
                time.sleep(1)
