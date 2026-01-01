from typing import Tuple
from .consts import C

class DownloadLimiter:
    @staticmethod
    def calc_dl_limit(state, total_uploaded: int, total_done: int, 
                      total_size: int, eta: int, up_speed: float, dl_speed: float, 
                      now: float) -> Tuple[int, str]:
        this_up = state.this_up(total_uploaded)
        this_time = state.this_time(now)
        if this_time < 2: return -1, ""
        
        avg_speed = this_up / this_time
        if avg_speed <= C.SPEED_LIMIT:
            if state.last_dl_limit > 0: return -1, "均值恢复"
            return -1, ""
        
        remaining = total_size - total_done
        if remaining <= 0: return -1, ""
        
        min_time = C.DL_LIMIT_MIN_TIME * (2 if state.last_up_limit > 0 else 1)
        
        if state.last_dl_limit <= 0:
            if 0 < eta <= min_time:
                denominator = this_up / C.SPEED_LIMIT - this_time + C.DL_LIMIT_BUFFER
                if denominator <= 0: return C.DL_LIMIT_MIN, "超速严重"
                dl_limit = remaining / denominator / 1024
                return max(C.DL_LIMIT_MIN, int(dl_limit)), f"均值超限"
        else:
            if avg_speed >= C.SPEED_LIMIT:
                if dl_speed / 1024 < 2 * state.last_dl_limit:
                    denominator = this_up / C.SPEED_LIMIT - this_time + C.DL_LIMIT_ADJUST_BUFFER
                    if denominator <= 0: return C.DL_LIMIT_MIN, "超速严重"
                    new_limit = remaining / denominator / 1024
                    new_limit = min(new_limit, 512000)
                    if new_limit > 1.5 * state.last_dl_limit:
                        new_limit = 1.5 * state.last_dl_limit
                    elif new_limit < state.last_dl_limit:
                        new_limit = new_limit / 1.5
                    return max(C.DL_LIMIT_MIN, int(new_limit)), "调整中"
                return state.last_dl_limit, "保持"
            else:
                return -1, "均值恢复"
        return -1, ""

class ReannounceOptimizer:
    @staticmethod
    def should_reannounce(state, total_uploaded: int, total_done: int,
                          total_size: int, up_speed: float, dl_speed: float, 
                          now: float) -> Tuple[bool, str]:
        if state.last_reannounce > 0 and now - state.last_reannounce < C.REANNOUNCE_MIN_INTERVAL:
            return False, ""
        
        this_up = state.this_up(total_uploaded)
        this_time = state.this_time(now)
        if this_time < 30: return False, ""
        
        avg_up, avg_dl = state.speed_tracker.get_avg_speeds(C.REANNOUNCE_SPEED_SAMPLES)
        if avg_up <= C.SPEED_LIMIT or avg_dl <= 0: return False, ""
        
        remaining = total_size - total_done
        if remaining <= 0: return False, ""
        
        announce_interval = state.get_announce_interval()
        complete_time = remaining / avg_dl + now
        perfect_time = complete_time - announce_interval * C.SPEED_LIMIT / avg_up
        
        if this_up / this_time > C.SPEED_LIMIT:
            earliest = (this_up - C.SPEED_LIMIT * this_time) / (45 * 1024 * 1024) + now
        else:
            earliest = now
        
        if earliest - (now - this_time) < C.REANNOUNCE_MIN_INTERVAL:
            return False, ""
        
        if earliest > perfect_time:
            if now >= earliest:
                if this_up / this_time > C.SPEED_LIMIT:
                    return True, "优化汇报"
            else:
                if earliest < perfect_time + 60:
                    state.waiting_reannounce = True
                    return False, "等待汇报"
        return False, ""
    
    @staticmethod
    def check_waiting_reannounce(state, total_uploaded: int, 
                                  now: float) -> Tuple[bool, str]:
        if not state.waiting_reannounce: return False, ""
        this_up = state.this_up(total_uploaded)
        this_time = state.this_time(now)
        if this_time < C.REANNOUNCE_MIN_INTERVAL: return False, ""
        avg_speed = this_up / this_time
        if avg_speed < C.SPEED_LIMIT:
            return True, "均值恢复"
        return False, ""
