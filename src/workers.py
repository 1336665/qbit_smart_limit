import threading
import time
import os
import json
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from .consts import C
from .utils import logger, fmt_size, wall_time

class NativeRssWorker(threading.Thread):
    def __init__(self, controller):
        super().__init__(name="NativeRSS", daemon=True)
        self.c = controller
        self.history = set()
        # 首次运行判断：如果没有历史文件，视为首次运行
        self.is_first_run = not os.path.exists(C.RSS_HISTORY)
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

    def get_download_link(self, item):
        enclosure = item.find('enclosure')
        if enclosure is not None:
            url = enclosure.get('url')
            if url: return url.strip()
        link = item.find('link')
        if link is not None and link.text:
            return link.text.strip()
        return None

    def check_free_via_cookie(self, url, cookie_dict):
        if not cookie_dict: return False
        try:
            time.sleep(1.5)
            headers = {'User-Agent': 'Mozilla/5.0', 'Referer': url}
            resp = requests.get(url, cookies=cookie_dict, headers=headers, timeout=15)
            if resp.status_code == 200:
                html = resp.text
                tags = ['class="pro_free"', 'class="pro_free2up"', 'alt="Free"', 'alt="2xFree"', '[免费]']
                return any(tag in html for tag in tags)
            return False
        except Exception: return False

    def download_torrent_file(self, url, cookie_dict):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, cookies=cookie_dict, headers=headers, timeout=20)
            if resp.status_code == 200:
                if b'd8:announce' in resp.content[:100] or b'd13:announce' in resp.content[:100]:
                    return resp.content
            return None
        except: return None

    def execute(self):
        if not os.path.exists(C.RSS_RULES): return
        try: feeds = json.load(open(C.RSS_RULES))
        except: return
        if not self.c.client:
            try: self.c._connect()
            except: return
        
        try:
            if not os.path.exists(C.RSS_LOG): os.makedirs(os.path.dirname(C.RSS_LOG), exist_ok=True)
        except: pass

        total_added = 0
        skipped_count = 0
        start_time = wall_time()
        
        for feed in feeds:
            feed_url = feed.get('url')
            if not feed_url: continue
            
            cookie_str = feed.get('cookie', '')
            cookie_dict = {}
            if cookie_str:
                cookie_dict = {k.strip(): v.strip() for k, v in (c.split('=', 1) for c in cookie_str.split(';') if '=' in c)}

            # === 获取配置: 是否优先下载首尾块 ===
            # 默认为 False，需要在 feeds.json 里开启
            first_last_prio = feed.get('first_last_piece', False) 
            
            try:
                resp = requests.get(feed_url, timeout=30)
                if resp.status_code != 200: 
                    logger.warning(f"RSS Fetch Failed: {resp.status_code}")
                    continue
                    
                try: root = ET.fromstring(resp.content)
                except: root = ET.fromstring(resp.content.decode('utf-8', 'ignore'))
                    
                items = root.findall('./channel/item')
                
                for item in items:
                    title_elem = item.find('title')
                    if title_elem is None: continue
                    title = title_elem.text
                    
                    dl_link = self.get_download_link(item)
                    if not dl_link: continue
                    
                    if dl_link in self.history: continue

                    # 首次运行跳过逻辑
                    if self.is_first_run:
                        self.history.add(dl_link)
                        skipped_count += 1
                        continue
                    
                    if feed.get('must_contain') and feed['must_contain'].lower() not in title.lower(): continue
                    
                    size_bytes = self.parse_size(item)
                    size_gb = size_bytes / (1024**3)
                    max_size = float(feed.get('max_size_gb', 0))
                    if max_size > 0 and size_gb > max_size: continue
                    
                    if feed.get('enable_scrape'):
                        detail_link = item.find('link').text
                        if not cookie_dict or not self.check_free_via_cookie(detail_link, cookie_dict):
                            continue

                    success = False
                    
                    # === 添加种子时传入 first_last_piece_prio 参数 ===
                    if cookie_dict:
                        torrent_data = self.download_torrent_file(dl_link, cookie_dict)
                        if torrent_data:
                            self.c.client.torrents_add(
                                torrent_files=torrent_data, 
                                category=feed.get('category', 'Racing'),
                                first_last_piece_prio=first_last_prio  # 关键参数
                            )
                            success = True
                            logger.info(f"RSS Add (File): {title}")
                        else:
                            logger.error(f"Failed to download .torrent: {title}")
                    else:
                        self.c.client.torrents_add(
                            urls=dl_link, 
                            category=feed.get('category', 'Racing'),
                            first_last_piece_prio=first_last_prio  # 关键参数
                        )
                        success = True
                        logger.info(f"RSS Add (URL): {title}")

                    if success:
                        self.history.add(dl_link)
                        total_added += 1
                        try:
                            with open(C.RSS_LOG, 'a') as f:
                                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ADD: {title} | {size_gb:.2f}GB\n")
                        except: pass
                    
            except Exception as e: 
                logger.error(f"RSS Process Error: {e}")

        if self.is_first_run:
            self.is_first_run = False
            self._save_history()
            if skipped_count > 0:
                logger.info(f"✨ 首次运行初始化完成：已跳过 {skipped_count} 个现有种子")

        duration = wall_time() - start_time
        if total_added > 0:
            self._save_history()
            if hasattr(self.c, 'notifier'): self.c.notifier.rss_notify(total_added, duration)

    def run(self):
        while self.c.running:
            if not self.c.config.flexget_enabled: 
                time.sleep(10); continue
            try: self.execute()
            except: pass
            time.sleep(max(60, int(self.c.config.flexget_interval_sec)))

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
        try: rules = json.load(open(C.AUTORM_RULES))
        except: return
        if not self.c.client: 
            try: self.c._connect()
            except: return

        torrents = list(self.c.client.torrents_info())
        torrents.sort(key=lambda x: getattr(x, 'upspeed', 0))
        now = time.time()
        deletions = []

        if dry_run: print(f"\n{'[Mode]':<10} {'[Rule]':<20} {'[Name]'}\n" + "-"*60)

        for t in torrents:
            save_path = getattr(t, 'save_path', '/')
            free_space = self.get_disk_free(save_path)
            upspeed = getattr(t, 'upspeed', 0)
            dlspeed = getattr(t, 'dlspeed', 0)
            
            for idx, r in enumerate(rules):
                should_delete = True
                if r.get("min_free_gb", 0) > 0 and free_space >= float(r["min_free_gb"])*1024**3: should_delete = False
                if r.get("require_complete") and t.progress < 0.999: should_delete = False
                if r.get("max_up_bps", 0) > 0 and upspeed > int(r["max_up_bps"]): should_delete = False
                if r.get("max_dl_bps", 0) > 0 and dlspeed > int(r["max_dl_bps"]): should_delete = False
                if r.get("min_dl_up_ratio", 0) > 0:
                    if upspeed > 0 and dlspeed <= upspeed * float(r["min_dl_up_ratio"]): should_delete = False

                rule_key = f"{t.hash}:{idx}"
                if should_delete:
                    if dry_run:
                        print(f"{'PREVIEW':<10} {r.get('name')[:20]:<20} {t.name[:40]}")
                        break
                    else:
                        since = self.state["since"].get(rule_key)
                        if not since: self.state["since"][rule_key] = now
                        elif now - since >= int(r.get("min_low_sec", 60)):
                            deletions.append((t, r.get("name")))
                            break
                else:
                    if not dry_run: self.state["since"].pop(rule_key, None)
            
            if not dry_run and len(deletions) >= 1: break

        if dry_run: return

        for t, reason in deletions:
            info = {'name': t.name, 'reason': reason, 'size': getattr(t, 'total_size', 0)}
            try:
                if hasattr(self.c, 'notifier'): self.c.notifier.autoremove_notify(info)
                self.c.client.torrents_delete(delete_files=True, torrent_hashes=t.hash)
                self.c.db.delete_torrent_state(t.hash)
                keys_to_rm = [k for k in self.state["since"] if k.startswith(t.hash)]
                for k in keys_to_rm: del self.state["since"][k]
                logger.warning(f"Deleted: {t.name} [{reason}]")
                try:
                    with open(C.AUTORM_LOG, "a") as lf:
                        lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] DELETE: {t.name} | {reason}\n")
                except: pass
            except Exception as e: logger.error(f"Delete fail: {e}")
            
        self._save_state()

    def run(self):
        while self.c.running:
            if not self.c.config.autoremove_enabled: time.sleep(10); continue
            try: self.execute()
            except: pass
            time.sleep(max(30, int(self.c.config.autoremove_interval_sec)))
