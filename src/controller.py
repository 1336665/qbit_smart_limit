import os, sys, time, signal, threading, queue, logging
from collections import deque
from typing import Optional, Dict, List, Any

import qbittorrentapi
from qbittorrentapi.exceptions import APIConnectionError, LoginFailed

from .consts import C
from .utils import logger, log_buffer, setup_logging, LoggerWrapper, wall_time, fmt_speed, safe_div
from .config import Config
from .database import Database
from .model import TorrentState, Stats
from .algorithms import _precision_tracker
from .helper_bot import TelegramBot
from .helper_web import U2WebHelper, BS4_AVAILABLE
from .logic import DownloadLimiter, ReannounceOptimizer

class Controller:
    ACTIVE = frozenset({'downloading', 'seeding', 'uploading', 'forcedUP', 'stalledUP', 
                        'stalledDL', 'checkingUP', 'forcedDL', 'checkingDL', 'metaDL'})
    
    def __init__(self, path: str):
        global logger
        self.db = Database()
        cfg, err = Config.load(path, self.db)
        if err:
            print(f"❌ 配置错误: {err}")
            sys.exit(1)
        self.config = cfg
        self.config_path = path
        self.last_config_check = wall_time()
        
        logger = LoggerWrapper(setup_logging(cfg.log_level), log_buffer)
        
        self.client: Optional[qbittorrentapi.Client] = None
        self.qb_version = ""
        self.states: Dict[str, TorrentState] = {}
        self.stats = Stats()
        
        db_stats = self.db.load_stats()
        if db_stats:
            self.stats.load_from_db(db_stats)
            logger.info(f"📦 已从数据库恢复统计: {self.stats.total} 个周期")
        
        self.notifier = TelegramBot(cfg.telegram_bot_token, cfg.telegram_chat_id, self)
        
        self.u2_helper: Optional[U2WebHelper] = None
        self.u2_enabled = False
        if cfg.peer_list_enabled and cfg.u2_cookie:
            if BS4_AVAILABLE:
                self.u2_helper = U2WebHelper(cfg.u2_cookie, cfg.proxy)
                self.u2_enabled = True
            else:
                logger.warning("⚠️ BeautifulSoup 未安装，U2功能已禁用")
        
        self.running = True
        self.modified_up: set = set()
        self.modified_dl: set = set()
        self._api_times: deque = deque(maxlen=200)
        
        self._pending_tid_searches: queue.Queue = queue.Queue()
        threading.Thread(target=self._tid_search_worker, daemon=True, name="TID-Search").start()
        
        self._last_db_save = wall_time()
        self._last_cookie_check = 0
        
        signal.signal(signal.SIGINT, lambda *_: self._shutdown())
        signal.signal(signal.SIGTERM, lambda *_: self._shutdown())
    
    def _tid_search_worker(self):
        while self.running:
            try:
                item = self._pending_tid_searches.get(timeout=5)
                if item and self.u2_helper:
                    h, state = item
                    result = self.u2_helper.search_tid_by_hash(h)
                    if result:
                        tid, publish_time, promo = result
                        state.tid = tid
                        state.publish_time = publish_time
                        state.promotion = promo
                        state.tid_searched = True
                        self.db.save_torrent_state(state)
                    else:
                        state.tid_not_found = True
                        state.tid_searched = True
                        state.promotion = "无优惠"
            except: pass
    
    def _shutdown(self):
        logger.info("🛑 正在停止服务...")
        self.running = False
        self._save_all_to_db()
        self.notifier.shutdown_report()
        if self.client:
            try:
                if self.modified_up: self.client.torrents_set_upload_limit(-1, list(self.modified_up))
                if self.modified_dl: self.client.torrents_set_download_limit(-1, list(self.modified_dl))
            except: pass
        if self.u2_helper: self.u2_helper.close()
        self.notifier.close()
        sys.exit(0)
    
    def _save_all_to_db(self):
        try:
            for state in self.states.values(): self.db.save_torrent_state(state)
            self.db.save_stats(self.stats)
            logger.debug("💾 状态已保存到数据库")
        except Exception as e: logger.error(f"保存数据库失败: {e}")
    
    def _check_config(self, now: float):
        if now - self.last_config_check < C.CONFIG_CHECK: return
        self.last_config_check = now
        try:
            mtime = os.path.getmtime(self.config_path)
            if mtime > self.config._mtime:
                new_cfg, err = Config.load(self.config_path, self.db)
                if not err:
                    self.config = new_cfg
                    logger.info("📝 配置已重新加载")
        except: pass
        if now - self._last_db_save > C.DB_SAVE_INTERVAL:
            self._save_all_to_db()
            self._last_db_save = now
        if self.u2_helper and now - self._last_cookie_check > C.COOKIE_CHECK_INTERVAL:
            self._last_cookie_check = now
            valid, msg = self.u2_helper.check_cookie_valid()
            if not valid:
                logger.warning(f"⚠️ Cookie 状态异常: {msg}")
                self.notifier.cookie_invalid_notify()
    
    def _connect(self):
        for i in range(5):
            try:
                self.client = qbittorrentapi.Client(host=self.config.host, username=self.config.username, password=self.config.password, VERIFY_WEBUI_CERTIFICATE=False, REQUESTS_ARGS={'timeout': (5, 15)})
                self.client.auth_log_in()
                self.qb_version = self.client.app.version
                logger.info(f"✅ 已连接 qBittorrent {self.qb_version}")
                return
            except LoginFailed:
                logger.error("❌ 登录失败，请检查用户名密码")
                sys.exit(1)
            except Exception as e:
                if i < 4: time.sleep(2 ** i)
                else: raise
    
    def _api_ok(self, now: float) -> bool:
        if self.config.api_rate_limit <= 0: return True
        while self._api_times and now - self._api_times[0] > 1: self._api_times.popleft()
        if len(self._api_times) >= self.config.api_rate_limit: return False
        self._api_times.append(now)
        return True
    
    def _get_props(self, h: str, state: TorrentState, now: float, force: bool = False) -> Optional[dict]:
        phase = state.get_phase(now)
        cache = C.PROPS_CACHE.get(phase, 1.0)
        if not force and state.last_props > 0 and now - state.last_props < cache: return None
        if not force and not self._api_ok(now): return None
        try:
            props = self.client.torrents_properties(torrent_hash=h)
            state.last_props = now
            return props
        except: return None
    
    def _should_manage(self, torrent: Any) -> bool:
        tracker = getattr(torrent, 'tracker', '') or ''
        if self.config.exclude_tracker_keyword and self.config.exclude_tracker_keyword in tracker: return False
        if self.config.target_tracker_keyword and self.config.target_tracker_keyword not in tracker: return False
        return True

    def _maybe_search_tid(self, state: TorrentState, now: float):
        if not self.u2_helper or not self.u2_helper.enabled: return
        if state.tid or state.tid_searched: return
        if state.tid_not_found and now - state.tid_search_time < 3600: return
        if now - state.tid_search_time < C.TID_SEARCH_INTERVAL: return
        state.tid_search_time = now
        try: self._pending_tid_searches.put_nowait((state.hash, state))
        except: pass

    def _maybe_check_peer_list(self, state: TorrentState, now: float):
        if not self.u2_helper or not self.u2_helper.enabled or not state.tid or state.tid < 0: return
        if now - state.last_peer_list_check < C.PEER_LIST_CHECK_INTERVAL: return
        state.last_peer_list_check = now
        def check():
            try:
                info = self.u2_helper.get_peer_list_info(state.tid)
                if info:
                    if 'last_announce' in info: state.last_announce_time = info['last_announce']
                    if 'uploaded' in info: state.peer_list_uploaded = info['uploaded']
            except: pass
        threading.Thread(target=check, daemon=True).start()

    def _do_reannounce(self, state: TorrentState, reason: str):
        try:
            self.client.torrents_reannounce(torrent_hashes=state.hash)
            state.last_reannounce = wall_time()
            state.reannounced_this_cycle = True
            state.waiting_reannounce = False
            state.last_announce_time = wall_time()
            logger.warning(f"[{state.name[:16]}] 🔄 强制汇报: {reason}")
            self.notifier.reannounce_notify(state.name, reason, state.tid)
        except: pass

    def _get_effective_target(self) -> int:
        if self.notifier.temp_target_kib:
            return int(self.notifier.temp_target_kib * 1024 * self.config.safety_margin)
        return self.config.target_bytes

    def _calc_upload_limit(self, state: TorrentState, torrent: Any, now: float, tl: float) -> Tuple[int, str]:
        if self.notifier.paused: return -1, "已暂停"
        target = self._get_effective_target()
        max_phy = self.config.max_physical_bytes
        current = getattr(torrent, 'upspeed', 0) or 0
        total_uploaded = getattr(torrent, 'uploaded', 0) or 0
        state.limit_controller.record_speed(now, current)
        real_speed = state.get_real_avg_speed(total_uploaded)
        
        if real_speed > C.SPEED_LIMIT * 1.05:
            logger.warning(f"[{state.name[:15]}] ⚠️ 超速 {fmt_speed(real_speed)}!")
            self.notifier.overspeed_warning(state.name, real_speed, target, state.tid)
            return C.MIN_LIMIT, "超速刹车"
        
        if state.waiting_reannounce: return C.REANNOUNCE_WAIT_LIMIT * 1024, "等待汇报"
        
        elapsed = state.elapsed(now)
        uploaded = state.uploaded_in_cycle(total_uploaded)
        phase = state.get_phase(now)
        precision_adj = _precision_tracker.get_adjustment(phase)
        
        limit, reason, debug = state.limit_controller.calculate(target, uploaded, tl, elapsed, phase, now, precision_adj)
        state.last_debug = debug
        
        if max_phy > 0:
            if limit == -1: limit = int(max_phy)
            elif limit > max_phy: limit = int(max_phy)
        
        progress = safe_div(uploaded, target * state.estimate_total(now, tl), 0)
        if progress >= C.PROGRESS_PROTECT and current > target * C.SPEED_PROTECT_RATIO:
            protect = int(target * C.SPEED_PROTECT_LIMIT)
            if limit == -1 or limit > protect:
                limit = protect
                reason = "保护"
        return limit, reason

    def _calc_download_limit(self, state: TorrentState, torrent: Any, now: float) -> Tuple[int, str]:
        if not self.config.enable_dl_limit or self.notifier.paused: return -1, ""
        total_uploaded = getattr(torrent, 'uploaded', 0) or 0
        total_done = getattr(torrent, 'completed', 0) or getattr(torrent, 'downloaded', 0) or 0
        total_size = getattr(torrent, 'total_size', 0) or state.total_size or 0
        eta = getattr(torrent, 'eta', 0) or 0
        up_speed = getattr(torrent, 'upspeed', 0) or 0
        dl_speed = getattr(torrent, 'dlspeed', 0) or 0
        if total_size <= 0: return -1, ""
        torrent_state = getattr(torrent, 'state', '')
        if 'download' not in torrent_state.lower() and 'stalled' not in torrent_state.lower():
            return (-1, "完成") if state.last_dl_limit > 0 else (-1, "")
        return DownloadLimiter.calc_dl_limit(state, total_uploaded, total_done, total_size, eta, up_speed, dl_speed, now)

    def _check_reannounce(self, state: TorrentState, torrent: Any, now: float):
        if not self.config.enable_reannounce_opt or self.notifier.paused: return
        total_uploaded = getattr(torrent, 'uploaded', 0) or 0
        total_done = getattr(torrent, 'completed', 0) or getattr(torrent, 'downloaded', 0) or 0
        total_size = getattr(torrent, 'total_size', 0) or state.total_size or 0
        up_speed = getattr(torrent, 'upspeed', 0) or 0
        dl_speed = getattr(torrent, 'dlspeed', 0) or 0
        if total_size <= 0: return
        if state.waiting_reannounce:
            should, reason = ReannounceOptimizer.check_waiting_reannounce(state, total_uploaded, now)
            if should: self._do_reannounce(state, reason)
            return
        should, reason = ReannounceOptimizer.should_reannounce(state, total_uploaded, total_done, total_size, up_speed, dl_speed, now)
        if should: self._do_reannounce(state, reason)

    def _report(self, state: TorrentState, torrent: Any, now: float):
        if state.report_sent: return
        state.report_sent = True
        target = self._get_effective_target()
        duration = max(1, state.elapsed(now))
        total_uploaded = getattr(torrent, 'uploaded', 0) or 0
        uploaded = state.uploaded_in_cycle(total_uploaded)
        speed = safe_div(uploaded, duration, 0)
        ratio = safe_div(speed, target, 0)
        real_speed = state.get_real_avg_speed(total_uploaded)
        phase = state.get_phase(now)
        _precision_tracker.record(ratio, phase, now)
        self.stats.record(ratio, uploaded)
        total_size = getattr(torrent, 'total_size', 0) or state.total_size
        total_done = getattr(torrent, 'completed', 0) or getattr(torrent, 'downloaded', 0) or 0
        progress_pct = safe_div(total_done, total_size, 0) * 100 if total_size > 0 else 0
        g = "🎯" if abs(ratio - 1) <= C.PRECISION_PERFECT else ("✅" if abs(ratio - 1) <= C.PRECISION_GOOD else ("👍" if ratio >= 0.95 else "⚠️"))
        extra = (" 📥" if state.dl_limited_this_cycle else "") + (" 🔄" if state.reannounced_this_cycle else "")
        logger.info(f"[{torrent.name[:16]}] {g} 汇报 ↑{fmt_speed(speed)}({ratio*100:.1f}%){extra}")
        self.notifier.cycle_report({'name': torrent.name, 'hash': state.hash, 'speed': speed, 'real_speed': real_speed, 'target': target, 'ratio': ratio, 'uploaded': uploaded, 'duration': duration, 'idx': state.cycle_index, 'tid': state.tid, 'total_size': total_size, 'total_uploaded_life': total_uploaded, 'total_downloaded_life': total_done, 'progress_pct': progress_pct})

    def _process(self, torrent: Any, now: float, up_actions: Dict[int, List[str]], dl_actions: Dict[int, List[str]]) -> float:
        h = torrent.hash
        if not self._should_manage(torrent): return 9999
        total_uploaded = getattr(torrent, 'uploaded', 0) or 0
        total_downloaded = getattr(torrent, 'completed', 0) or getattr(torrent, 'downloaded', 0) or 0
        if h not in self.states:
            state = TorrentState(h)
            db_data = self.db.load_torrent_state(h)
            if db_data:
                state.load_from_db(db_data)
                logger.info(f"📦 恢复: {torrent.name[:20]} (# {state.cycle_index})")
            state.time_added = getattr(torrent, 'added_on', 0) or 0
            state.initial_uploaded = total_uploaded
            state.total_size = getattr(torrent, 'total_size', 0) or 0
            if state.session_start_time <= 0:
                state.total_uploaded_start = total_uploaded
                state.session_start_time = now
            self.states[h] = state
        
        state = self.states[h]
        state.name = torrent.name
        if state.total_size <= 0: state.total_size = getattr(torrent, 'total_size', 0) or 0
        state.speed_tracker.record(now, total_uploaded, total_downloaded, getattr(torrent, 'upspeed', 0) or 0, getattr(torrent, 'dlspeed', 0) or 0)
        self._maybe_check_peer_list(state, now)
        
        props = self._get_props(h, state, now)
        tl = state.get_tl(now)
        if props:
            ra = props.get('reannounce', 0) or 0
            if 0 < ra < C.MAX_REANNOUNCE:
                state.cached_tl = ra; state.cache_ts = now
                if not state.last_announce_time: tl = ra
        
        current_up_limit = getattr(torrent, 'up_limit', -1) or -1
        is_jump = state.cycle_start > 0 and tl > state.prev_tl + 30
        
        if not state.monitor_notified:
            self._maybe_search_tid(state, now)
            if state.tid_searched or (not self.u2_helper) or ((now - state.session_start_time) > 60):
                self.notifier.monitor_start({'hash': h, 'name': torrent.name, 'total_size': state.total_size, 'target': self._get_effective_target(), 'tid': state.tid, 'promotion': state.promotion})
                state.monitor_notified = True
        
        self.notifier.check_finish({'hash': h, 'name': torrent.name, 'progress': safe_div(total_downloaded, state.total_size, 0), 'total_uploaded': total_uploaded, 'total_downloaded': total_downloaded})
        
        if state.cycle_start == 0 or is_jump:
            if is_jump: self._report(state, torrent, now)
            state.new_cycle(now, total_uploaded, tl, is_jump)
            logger.info(f"[{torrent.name[:16]}] 🔄 周期 #{state.cycle_index} {'✅同步' if state.cycle_synced else '⏳预热'} tid={state.tid or ''}")
        
        state.prev_tl = tl
        up_limit, up_reason = self._calc_upload_limit(state, torrent, now, tl)
        dl_limit, dl_reason = self._calc_download_limit(state, torrent, now)
        self._check_reannounce(state, torrent, now)
        
        if now - state.last_log > C.LOG_INTERVAL or state.last_log_limit != up_limit:
            uploaded = state.uploaded_in_cycle(total_uploaded)
            total = state.estimate_total(now, tl)
            progress = safe_div(uploaded, self._get_effective_target() * total, 0) * 100
            phase = state.get_phase(now)
            pid_out = state.last_debug.get('pid_output', 1) if state.last_debug else 1
            limit_str = 'MAX' if up_limit == -1 else f'{up_limit//1024}K'
            dl_info = f" 📥{dl_limit}K" if dl_limit > 0 else ""
            logger.info(f"[{torrent.name[:12]}] ↑{getattr(torrent, 'upspeed', 0)/1024:.0f}K ({progress:.0f}%) ⏱{tl:.0f}s [{phase[0].upper()}] → {limit_str} ({up_reason}) PID={pid_out:.2f}{dl_info}")
            state.last_log = now; state.last_log_limit = up_limit
        
        state.last_up_limit = up_limit; state.last_up_reason = up_reason
        if up_limit != current_up_limit:
            up_actions.setdefault(up_limit, []).append(h)
            self.modified_up.add(h)
        if dl_limit != state.last_dl_limit:
            if dl_limit > 0:
                state.dl_limited_this_cycle = True
                if state.last_dl_limit <= 0:
                    logger.warning(f"[{torrent.name[:16]}] 📥 下载限速: {dl_limit}K")
                    self.notifier.dl_limit_notify(torrent.name, dl_limit, dl_reason, state.tid)
            elif state.last_dl_limit > 0: logger.info(f"[{torrent.name[:16]}] 📥 解除限速")
            dl_actions.setdefault(dl_limit * 1024 if dl_limit > 0 else -1, []).append(h)
            self.modified_dl.add(h)
            state.last_dl_limit = dl_limit
        return tl

    def run(self):
        cfg = self.config
        target = self._get_effective_target()
        logger.info(f"🚀 qBit Smart Limit v{C.VERSION} | 目标: {fmt_speed(target)} | DL限速: {cfg.enable_dl_limit} | TG: {self.notifier.enabled}")
        self._connect()
        self.notifier.startup(cfg, self.qb_version, self.u2_enabled)
        while self.running:
            start = wall_time()
            min_tl = 3600
            try:
                self._check_config(start)
                torrents = self.client.torrents_info(status_filter='active')
                up_actions = {}; dl_actions = {}; now = wall_time()
                for t in torrents:
                    if getattr(t, 'state', '') in self.ACTIVE:
                        try: min_tl = min(min_tl, self._process(t, now, up_actions, dl_actions))
                        except: pass
                for limit, hashes in up_actions.items(): self.client.torrents_set_upload_limit(limit, hashes)
                for limit, hashes in dl_actions.items(): self.client.torrents_set_download_limit(limit, hashes)
                active = {t.hash for t in torrents if getattr(t, 'state', '') in self.ACTIVE}
                for h in list(self.states):
                    if h not in active: del self.states[h]
            except APIConnectionError:
                logger.warning("⚠️ 连接断开，重连中...")
                time.sleep(5)
                try: self._connect()
                except: pass
            except Exception as e: logger.error(f"❌ 异常: {e}")
            elapsed = wall_time() - start
            sleep = 0.15 if min_tl <= 5 else (0.25 if min_tl <= 15 else (0.4 if min_tl <= 30 else (0.8 if min_tl <= 90 else 1.5)))
            time.sleep(max(0.1, sleep - elapsed))
