import time
import re
import os
import logging
import threading
from collections import deque
from typing import Optional, List, Deque
from logging.handlers import RotatingFileHandler
from datetime import datetime
from .consts import C

def fmt_size(b: float, precision: int = 2) -> str:
    if b == 0: return "0 B"
    for u in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if abs(b) < 1024: return f"{b:.{precision}f} {u}"
        b /= 1024
    return f"{b:.{precision}f} PiB"

def fmt_speed(b: float, precision: int = 1) -> str:
    if b == 0: return "0 B/s"
    for u in ['B/s', 'KiB/s', 'MiB/s', 'GiB/s']:
        if abs(b) < 1024: return f"{b:.{precision}f} {u}"
        b /= 1024
    return f"{b:.{precision}f} TiB/s"

def fmt_duration(s: float) -> str:
    s = max(0, int(s))
    if s < 60: return f"{s}s"
    if s < 3600: return f"{s//60}m{s%60}s"
    return f"{s//3600}h{(s%3600)//60}m"

def escape_html(t: str) -> str:
    return str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def safe_div(a: float, b: float, default: float = 0) -> float:
    try:
        if b == 0 or abs(b) < 1e-10: return default
        return a / b
    except: return default

def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))

def get_phase(tl: float, synced: bool) -> str:
    if not synced: return C.PHASE_WARMUP
    if tl <= C.FINISH_TIME: return C.PHASE_FINISH
    if tl <= C.STEADY_TIME: return C.PHASE_STEADY
    return C.PHASE_CATCH

def estimate_announce_interval(time_ref: float) -> int:
    age = time.time() - time_ref
    if age < 7 * 86400: return C.ANNOUNCE_INTERVAL_NEW
    elif age < 30 * 86400: return C.ANNOUNCE_INTERVAL_WEEK
    return C.ANNOUNCE_INTERVAL_OLD

def wall_time() -> float:
    return time.time()

def parse_speed_str(s: str) -> Optional[int]:
    s = s.strip().upper()
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(K|M|G|KB|MB|GB|KIB|MIB|GIB)?$', s)
    if not match: return None
    num = float(match.group(1))
    unit = match.group(2) or 'K'
    multipliers = {'K': 1, 'KB': 1, 'KIB': 1, 'M': 1024, 'MB': 1024, 'MIB': 1024, 'G': 1048576, 'GB': 1048576, 'GIB': 1048576}
    return int(num * multipliers.get(unit, 1))

# 日志系统
class LogBuffer:
    def __init__(self, maxlen: int = 100):
        self._buffer: Deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
    
    def add(self, msg: str):
        with self._lock:
            self._buffer.append(f"{datetime.now().strftime('%H:%M:%S')} {msg}")
    
    def get_recent(self, n: int = 10) -> List[str]:
        with self._lock:
            return list(self._buffer)[-n:]

def setup_logging(level: str = "INFO") -> logging.Logger:
    log = logging.getLogger("qsl")
    log.setLevel(logging.DEBUG)
    for h in list(log.handlers):
        try: h.close()
        except: pass
    log.handlers.clear()
    
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    log.addHandler(console)
    
    try:
        os.makedirs("/var/log", exist_ok=True)
        fh = RotatingFileHandler("/var/log/qbit-smart-limit.log", maxBytes=10*1024*1024, backupCount=3)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        log.addHandler(fh)
    except: pass
    return log

class LoggerWrapper:
    def __init__(self, logger: logging.Logger, buffer: LogBuffer):
        self._logger = logger
        self._buffer = buffer
    
    def info(self, msg): self._logger.info(msg); self._buffer.add(f"[I] {msg}")
    def warning(self, msg): self._logger.warning(msg); self._buffer.add(f"[W] {msg}")
    def error(self, msg): self._logger.error(msg); self._buffer.add(f"[E] {msg}")
    def debug(self, msg): self._logger.debug(msg)

# 初始化全局单例
log_buffer = LogBuffer()
# 初始 logger，稍后在 main 中会根据配置重置
logger = LoggerWrapper(setup_logging("INFO"), log_buffer)
