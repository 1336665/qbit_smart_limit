cat > /opt/qbit-smart-limit/src/helper_bot.py <<EOF
import threading
import queue
import requests
import time
import re
import html
from typing import Dict, Optional, TYPE_CHECKING
from datetime import datetime
from .consts import C
from .utils import logger, log_buffer, fmt_speed, fmt_duration, fmt_size, parse_speed_str, escape_html, safe_div, wall_time

if TYPE_CHECKING:
    from .controller import Controller

class Notifier:
    def __init__(self, controller: 'Controller'):
        token = controller.config.telegram_bot_token
        chat_id = controller.config.telegram_chat_id
        
        self.enabled = bool(token and chat_id)
        self.token = token
        self.chat_id = str(chat_id).strip()
        self.controller = controller
        self.base_url = f"https://api.telegram.org/bot{token}" if token else ""
        
        self._queue: queue.Queue = queue.Queue(maxsize=100)
        self._last_update_id = 0
        self._last_send: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        
        self.paused = False
        self.temp_target_kib: Optional[int] = None
        
        if self.enabled:
            self._session = requests.Session()
            threading.Thread(target=self._send_worker, daemon=True, name="TG-Sender").start()
            threading.Thread(target=self._poll_worker, daemon=True, name="TG-Poller").start()
    
    def close(self):
        self._stop.set()
    
    def _html_sanitize(self, msg: str) -> str:
        if not msg: return msg
        msg = re.sub(r'&(?![a-zA-Z]+;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', str(msg))
        if '<' not in msg: return msg
        allowed = {'b','strong','i','em','u','ins','s','strike','del','code','pre','a','span','tg-spoiler','blockquote'}
        def repl(m: re.Match) -> str:
            full = m.group(0)
            inner = (m.group(1) or '').strip()
            if not inner: return html.escape(full)
            name = inner.lstrip('/').split()[0].lower()
            if name not in allowed: return html.escape(full)
            if name == 'a' and not inner.startswith('/') and not re.search(r'\bhref\s*=', inner, flags=re.IGNORECASE):
                return html.escape(full)
            return full
        return re.sub(r'<([^<>]+)>', repl, msg)

    def _send_worker(self):
        while not self._stop.is_set():
            try:
                msg = self._queue.get(timeout=5)
                if not msg: continue
                try:
                    resp = self._session.post(
                        f"{self.base_url}/sendMessage",
                        json={"chat_id": self.chat_id, "text": self._html_sanitize(msg), "parse_mode": "HTML", "disable_web_page_preview": True},
                        timeout=20
                    )
                    if resp.status_code == 429:
                        time.sleep(resp.json().get('parameters', {}).get('retry_after', 30) + 1)
                    time.sleep(3)
                except Exception:
                    time.sleep(5)
            except: pass

    def send(self, msg: str, key: str = None, interval: int = 60):
        if not self.enabled: return
        if key:
            with self._lock:
                now = wall_time()
                if key in self._last_send and now - self._last_send[key] < max(10, interval): return
                self._last_send[key] = now
        try: self._queue.put_nowait(msg)
        except: pass
    
    def send_immediate(self, msg: str):
        if not self.enabled: return
        try:
            self._session.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": self._html_sanitize(msg), "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=15
            )
        except: pass

    def _poll_worker(self):
        while not self._stop.is_set():
            try:
                resp = self._session.get(f"{self.base_url}/getUpdates", params={"offset": self._last_update_id + 1, "timeout": 30, "allowed_updates": ["message"]}, timeout=35)
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get('result', []):
                        self._last_update_id = update.get('update_id', self._last_update_id)
                        msg = update.get('message', {})
                        text = (msg.get('text') or '').strip()
                        chat_id = str((msg.get('chat') or {}).get('id', ''))
                        if text and chat_id == self.chat_id and text.startswith('/'):
                            self._handle_command(text)
            except: time.sleep(5)
            time.sleep(C.TG_POLL_INTERVAL)

    def _handle_command(self, text: str):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        handlers = {
            '/start': self._cmd_help, '/help': self._cmd_help, '/status': self._cmd_status,
            '/pause': self._cmd_pause, '/resume': self._cmd_resume, '/limit': self._cmd_limit,
            '/log': self._cmd_log, '/config': self._cmd_config, '/stats': self._cmd_stats
        }
        handler = handlers.get(cmd, self._cmd_unknown)
        try: handler(args)
        except Exception as e: self.send_immediate(f"❌ 命令执行出错: {e}")

    def _cmd_help(self, args: str):
        msg = """🤖 <b>qBit Smart Limit 命令帮助</b>
━━━━━━━━━━━━━━━━━━━━━
📊 <b>状态查询</b>
├ /status - 查看所有种子状态
├ /stats - 查看统计信息
└ /log [n] - 查看最近n条日志

⚙️ <b>控制命令</b>
├ /pause - 暂停限速功能
├ /resume - 恢复限速功能
└ /limit <速度> - 设置目标速度
   例: /limit 100M 或 /limit 51200K
━━━━━━━━━━━━━━━━━━━━━
💡 速度单位支持: K/M/G (KiB)"""
        self.send_immediate(msg)

    def _cmd_status(self, args: str):
        if not self.controller:
            self.send_immediate("❌ 控制器未初始化")
            return
        
        states = self.controller.states
        if not states:
            self.send_immediate("📭 当前没有正在监控的种子")
            return
        
        now = wall_time()
        lines = ["📊 <b>种子状态总览</b>", "━━━━━━━━━━━━━━━━━━━━━"]
        
        for h, state in list(states.items())[:10]:
            name = escape_html(state.name[:25])
            phase = state.get_phase(now)
            tl = state.get_tl(now)
            # 兼容性处理
            speed = getattr(state.limit_controller.kalman, 'x', 0) if hasattr(state, 'limit_controller') else 0
            
            phase_emoji = {'warmup': '🔥', 'catch': '🏃', 'steady': '⚖️', 'finish': '🎯'}.get(phase, '❓')
            lines.append(f"{phase_emoji} <b>{name}</b>")
            lines.append(f"   ↑{fmt_speed(speed)} | ⏱{tl:.0f}s | 周期#{state.cycle_index}")
        
        if len(states) > 10:
            lines.append(f"\n... 还有 {len(states)-10} 个种子")
        
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
        status = "⏸️ 已暂停" if self.paused else "▶️ 运行中"
        target = self.temp_target_kib or self.controller.config.target_speed_kib
        lines.append(f"状态: {status} | 目标: {fmt_speed(target * 1024)}")
        self.send_immediate("\n".join(lines))

    def _cmd_pause(self, args: str):
        self.paused = True
        self.send_immediate("⏸️ <b>限速功能已暂停</b>\n所有种子将以最大速度运行")
        logger.warning("⏸️ 用户暂停了限速功能")

    def _cmd_resume(self, args: str):
        self.paused = False
        self.send_immediate("▶️ <b>限速功能已恢复</b>")
        logger.info("▶️ 用户恢复了限速功能")

    def _cmd_limit(self, args: str):
        if not args:
            current = self.temp_target_kib or (self.controller.config.target_speed_kib if self.controller else 0)
            self.send_immediate(f"🎯 当前目标: <code>{fmt_speed(current * 1024)}</code>")
            return
        new_limit = parse_speed_str(args)
        if not new_limit or new_limit <= 0:
            self.send_immediate("❌ 无效速度值")
            return
        self.temp_target_kib = new_limit
        self.send_immediate(f"🎯 目标速度已修改为: <code>{fmt_speed(new_limit * 1024)}</code>\n(临时生效，重启后恢复)")

    def _cmd_log(self, args: str):
        try: n = min(max(1, int(args) if args else 10), 30)
        except: n = 10
        logs = log_buffer.get_recent(n)
        if not logs:
            self.send_immediate("📜 暂无日志")
            return
        msg = f"📜 <b>最近 {len(logs)} 条日志</b>\n━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(f"<code>{escape_html(l)}</code>" for l in logs)
        self.send_immediate(msg)

    def _cmd_config(self, args: str):
        self.send_immediate("⚠️ 请使用 WebUI 或修改配置文件 config.json")

    def _cmd_stats(self, args: str):
        self.send_immediate("📊 统计功能开发中...")

    def _cmd_unknown(self, args):
        self.send_immediate("❓ 未知命令，发送 /help 查看帮助")

    # ==========================================
    # 👇 关键修复：添加 u2_enabled 参数 👇
    # ==========================================
    def startup(self, config, qb_version: str = "", u2_enabled: bool = False):
        if not self.enabled: return
        msg = f"""🚀 <b>qBit Smart Limit 已启动</b>
━━━━━━━━━━━━━━━━━━━━━
📌 <b>版本</b>: v{C.VERSION}
🎯 目标速度: <code>{fmt_speed(config.target_bytes)}</code>
🤖 qBittorrent: <code>{qb_version}</code>
🌐 U2辅助: {'✅' if u2_enabled else '❌'}
🕒 启动时间: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"""
        self.send(msg, "startup", 0)

    def monitor_start(self, info: dict):
        if not self.enabled: return
        name = escape_html(info.get('name', 'Unknown'))
        total_size = info.get('total_size', 0)
        msg = f"🎬 <b>开始监控</b>\n📛 {name}\n📦 大小: <code>{fmt_size(total_size)}</code>"
        self.send(msg, f"start_{info.get('hash')}", 0)

    def check_finish(self, info: dict):
        if not self.enabled: return
        h = info.get('hash', '')
        progress = info.get('progress', 0)
        if progress >= 0.999 and h not in getattr(self, '_finish_notified', set()):
            if not hasattr(self, '_finish_notified'): self._finish_notified = set()
            self._finish_notified.add(h)
            name = escape_html(info.get('name', 'Unknown'))
            msg = f"🎉 <b>下载完成</b>\n📛 {name}\n⏱️ 时间: <code>{datetime.now().strftime('%H:%M:%S')}</code>"
            self.send(msg, f"finish_{h}", 0)

    def cycle_report(self, info: dict):
        if not self.enabled: return
        name = escape_html(info.get('name', 'Unknown')[:20])
        idx = info.get('idx', 0)
        uploaded = info.get('uploaded', 0)
        speed = info.get('real_speed', 0)
        msg = f"📊 <b>周期汇报 #{idx}</b>\n📛 {name}\n📤 上传: <code>{fmt_size(uploaded)}</code>\n📈 均速: <code>{fmt_speed(speed)}</code>"
        self.send(msg, f"cycle_{info.get('hash', '')}", 5)

    def overspeed_warning(self, name: str, real_speed: float, target: float, tid: int = None):
        msg = f"🚨 <b>超速警告</b>\n📛 {escape_html(name[:20])}\n⚠️ 速度: <code>{fmt_speed(real_speed)}</code>"
        self.send(msg, f"overspeed_{name[:10]}", 120)

    def dl_limit_notify(self, name: str, dl_limit: float, reason: str, tid: int = None):
        msg = f"📥 <b>下载限速</b>\n📛 {escape_html(name[:20])}\n🔒 限制: <code>{fmt_speed(dl_limit*1024)}</code>\n📝 {reason}"
        self.send(msg, f"dl_limit_{name[:10]}", 60)

    def reannounce_notify(self, name: str, reason: str, tid: int = None):
        msg = f"🔄 <b>强制汇报</b>\n📛 {escape_html(name[:20])}\n📝 {reason}"
        self.send(msg, f"reannounce_{name[:10]}", 60)
        
    def limit_notify(self, state, speed_limit):
        pass
    
    def shutdown_report(self):
        if not self.enabled: return
        self.send_immediate(f"🛑 <b>脚本已停止</b>\n⏱️ {datetime.now().strftime('%H:%M:%S')}")

    def cookie_invalid_notify(self):
        self.send("⚠️ <b>U2 Cookie 已失效</b>，请更新配置！", "cookie_invalid", 3600)

    def rss_notify(self, count: int, duration: float):
        if not self.enabled: return
        msg = f"""📡 <b>原生 RSS 抓取成功</b>
━━━━━━━━━━━━━━━━━━━━━
🌱 新增种子: <code>{count}</code> 个
⏱️ 耗时: <code>{duration:.1f}s</code>"""
        self.send(msg, "rss_run", 0)

    def autoremove_notify(self, info: dict):
        if not self.enabled: return
        name = escape_html(info.get('name', 'Unknown')).replace('[', '(').replace(']', ')')
        reason = escape_html(info.get('reason', 'Unknown'))
        size = fmt_size(info.get('size', 0))
        emoji = "🗑️"
        if "极危" in reason or "红色" in reason: emoji = "🚨"
        elif "空间" in reason: emoji = "⚠️"
        msg = f"""{emoji} <b>自动删种执行</b>
━━━━━━━━━━━━━━━━━━━━━
📛 <b>{name}</b>
💥 <b>删除原因</b>
└ {reason}
📦 释放空间: <code>{size}</code>"""
        self.send(msg, f"autorm_{name[:10]}", 0)
EOF

systemctl restart qbit-smart-limit
systemctl status qbit-smart-limit
