cat > /opt/qbit-smart-limit/src/consts.py <<EOF
import os

class C:
    VERSION = "11.5.0 PRO"
    
    # ==========================================
    # 👇 新增：RSS 和 AutoRemove 必须的路径配置
    # ==========================================
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Native RSS 路径
    RSS_DIR = os.path.join(BASE_DIR, "rss_data")
    RSS_RULES = os.path.join(RSS_DIR, "feeds.json")
    RSS_HISTORY = os.path.join(RSS_DIR, "history.json")
    RSS_LOG = "/var/log/qsl-rss.log"
    
    # AutoRemove 路径
    AUTORM_DIR = os.path.join(BASE_DIR, "autoremove")
    AUTORM_RULES = os.path.join(AUTORM_DIR, "rules.json")
    AUTORM_STATE = os.path.join(AUTORM_DIR, "state.json")
    AUTORM_LOG = "/var/log/qsl-autoremove.log"

    # ==========================================
    # 👇 原有配置：核心算法与逻辑参数 (保持不变)
    # ==========================================
    
    # 周期阶段定义
    PHASE_WARMUP = "warmup"
    PHASE_CATCH = "catch"
    PHASE_STEADY = "steady"
    PHASE_FINISH = "finish"
    
    # 时间参数
    FINISH_TIME = 30
    STEADY_TIME = 120
    
    # 精度控制
    PRECISION_PERFECT = 0.001
    PRECISION_GOOD = 0.005
    
    # 保护机制
    SPEED_PROTECT_RATIO = 2.5
    SPEED_PROTECT_LIMIT = 1.3
    PROGRESS_PROTECT = 0.90
    MIN_LIMIT = 4096
    
    # PID 参数 (原版核心逻辑)
    PID_PARAMS = {
        'warmup': {'kp': 0.3, 'ki': 0.05, 'kd': 0.02, 'headroom': 1.03},
        'catch':  {'kp': 0.5, 'ki': 0.10, 'kd': 0.05, 'headroom': 1.02},
        'steady': {'kp': 0.6, 'ki': 0.15, 'kd': 0.08, 'headroom': 1.005},
        'finish': {'kp': 0.8, 'ki': 0.20, 'kd': 0.12, 'headroom': 1.001},
    }
    
    # 量化步长
    QUANT_STEPS = {'finish': 256, 'steady': 512, 'catch': 2048, 'warmup': 4096}
    
    # 卡尔曼滤波参数
    KALMAN_Q_SPEED = 0.1
    KALMAN_Q_ACCEL = 0.05
    KALMAN_R = 0.5
    
    # 速度窗口权重
    SPEED_WINDOWS = [5, 15, 30, 60]
    WINDOW_WEIGHTS = {
        'warmup': {5: 0.1, 15: 0.2, 30: 0.3, 60: 0.4},
        'catch':  {5: 0.2, 15: 0.3, 30: 0.3, 60: 0.2},
        'steady': {5: 0.3, 15: 0.3, 30: 0.2, 60: 0.2},
        'finish': {5: 0.5, 15: 0.3, 30: 0.15, 60: 0.05},
    }
    
    # 杂项配置
    MAX_REANNOUNCE = 86400
    PROPS_CACHE = {"finish": 0.2, "steady": 0.5, "catch": 1.0, "warmup": 2.0}
    LOG_INTERVAL = 20
    CONFIG_CHECK = 30
    ANNOUNCE_INTERVAL_NEW = 1800
    ANNOUNCE_INTERVAL_WEEK = 2700
    ANNOUNCE_INTERVAL_OLD = 3600
    SPEED_LIMIT = 50 * 1024 * 1024 # 50MB/s 软顶
    
    DL_LIMIT_MIN_TIME = 20
    DL_LIMIT_BUFFER = 30
    DL_LIMIT_MIN = 512
    DL_LIMIT_ADJUST_BUFFER = 60
    
    REANNOUNCE_WAIT_LIMIT = 5120
    REANNOUNCE_MIN_INTERVAL = 900
    REANNOUNCE_SPEED_SAMPLES = 300
    
    PEER_LIST_CHECK_INTERVAL = 300
    TID_SEARCH_INTERVAL = 60
    
    DB_PATH = "qbit_smart_limit.db"
    DB_SAVE_INTERVAL = 180
    TG_POLL_INTERVAL = 2
    COOKIE_CHECK_INTERVAL = 3600
EOF
