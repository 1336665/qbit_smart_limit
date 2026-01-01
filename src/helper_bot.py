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

class TelegramBot:
    def __init__(self, token: str, chat_id: str, controller: 'Controller' = None):
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
    
    def set_controller(self, controller: 'Controller'):
        self.controller = controller
    
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
            if name == 'span' and not inner.startswith('/') and not re.search(r'tg-spoiler', inner, flags=re.IGNORECASE):
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
                except Exception as e:
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
            '/log': self._cmd_log, '/cookie': self._cmd_cookie, '/config': self._cmd_config,
            '/stats': self._cmd_stats
        }
        handler = handlers.get(cmd, self._cmd_unknown)
        try: handler(args)
        except Exception as e: self.send_immediate(f"❌ 命令执行出错: {e}")

    def _cmd_help(self, args: str):
        self.send_immediate("🤖 <b>qBit Smart Limit 命令帮助</b>\n━━━━━━━━━━━━━━━━━━━━━\n📊 <b>状态查询</b>\n├ /status - 查看状态\n├ /stats - 查看统计\n└ /log [n] - 查看日志\n\n⚙️ <b>控制</b>\n├ /pause - 暂停\n├ /resume - 恢复\n└ /limit <速度> - 设置目标\n\n🔧 <b>配置</b>\n├ /cookie - 检查Cookie\n└ /config <参数> <值> - 修改配置")

    def _cmd_status(self, args: str):
        if not self.controller or not self.controller.states:
            self.send_immediate("📭 当前没有正在监控的种子")
            return
        lines = ["📊 <b>种子状态总览</b>", "━━━━━━━━━━━━━━━━━━━━━"]
        now = wall_time()
        for h, state in list(self.controller.states.items())[:10]:
            phase = state.get_phase(now)
            emoji = {'warmup': '🔥', 'catch': '🏃', 'steady': '⚖️', 'finish': '🎯'}.get(phase, '❓')
            lines.append(f"{emoji} <b>{escape_html(state.name[:25])}</b>")
            lines.append(f"   ↑{fmt_speed(state.limit_controller.kalman.speed)} | ⏱{state.get_tl(now):.0f}s | #{state.cycle_index}")
        status = "⏸️ 已暂停" if self.paused else "▶️ 运行中"
        target = self.temp_target_kib or (self.controller.config.target_speed_kib if self.controller else 0)
        lines.append(f"\n状态: {status} | 目标: {fmt_speed(target * 1024)}")
        self.send_immediate("\n".join(lines))

    def _cmd_pause(self, args: str):
        self.paused = True
        self.send_immediate("⏸️ <b>已暂停</b>")

    def _cmd_resume(self, args: str):
        self.paused = False
        self.send_immediate("▶️ <b>已恢复</b>")

    def _cmd_limit(self, args: str):
        if not args:
            cur = self.temp_target_kib or (self.controller.config.target_speed_kib if self.controller else 0)
            self.send_immediate(f"🎯 当前: {fmt_speed(cur*1024)}\n用法: /limit 100M")
            return
        nl = parse_speed_str(args)
        if nl and nl > 0:
            self.temp_target_kib = nl
            self.send_immediate(f"🎯 目标已改为: <code>{fmt_speed(nl*1024)}</code> (临时)")
        else:
            self.send_immediate("❌ 无效值")

    def _cmd_log(self, args: str):
        try: n = min(max(1, int(args) if args else 10), 30)
        except: n = 10
        logs = log_buffer.get_recent(n)
        self.send_immediate(f"📜 <b>最近 {len(logs)} 条日志</b>\n" + "\n".join(f"<code>{escape_html(l)}</code>" for l in logs))

    def _cmd_cookie(self, args: str):
        if not self.controller or not self.controller.u2_helper:
            self.send_immediate("❌ U2辅助未启用")
            return
        v, m = self.controller.u2_helper.check_cookie_valid()
        self.send_immediate(f"{'✅' if v else '❌'} {m}")

    def _cmd_config(self, args: str):
        parts = args.split(maxsplit=1)
        if len(parts) != 2:
            self.send_immediate("用法: /config <qb_host|qb_user|qb_pass> <val>")
            return
        k, v = parts
        if k in ['qb_host', 'qb_user', 'qb_pass'] and self.controller:
            self.controller.db.save_runtime_config(f"override_{{'qb_host':'host','qb_user':'username','qb_pass':'password'}[k]}", v)
            self.send_immediate(f"✅ {k} 已更新，重启生效")

    def _cmd_stats(self, args: str):
        if not self.controller: return
        s = self.controller.stats
        self.send_immediate(f"📈 <b>统计</b>\n运行时长: {fmt_duration(wall_time()-s.start)}\n周期: {s.total}\n达标率: {safe_div(s.success,s.total,0)*100:.1f}%\n总上传: {fmt_size(s.uploaded)}")

    def _cmd_unknown(self, args): self.send_immediate("❓ 未知命令")

    def startup(self, config, qb_v, u2):
        self.send(f"🚀 <b>启动成功</b>\nv{C.VERSION}\n目标: {fmt_speed(config.target_bytes)}\nU2: {'✅' if u2 else '❌'}", "startup")

    def monitor_start(self, info):
        lnk = f'<a href="https://u2.dmhy.org/details.php?id={info["tid"]}&hit=1">{escape_html(info["name"])}</a>' if info.get('tid') else f'<b>{escape_html(info["name"])}</b>'
        self.send(f"🎬 <b>开始监控</b>\n{lnk}\n大小: {fmt_size(info['total_size'])}\n优惠: {info.get('promotion')}", f"start_{info['hash']}")

    def check_finish(self, info):
        if info['progress'] >= 0.999 and info['hash'] not in getattr(self, '_finish_notified', set()):
            if not hasattr(self, '_finish_notified'): self._finish_notified = set()
            self._finish_notified.add(info['hash'])
            self.send(f"🎉 <b>下载完成</b>\n{escape_html(info['name'])}\n上传: {fmt_size(info['total_uploaded'])}", f"finish_{info['hash']}")

    def cycle_report(self, info):
        st = "🎯 完美" if info['ratio']>=0.99 else ("✅ 达标" if info['ratio']>=0.95 else ("👍 良好" if info['ratio']>=0.9 else "⚠️ 欠速"))
        self.send(f"📊 <b>汇报 #{info['idx']}</b>\n{escape_html(info['name'][:30])}\n上传: {fmt_size(info['uploaded'])}\n均速: {fmt_speed(info['real_speed'])}\n达标: {st} ({info['ratio']*100:.1f}%)", f"cycle_{info['hash']}", 5)

    def overspeed_warning(self, name, rs, t, tid):
        self.send(f"🚨 <b>超速警告</b>\n{escape_html(name[:20])}\n实速: {fmt_speed(rs)}\n目标: {fmt_speed(t)}", f"over_{name[:5]}", 120)

    def dl_limit_notify(self, name, l, r, tid):
        self.send(f"📥 <b>下载限速</b>\n{escape_html(name[:20])}\n限速: {fmt_speed(l*1024)}\n原因: {r}", f"dl_{name[:5]}", 60)

    def reannounce_notify(self, name, r, tid):
        self.send(f"🔄 <b>强制汇报</b>\n{escape_html(name[:20])}\n原因: {r}", f"re_{name[:5]}", 60)

    def cookie_invalid_notify(self):
        self.send("🔴 <b>Cookie 已失效</b>\n请尽快更新", "cookie_inv", 3600)

    def shutdown_report(self):
        self.send_immediate("🛑 <b>脚本已停止</b>")
