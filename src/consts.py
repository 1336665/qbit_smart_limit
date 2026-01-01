class C:
    VERSION = "11.0.0 PRO"
    
    PHASE_WARMUP = "warmup"
    PHASE_CATCH = "catch"
    PHASE_STEADY = "steady"
    PHASE_FINISH = "finish"
    
    FINISH_TIME = 30
    STEADY_TIME = 120
    
    PRECISION_PERFECT = 0.001
    PRECISION_GOOD = 0.005
    
    SPEED_PROTECT_RATIO = 2.5
    SPEED_PROTECT_LIMIT = 1.3
    PROGRESS_PROTECT = 0.90
    
    MIN_LIMIT = 4096
    
    PID_PARAMS = {
        'warmup': {'kp': 0.3, 'ki': 0.05, 'kd': 0.02, 'headroom': 1.03},
        'catch':  {'kp': 0.5, 'ki': 0.10, 'kd': 0.05, 'headroom': 1.02},
        'steady': {'kp': 0.6, 'ki': 0.15, 'kd': 0.08, 'headroom': 1.005},
        'finish': {'kp': 0.8, 'ki': 0.20, 'kd': 0.12, 'headroom': 1.001},
    }
    
    QUANT_STEPS = {'finish': 256, 'steady': 512, 'catch': 2048, 'warmup': 4096}
    
    KALMAN_Q_SPEED = 0.1
    KALMAN_Q_ACCEL = 0.05
    KALMAN_R = 0.5
    
    SPEED_WINDOWS = [5, 15, 30, 60]
    WINDOW_WEIGHTS = {
        'warmup': {5: 0.1, 15: 0.2, 30: 0.3, 60: 0.4},
        'catch':  {5: 0.2, 15: 0.3, 30: 0.3, 60: 0.2},
        'steady': {5: 0.3, 15: 0.3, 30: 0.2, 60: 0.2},
        'finish': {5: 0.5, 15: 0.3, 30: 0.15, 60: 0.05},
    }
    
    MAX_REANNOUNCE = 86400
    PROPS_CACHE = {"finish": 0.2, "steady": 0.5, "catch": 1.0, "warmup": 2.0}
    LOG_INTERVAL = 20
    CONFIG_CHECK = 30
    
    ANNOUNCE_INTERVAL_NEW = 1800
    ANNOUNCE_INTERVAL_WEEK = 2700
    ANNOUNCE_INTERVAL_OLD = 3600
    
    SPEED_LIMIT = 50 * 1024 * 1024
    
    DL_LIMIT_MIN_TIME = 20
    DL_LIMIT_BUFFER = 30
    DL_LIMIT_MIN = 512
    DL_LIMIT_ADJUST_BUFFER = 60
    
    REANNOUNCE_WAIT_LIMIT = 5120
    REANNOUNCE_MIN_INTERVAL = 900
    REANNOUNCE_SPEED_SAMPLES = 300
    
    PEER_LIST_CHECK_INTERVAL = 300
    TID_SEARCH_INTERVAL = 60
    
    # 数据库相关
    DB_PATH = "qbit_smart_limit.db"
    DB_SAVE_INTERVAL = 180
    
    # TG Bot 轮询
    TG_POLL_INTERVAL = 2
    COOKIE_CHECK_INTERVAL = 3600
