import sqlite3
import threading
from typing import Optional, List
from .consts import C
from .utils import wall_time

class Database:
    def __init__(self, db_path: str = C.DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # 种子状态表
            c.execute('''CREATE TABLE IF NOT EXISTS torrent_states (
                hash TEXT PRIMARY KEY,
                name TEXT,
                tid INTEGER,
                promotion TEXT,
                publish_time REAL,
                cycle_index INTEGER,
                cycle_start REAL,
                cycle_start_uploaded INTEGER,
                cycle_synced INTEGER,
                cycle_interval REAL,
                total_uploaded_start INTEGER,
                session_start_time REAL,
                last_announce_time REAL,
                updated_at REAL
            )''')
            
            # 统计表
            c.execute('''CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY,
                total_cycles INTEGER,
                success_cycles INTEGER,
                precision_cycles INTEGER,
                total_uploaded INTEGER,
                start_time REAL,
                updated_at REAL
            )''')
            
            # 配置运行时状态表
            c.execute('''CREATE TABLE IF NOT EXISTS runtime_config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at REAL
            )''')
            
            conn.commit()
            conn.close()
    
    def save_torrent_state(self, state):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO torrent_states 
                (hash, name, tid, promotion, publish_time, cycle_index, cycle_start, 
                 cycle_start_uploaded, cycle_synced, cycle_interval, total_uploaded_start,
                 session_start_time, last_announce_time, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (state.hash, state.name, state.tid, state.promotion,
                 state.publish_time, state.cycle_index, state.cycle_start,
                 state.cycle_start_uploaded, 1 if state.cycle_synced else 0,
                 state.cycle_interval, state.total_uploaded_start,
                 state.session_start_time, state.last_announce_time, wall_time()))
            conn.commit()
            conn.close()
    
    def load_torrent_state(self, torrent_hash: str) -> Optional[dict]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('SELECT * FROM torrent_states WHERE hash = ?', (torrent_hash,))
            row = c.fetchone()
            conn.close()
            
            if not row: return None
            return {
                'hash': row[0], 'name': row[1], 'tid': row[2], 'promotion': row[3],
                'publish_time': row[4], 'cycle_index': row[5], 'cycle_start': row[6],
                'cycle_start_uploaded': row[7], 'cycle_synced': bool(row[8]),
                'cycle_interval': row[9], 'total_uploaded_start': row[10],
                'session_start_time': row[11], 'last_announce_time': row[12]
            }
    
    def save_stats(self, stats):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO stats 
                (id, total_cycles, success_cycles, precision_cycles, total_uploaded, start_time, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?)''',
                (stats.total, stats.success, stats.precision, stats.uploaded, stats.start, wall_time()))
            conn.commit()
            conn.close()
    
    def load_stats(self) -> Optional[dict]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('SELECT * FROM stats WHERE id = 1')
            row = c.fetchone()
            conn.close()
            
            if not row: return None
            return {
                'total': row[1], 'success': row[2], 'precision': row[3],
                'uploaded': row[4], 'start': row[5]
            }
    
    def save_runtime_config(self, key: str, value: str):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO runtime_config (key, value, updated_at) VALUES (?, ?, ?)',
                      (key, value, wall_time()))
            conn.commit()
            conn.close()
    
    def get_runtime_config(self, key: str) -> Optional[str]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('SELECT value FROM runtime_config WHERE key = ?', (key,))
            row = c.fetchone()
            conn.close()
            return row[0] if row else None
            
    def get_all_torrent_hashes(self) -> List[str]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('SELECT hash FROM torrent_states')
            rows = c.fetchall()
            conn.close()
            return [r[0] for r in rows]
