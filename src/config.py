import os
import json
from dataclasses import dataclass
from typing import Optional, Tuple
from .database import Database

@dataclass
class Config:
    host: str
    username: str
    password: str
    target_speed_kib: int
    safety_margin: float = 0.98
    log_level: str = "INFO"
    target_tracker_keyword: str = ""
    exclude_tracker_keyword: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    max_physical_speed_kib: int = 0
    api_rate_limit: int = 20
    u2_cookie: str = ""
    proxy: str = ""
    peer_list_enabled: bool = True
    enable_dl_limit: bool = True
    enable_reannounce_opt: bool = True
    
    # === 新增模块开关 ===
    flexget_enabled: bool = False
    flexget_interval_sec: int = 120
    autoremove_enabled: bool = False
    autoremove_interval_sec: int = 1800
    
    _mtime: float = 0
    
    @property
    def target_bytes(self) -> int:
        return max(1, int(self.target_speed_kib * 1024 * self.safety_margin))
    
    @property
    def max_physical_bytes(self) -> int:
        return (self.max_physical_speed_kib or 0) * 1024
    
    @classmethod
    def load(cls, path: str, db: 'Database' = None) -> Tuple[Optional['Config'], Optional[str]]:
        try:
            mtime = os.path.getmtime(path)
            with open(path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            
            cfg = cls(
                host=str(d.get('host', '')).strip(),
                username=str(d.get('username', '')).strip(),
                password=str(d.get('password', '')).strip(),
                target_speed_kib=int(d.get('target_speed_kib', 0)),
                safety_margin=float(d.get('safety_margin', 0.98)),
                log_level=str(d.get('log_level', 'INFO')),
                target_tracker_keyword=str(d.get('target_tracker_keyword', '')).strip(),
                exclude_tracker_keyword=str(d.get('exclude_tracker_keyword', '')).strip(),
                telegram_bot_token=str(d.get('telegram_bot_token', '')).strip(),
                telegram_chat_id=str(d.get('telegram_chat_id', '')).strip(),
                max_physical_speed_kib=int(d.get('max_physical_speed_kib', 0) or 0),
                api_rate_limit=int(d.get('api_rate_limit', 20) or 20),
                u2_cookie=str(d.get('u2_cookie', '')).strip(),
                proxy=str(d.get('proxy', '')).strip(),
                peer_list_enabled=bool(d.get('peer_list_enabled', True)),
                enable_dl_limit=bool(d.get('enable_dl_limit', True)),
                enable_reannounce_opt=bool(d.get('enable_reannounce_opt', True)),
                
                # === 新增参数 ===
                flexget_enabled=bool(d.get('flexget_enabled', False)),
                flexget_interval_sec=int(d.get('flexget_interval_sec', 120)),
                autoremove_enabled=bool(d.get('autoremove_enabled', False)),
                autoremove_interval_sec=int(d.get('autoremove_interval_sec', 1800)),
                
                _mtime=mtime
            )
            
            if db:
                for param, attr in [('host', 'host'), ('username', 'username'), ('password', 'password')]:
                    override = db.get_runtime_config(f"override_{attr}")
                    if override:
                        setattr(cfg, attr, override)
            
            return cfg, None
        except Exception as e:
            return None, str(e)
