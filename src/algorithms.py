import threading
from collections import deque
from typing import Tuple, Dict, List, Any, Optional, Deque
from .consts import C
from .utils import safe_div, clamp

class PIDController:
    def __init__(self):
        self.kp = 0.6; self.ki = 0.15; self.kd = 0.08
        self._integral = 0.0; self._last_error = 0.0; self._last_time = 0.0
        self._last_output = 1.0; self._initialized = False
        self._integral_limit = 0.3; self._derivative_filter = 0.0
    
    def set_phase(self, phase: str):
        params = C.PID_PARAMS.get(phase, C.PID_PARAMS['steady'])
        self.kp, self.ki, self.kd = params['kp'], params['ki'], params['kd']
    
    def update(self, setpoint: float, measured: float, now: float) -> float:
        error = safe_div(setpoint - measured, max(setpoint, 1), 0)
        if not self._initialized:
            self._last_error = error; self._last_time = now; self._initialized = True
            return 1.0
        dt = now - self._last_time
        if dt <= 0.01: return self._last_output
        self._last_time = now
        
        p_term = self.kp * error
        self._integral = clamp(self._integral + error * dt, -self._integral_limit, self._integral_limit)
        i_term = self.ki * self._integral
        
        raw_derivative = (error - self._last_error) / dt
        self._derivative_filter = 0.3 * raw_derivative + 0.7 * self._derivative_filter
        d_term = self.kd * self._derivative_filter
        self._last_error = error
        
        output = clamp(1.0 + p_term + i_term + d_term, 0.5, 2.0)
        self._last_output = output
        return output
    
    def reset(self):
        self._integral = 0.0; self._last_error = 0.0; self._last_time = 0.0
        self._last_output = 1.0; self._derivative_filter = 0.0; self._initialized = False

class ExtendedKalman:
    def __init__(self):
        self.speed = 0.0; self.accel = 0.0
        self.p00 = 1000.0; self.p01 = 0.0; self.p10 = 0.0; self.p11 = 1000.0
        self._last_time = 0.0; self._initialized = False
    
    def update(self, measurement: float, now: float) -> Tuple[float, float]:
        if not self._initialized:
            self.speed = measurement; self._last_time = now; self._initialized = True
            return measurement, 0.0
        dt = now - self._last_time
        if dt <= 0.01: return self.speed, self.accel
        self._last_time = now
        
        pred_speed = self.speed + self.accel * dt
        p00_pred = self.p00 + dt * (self.p10 + self.p01) + dt * dt * self.p11 + C.KALMAN_Q_SPEED
        p01_pred = self.p01 + dt * self.p11
        p10_pred = self.p10 + dt * self.p11
        p11_pred = self.p11 + C.KALMAN_Q_ACCEL
        
        s = p00_pred + C.KALMAN_R
        if abs(s) < 1e-10: return self.speed, self.accel
        k0, k1 = p00_pred / s, p10_pred / s
        innovation = measurement - pred_speed
        
        self.speed = pred_speed + k0 * innovation
        self.accel = self.accel + k1 * innovation
        self.p00 = (1 - k0) * p00_pred
        self.p01 = (1 - k0) * p01_pred
        self.p10 = -k1 * p00_pred + p10_pred
        self.p11 = -k1 * p01_pred + p11_pred
        return self.speed, self.accel
    
    def predict_upload(self, seconds: float) -> float:
        return max(0, self.speed * seconds + 0.5 * self.accel * seconds * seconds)
    
    def reset(self):
        self.speed = 0.0; self.accel = 0.0; self.p00 = 1000.0
        self.p01 = 0.0; self.p10 = 0.0; self.p11 = 1000.0; self._initialized = False

class MultiWindowSpeedTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._samples: Deque[Tuple[float, float]] = deque(maxlen=1200)
    
    def record(self, now: float, speed: float):
        with self._lock: self._samples.append((now, speed))
    
    def get_weighted_avg(self, now: float, phase: str) -> float:
        weights = C.WINDOW_WEIGHTS.get(phase, C.WINDOW_WEIGHTS['steady'])
        with self._lock: samples = list(self._samples)
        
        total_weight = 0.0; weighted_sum = 0.0
        for window in C.SPEED_WINDOWS:
            win_samples = [s for t, s in samples if now - t <= window]
            if win_samples:
                avg = sum(win_samples) / len(win_samples)
                w = weights.get(window, 0.25)
                weighted_sum += avg * w; total_weight += w
        return weighted_sum / total_weight if total_weight > 0 else 0.0
    
    def get_recent_trend(self, now: float, window: int = 10) -> float:
        with self._lock:
            samples = [(t, s) for t, s in self._samples if now - t <= window]
        if len(samples) < 5: return 0.0
        mid = len(samples) // 2
        first = sum(s for _, s in samples[:mid]) / mid
        second = sum(s for _, s in samples[mid:]) / (len(samples) - mid)
        return safe_div(second - first, first, 0)
    
    def clear(self):
        with self._lock: self._samples.clear()

class AdaptiveQuantizer:
    @staticmethod
    def quantize(limit: int, phase: str, current_speed: float, target: float, trend: float = 0) -> int:
        if limit <= 0: return limit
        base = C.QUANT_STEPS.get(phase, 1024)
        ratio = safe_div(current_speed, target, 1)
        
        if phase == 'finish': step = 256
        elif ratio > 1.2: step = base * 2
        elif ratio > 1.05: step = base
        elif ratio > 0.8: step = base // 2
        else: step = base
        
        if abs(trend) > 0.1: step = max(256, step // 2)
        step = int(clamp(step, 256, 8192))
        return max(C.MIN_LIMIT, int((limit + step // 2) // step) * step)

class PrecisionTracker:
    def __init__(self, window: int = 30):
        self._history: Deque[Tuple[float, str, float]] = deque(maxlen=window)
        self._phase_adj: Dict[str, float] = {'warmup': 1.0, 'catch': 1.0, 'steady': 1.0, 'finish': 1.0}
        self._global_adj = 1.0
        self._lock = threading.Lock()
    
    def record(self, ratio: float, phase: str, now: float):
        with self._lock:
            self._history.append((ratio, phase, now))
            self._update()
    
    def _update(self):
        if len(self._history) < 5: return
        phase_data: Dict[str, List[float]] = {}
        for ratio, phase, _ in self._history:
            phase_data.setdefault(phase, []).append(ratio)
        
        for phase, ratios in phase_data.items():
            if len(ratios) < 3: continue
            avg = sum(ratios) / len(ratios)
            if avg > 1.005: adj = 0.998
            elif avg > 1.001: adj = 0.999
            elif avg < 0.99: adj = 1.002
            elif avg < 0.995: adj = 1.001
            else: adj = 1.0
            self._phase_adj[phase] = clamp(self._phase_adj[phase] * adj, 0.92, 1.08)
        
        all_ratios = [r for r, _, _ in self._history]
        global_avg = sum(all_ratios) / len(all_ratios)
        if global_avg > 1.002: self._global_adj = clamp(self._global_adj * 0.999, 0.95, 1.05)
        elif global_avg < 0.995: self._global_adj = clamp(self._global_adj * 1.001, 0.95, 1.05)
    
    def get_adjustment(self, phase: str) -> float:
        with self._lock:
            return self._phase_adj.get(phase, 1.0) * self._global_adj

class PrecisionLimitController:
    def __init__(self):
        self.kalman = ExtendedKalman()
        self.speed_tracker = MultiWindowSpeedTracker()
        self.pid = PIDController()
        self._smooth_limit = -1
    
    def record_speed(self, now: float, speed: float):
        self.kalman.update(speed, now)
        self.speed_tracker.record(now, speed)
    
    def calculate(self, target: float, uploaded: int, time_left: float, elapsed: float, 
                  phase: str, now: float, precision_adj: float = 1.0) -> Tuple[int, str, Dict]:
        debug: Dict[str, Any] = {}
        adjusted_target = target * precision_adj
        
        kalman_speed = self.kalman.speed
        weighted_speed = self.speed_tracker.get_weighted_avg(now, phase)
        trend = self.speed_tracker.get_recent_trend(now)
        current_speed = weighted_speed if (phase == 'finish' and weighted_speed > 0) else (kalman_speed if kalman_speed > 0 else weighted_speed)
        
        total_time = elapsed + time_left
        target_total = adjusted_target * total_time
        debug['predicted_ratio'] = safe_div(uploaded + self.kalman.predict_upload(time_left), target_total, 0)
        
        need = max(0, target_total - uploaded)
        if time_left <= 0: return -1, "汇报中", debug
        required_speed = need / time_left
        debug['required_speed'] = required_speed
        
        self.pid.set_phase(phase)
        pid_output = self.pid.update(target_total, uploaded, now)
        debug['pid_output'] = pid_output
        
        headroom = C.PID_PARAMS.get(phase, {}).get('headroom', 1.01)
        limit = -1; reason = ""
        
        if phase == 'finish':
            pred = debug['predicted_ratio']
            correction = max(0.8, 1 - (pred - 1) * 3) if pred > 1.002 else (min(1.2, 1 + (1 - pred) * 3) if pred < 0.998 else 1.0)
            limit = int(required_speed * pid_output * correction)
            reason = f"F:{required_speed/1024:.0f}K"
        elif phase == 'steady':
            if debug['predicted_ratio'] > 1.01: headroom = 1.0
            limit = int(required_speed * headroom * pid_output)
            reason = f"S:{required_speed/1024:.0f}K"
        elif phase == 'catch':
            if required_speed > adjusted_target * 5:
                limit = -1; reason = "C:欠速放开"
            else:
                limit = int(required_speed * headroom * pid_output)
                reason = f"C:{required_speed/1024:.0f}K"
        else:
            progress = safe_div(uploaded, target_total, 0)
            if progress >= 1.0:
                limit = C.MIN_LIMIT; reason = f"W:超{(progress-1)*100:.0f}%"
            elif progress >= 0.8:
                limit = int(required_speed * 1.01 * pid_output); reason = f"W:精控"
            elif progress >= 0.5:
                limit = int(required_speed * 1.05); reason = f"W:温控"
            else:
                limit = -1; reason = "W:预热"
        
        if limit > 0:
            limit = AdaptiveQuantizer.quantize(limit, phase, current_speed, adjusted_target, trend)
        limit = self._smooth(limit, phase)
        debug['final_limit'] = limit
        return limit, reason, debug

    def _smooth(self, new_limit: int, phase: str) -> int:
        if new_limit <= 0 or self._smooth_limit <= 0 or phase == 'finish':
            self._smooth_limit = new_limit
            return new_limit
        change = abs(new_limit - self._smooth_limit) / self._smooth_limit
        if change < 0.2:
            self._smooth_limit = new_limit
        else:
            factor = 0.5 if change >= 0.5 else 0.3
            self._smooth_limit = int((1-factor) * self._smooth_limit + factor * new_limit)
        return self._smooth_limit
    
    def reset(self):
        self.kalman.reset()
        self.speed_tracker.clear()
        self.pid.reset()
        self._smooth_limit = -1

class SpeedTracker:
    def __init__(self, max_samples: int = 600):
        self._lock = threading.Lock()
        self._samples: Deque[Tuple[float, int, int, float, float]] = deque(maxlen=max_samples)
    
    def record(self, ts: float, u: int, d: int, us: float, ds: float):
        with self._lock: self._samples.append((ts, u, d, us, ds))
    
    def get_avg_speeds(self, window: float = 300) -> Tuple[float, float]:
        now = time.time()
        with self._lock:
            samples = [(t, u, d, us, ds) for t, u, d, us, ds in self._samples if now - t <= window]
        if len(samples) < 2: return 0, 0
        first, last = samples[0], samples[-1]
        dt = last[0] - first[0]
        if dt <= 0: return 0, 0
        return safe_div(last[1]-first[1], dt, 0), safe_div(last[2]-first[2], dt, 0)
    
    def clear(self):
        with self._lock: self._samples.clear()

# 全局实例
_precision_tracker = PrecisionTracker()
