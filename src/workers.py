import threading
import time
import os
import json
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from .consts import C
from .utils import logger, fmt_size

class NativeRssWorker(threading.Thread):
    def __init__(self, controller):
        super().__init__(name="NativeRSS", daemon=True)
        self.c = controller
        self.history = set()
        self._load_history()
        
    def _load_history(self):
        if os.path.exists(C.RSS_HISTORY):
            try: 
                data = json.load(open(C.RSS_HISTORY))
                self.history = set(data)
            except: pass
            
    def _save_history(self):
        try:
            os.makedirs(os.path.dirname(C.RSS_HISTORY), exist_ok=True)
            with open(C.RSS_HISTORY, 'w') as f: 
                json.dump(list(self.history)[-5000:], f)
        except: pass

    def parse_size(self, item):
        enclosure = item.find('enclosure')
        if enclosure is not None:
            length = enclosure.get('length')
            if length and length.isdigit():
                return int(length)
        return 0

    def check_free_via_cookie(self, url, cookie_str):
        if not cookie_str: return False
        try:
            cookie_dict = {}
            for c in cookie_str.split(';'):
                if '=' in c:
                    k, v = c.split('=', 1)
                    cookie_dict[k.strip()] = v.strip()
            
            time.sleep(1.5)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': url
            }
            
            # logger.info(f"🔍 正在抓取页面验证免费: {url}")
            resp = requests.get(url, cookies=cookie_dict, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                html = resp.text
                free_tags = [
                    'class="pro_free"', 'class="pro_free2up"',
                    'alt="Free"', 'alt="2xFree"',
                    '<font class="free">', '[免费]', '[2X免费]'
                ]
                for tag in free_tags:
                    if tag in html: return True
            return False
        except Exception as e:
            logger.error(f"抓取验证失败: {e}")
            return False

    def execute(self):
        if not os.path.exists(C.RSS_RULES): return
        try: feeds = json.load(open(C.RSS_RULES))
        except: return
        if not self.c.client:
            try: self.c._connect()
            except: return
        try:
            if not os.path.exists(C.RSS_LOG):
                os.makedirs(os.path.dirname(C.RSS_LOG), exist_ok=True)
                with open(C.RSS_LOG, 'a') as f: f.write("")
        except: pass

        total_added = 0
        
        for feed in feeds:
            feed_url = feed.get('url')
            if not feed_url: continue
            
            max_size_gb = float(feed.get('max_size_gb', 0))
            must_contain = feed.get('must_contain', "")
            category = feed.get('category', 'Racing')
            enable_scrape = bool(feed.get('enable_scrape', False))
            cookie = feed.get('cookie', "")
            
            try:
                resp = requests.get(feed_url, timeout=30)
                if resp.status_code != 200: continue
                
                root = ET.fromstring(resp.content)
                items = root.findall('./channel/item')
                
                for item in items:
                    title = item.find('title').text
                    link = item.find('link').text
                    
                    if link in self.history: continue
                    if must_contain and must_contain.lower() not in title.lower(): continue
                    
                    size_bytes = self.parse_size(item)
                    size_gb = size_bytes / (1024**3)
                    
                    if max_size_gb > 0 and size_gb > max_size_gb: continue
                    
                    if enable_scrape:
                        if not cookie:
                            logger.warning(f"开启了抓取检测但未提供 Cookie: {feed_url}")
                            continue 
                        if not self.check_free_via_cookie(link, cookie):
                            continue
                    
                    logger.info(f"RSS 添加: {title} [{size_gb:.1f} GB]")
                    self.c.client.torrents_add(urls=link, category=category)
                    self.history.add(link)
                    total_added += 1
                    try:
                        with open(C.RSS_LOG, 'a') as f:
                            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ADD: {title} | {size_gb:.2f}GB\n")
                    except: pass
                    
            except Exception as e:
                logger.error(f"RSS 处理错误: {e}")

        if total_added > 0:
            self._save_history()
            if hasattr(self.c, 'notifier'):
                # === 修改处：调用新的 rss_notify 方法 ===
                self.c.notifier.rss_notify(total_added, 0)

    def run(self):
        logger.info("📡 原生 RSS 模块 (Cookie版) 已就绪")
        while self.c.running:
            if not self.c.config.flexget_enabled: 
                time.sleep(10); continue
            try: self.execute()
            except Exception as e: logger.error(f"RSS 循环异常: {e}")
            interval = max(60, int(self.c.config.flexget_interval_sec))
            for _ in range(interval):
                if not self.c.running: break
                time.sleep(1)

# === AutoRemoveWorker (保持不变) ===
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

        torrents = list(self.c.client.torrents_info())
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
                            break
                else:
                    if not dry_run: self.state["since"].pop(rule_key, None)
            
            if not dry_run and len(deletions) >= 1: break

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
            interval = max(30, int(self.c.config.autoremove_interval_sec))
            for _ in range(interval):
                if not self.c.running: break
                time.sleep(1)
