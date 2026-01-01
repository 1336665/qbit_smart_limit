import time
import threading
import signal
import sys
import qbittorrentapi
from .config import Config
from .database import Database
from .logic import Logic
# === 注意这里：必须导入 Notifier ===
from .helper_bot import Notifier
from .workers import NativeRssWorker, AutoRemoveWorker
from .consts import C
from .utils import logger

class Controller:
    def __init__(self, config_path):
        self.running = True
        self.config = Config(config_path)
        self.db = Database()
        
        # === 初始化通知器 ===
        self.notifier = Notifier(self) 
        
        self.client = None
        self.logic = Logic(self)
        
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

    def _connect(self):
        try:
            self.client = qbittorrentapi.Client(
                host=self.config.host,
                username=self.config.username,
                password=self.config.password
            )
            self.client.auth_log_in()
            logger.info(f"✅ qBittorrent 已连接: v{self.client.app.version}")
            
            # 发送启动通知
            if hasattr(self, 'notifier'):
                self.notifier.startup(self.config, self.client.app.version)
                
        except Exception as e:
            logger.error(f"无法连接 qBittorrent: {e}")
            self.client = None

    def stop(self, signum=None, frame=None):
        self.running = False
        logger.info("正在停止服务...")
        if hasattr(self, 'notifier'):
            try:
                self.notifier.shutdown_report()
                self.notifier.close()
            except: pass

    def run(self):
        logger.info(f"qBit Smart Limit {C.VERSION} 启动中...")
        self._connect()
        
        # 启动工作线程
        threads = [
            NativeRssWorker(self),
            AutoRemoveWorker(self)
        ]
        
        for t in threads: t.start()
        
        # 主循环
        while self.running:
            try:
                if not self.client:
                    self._connect()
                time.sleep(5)
            except Exception as e:
                logger.error(f"主循环异常: {e}")
                time.sleep(5)

