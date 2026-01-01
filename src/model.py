import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from .consts import C
from .utils import wall_time, estimate_announce_interval, get_phase, safe_div
from .algorithms import PrecisionLimitController, SpeedTracker

@dataclass
class Stats:
    start: float = field(default_factory=wall_time)
    total: int = 0
    success: int = 0
    precision: int = 0
    uploaded: int = 0
    
    def record(self, ratio: float, uploaded: int):
        self.total += 1
        self.uploaded += uploaded
        if ratio >= 0.95: self.success += 1
        if abs(ratio - 1) <= C.PRECISION_PERFECT: self.precision += 1
    
    def load_from_db(self, data: dict):
        if not data: return
        self.total = data.get('total', 0)
        self.success = data.get('success', 0)
        self.precision = data.get('precision', 0)
        self.uploaded = data.get('uploaded', 0)
        self.start = data.get('start', wall_time())

class TorrentState:
    def __init__(self, h: str):
        self.hash = h
        self.name = ""
        self._lock = threading.RLock()
        
        self._tid: Optional[int] = None
        self.tid_searched = False
        self.tid_search_time = 0.0
        self.tid_not_found = False
        self.promotion = "获取中..."
        self.monitor_notified = False
        
        self.cycle_start = 0.0
        self.cycle_start_uploaded = 0
        self.cycle_synced = False
        self.cycle_interval = 0.0
        self.cycle_index = 0
        self.jump_count = 0
        self.last_jump = 0.0
        
        self.time_added = 0.0
        self._publish_time: Optional[float] = None
        self._last_announce_time: Optional[float] = None
        
        self.initial_uploaded = 0
        self.total_size = 0
        self.total_uploaded_start = 0
        self.session_start_time = 0.0
        
        self.cached_tl = 0.0
        self.cache_ts = 0.0
        self.prev_tl = 0.0
        
        self.last_up_limit = -1
        self.last_up_reason = ""
        self.last_dl_limit = -1
        self.dl_limited_this_cycle = False
        
        self.last_reannounce = 0.0
        self.reannounced_this_cycle = False
        self.waiting_reannounce = False
        
        self.last_log = 0.0
        self.last_log_limit = -1
        self.last_props = 0.0
        self.report_sent = False
        
        self.last_peer_list_check = 0.0
        self.peer_list_uploaded: Optional[int] = None
        
        self.limit_controller = PrecisionLimitController()
        self.speed_tracker = SpeedTracker()
        self.last_debug: Dict[str, Any] = {}
    
    @property
    def tid(self) -> Optional[int]:
        with self._lock: return self._tid
    @tid.setter
    def tid(self, value: Optional[int]):
        with self._lock: self._tid = value
    
    @property
    def publish_time(self) -> Optional[float]:
        with self._lock: return self._publish_time
    @publish_time.setter
    def publish_time(self, value: Optional[float]):
        with self._lock: self._publish_time = value
    
    @property
    def last_announce_time(self) -> Optional[float]:
        with self._lock: return self._last_announce_time
    @last_announce_time.setter
    def last_announce_time(self, value: Optional[float]):
        with self._lock: self._last_announce_time = value
    
    def get_tl(self, now: float) -> float:
        with self._lock:
            if self._last_announce_time and self._last_announce_time > 0:
                interval = self.get_announce_interval()
                next_announce = self._last_announce_time + interval
                return max(0, next_announce - now)
            if self.cache_ts <= 0: return 9999
            return max(0, self.cached_tl - (now - self.cache_ts))
    
    def get_phase(self, now: float) -> str:
        return get_phase(self.get_tl(now), self.cycle_synced)
    
    def get_announce_interval(self) -> int:
        with self._lock:
            if self._publish_time and self._publish_time > 0:
                return estimate_announce_interval(self._publish_time)
        if self.time_added > 0:
            return estimate_announce_interval(self.time_added)
        return C.ANNOUNCE_INTERVAL_NEW
    
    def elapsed(self, now: float) -> float:
        return max(0, now - self.cycle_start) if self.cycle_start > 0 else 0
    
    def this_time(self, now: float) -> float:
        return self.elapsed(now)
    
    def uploaded_in_cycle(self, current_uploaded: int) -> int:
        return max(0, current_uploaded - self.cycle_start_uploaded)
    
    def this_up(self, current_uploaded: int) -> int:
        return self.uploaded_in_cycle(current_uploaded)
    
    def estimate_total(self, now: float, tl: float) -> float:
        e = self.elapsed(now)
        if 0 < tl < C.MAX_REANNOUNCE: return max(1, e + tl)
        if self.cycle_synced and self.cycle_interval > 0: return max(1, self.cycle_interval)
        return max(1, e)
    
    def get_real_avg_speed(self, current_uploaded: int) -> float:
        if self.session_start_time <= 0: return 0
        elapsed = wall_time() - self.session_start_time
        if elapsed < 10: return 0
        uploaded = current_uploaded - self.total_uploaded_start
        return safe_div(uploaded, elapsed, 0)
    
    def new_cycle(self, now: float, uploaded: int, tl: float, is_jump: bool):
        if is_jump:
            self.jump_count += 1
            if self.jump_count >= 2 and self.last_jump > 0:
                self.cycle_interval = now - self.last_jump
                self.cycle_synced = True
            self.last_jump = now
            self.cycle_index += 1
            self.cycle_start_uploaded = uploaded
            with self._lock: self._last_announce_time = now
        elif self.time_added > 0 and (now - self.time_added) < self.get_announce_interval():
            self.cycle_start_uploaded = 0
        else:
            interval = self.get_announce_interval()
            elapsed_in_cycle = interval - tl if 0 < tl < interval else 0
            if elapsed_in_cycle > 60:
                avg_speed = self.limit_controller.kalman.speed
                if avg_speed > 0:
                    self.cycle_start_uploaded = max(0, uploaded - int(avg_speed * elapsed_in_cycle))
                else: self.cycle_start_uploaded = uploaded
            else: self.cycle_start_uploaded = uploaded
        
        self.cycle_start = now
        self.report_sent = False
        self.dl_limited_this_cycle = False
        self.reannounced_this_cycle = False
        self.waiting_reannounce = False
        self.last_dl_limit = -1
        self.limit_controller.reset()
        self.speed_tracker.clear()
    
    def load_from_db(self, data: dict):
        if not data: return
        self.name = data.get('name', '')
        self.tid = data.get('tid')
        self.promotion = data.get('promotion', '获取中...')
        self.publish_time = data.get('publish_time')
        self.cycle_index = data.get('cycle_index', 0)
        self.cycle_start = data.get('cycle_start', 0)
        self.cycle_start_uploaded = data.get('cycle_start_uploaded', 0)
        self.cycle_synced = data.get('cycle_synced', False)
        self.cycle_interval = data.get('cycle_interval', 0)
        self.total_uploaded_start = data.get('total_uploaded_start', 0)
        self.session_start_time = data.get('session_start_time', 0)
        self.last_announce_time = data.get('last_announce_time')
        if self.tid: self.tid_searched = True
