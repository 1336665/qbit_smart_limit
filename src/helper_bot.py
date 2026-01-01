# src/helper_bot.py
import threading
import queue
import requests
import time
import re
import html
from typing import Dict, Optional, TYPE_CHECKING
from datetime import datetime, timedelta
from .consts import C
from .utils import logger, log_buffer, fmt_speed, fmt_duration, fmt_size, parse_speed_str, escape_html, safe_div, wall_time

if TYPE_CHECKING:
    from .controller import Controller
    from .config import Config

class Notifier:
    """支持命令交互的 Telegram Bot (基于 v11.0.0 PRO 逻辑)"""
    
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
        
        # 运行时状态
        self.paused = False
        self.temp_target_kib: Optional[int] = None  # 临时目标速度
        self.start_time = wall_time() # 记录启动时间
        
        if self.enabled:
            self._session = requests.Session()
            # 启动消息发送线程
            threading.Thread(target=self._send_worker, daemon=True, name="TG-Sender").start()
            # 启动命令监听线程
            threading.Thread(target=self._poll_worker, daemon=True, name="TG-Poller").start()
    
    def _html_sanitize(self, msg: str) -> str:
        if not msg: return msg
        # Escape stray '&' but keep existing entities
        msg = re.sub(r'&(?![a-zA-Z]+;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', str(msg))

        if '<' not in msg: return msg

        allowed = {
            'b','strong','i','em','u','ins','s','strike','del',
            'code','pre','a','span','tg-spoiler','blockquote'
        }

        def repl(m: re.Match) -> str:
            full = m.group(0)
            inner = (m.group(1) or '').strip()
            if not inner: return html.escape(full)

            name = inner.lstrip('/').split()[0].lower()
            if name not in allowed: return html.escape(full)

            if name == 'a' and not inner.startswith('/'):
                if re.search(r'\bhref\s*=', inner, flags=re.IGNORECASE): return full
                return html.escape(full)

            if name == 'span' and not inner.startswith('/'):
                if re.search(r'tg-spoiler', inner, flags=re.IGNORECASE): return full
                return html.escape(full)

            return full

        return re.sub(r'<([^<>]+)>', repl, msg)

    def set_controller(self, controller: 'Controller'):
        self.controller = controller
    
    def close(self):
        self._stop.set()
    
    def _send_worker(self):
        while not self._stop.is_set():
            try:
                msg = self._queue.get(timeout=5)
                if not msg: continue
                try:
                    resp = self._session.post(
                        f"{self.base_url}/sendMessage",
                        json={
                            "chat_id": self.chat_id,
                            "text": self._html_sanitize(msg),
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True
                        },
                        timeout=20
                    )
                    if resp.status_code == 429:
                        retry = resp.json().get('parameters', {}).get('retry_after', 30)
                        logger.warning(f"⚠️ TG 限流! 暂停 {retry}s")
                        time.sleep(retry + 1)
                    elif resp.status_code != 200:
                        logger.warning(f"⚠️ TG发送失败 HTTP {resp.status_code}: {resp.text[:200]}")
                    time.sleep(3)
                except Exception as e:
                    logger.debug(f"TG发送失败: {e}")
                    time.sleep(5)
            except queue.Empty: pass
            except Exception: time.sleep(1)

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
            resp = self._session.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": self._html_sanitize(msg),
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                },
                timeout=15
            )
        except: pass

    def _poll_worker(self):
        try:
            self._session.get(f"{self.base_url}/getMe", timeout=10)
        except: pass

        while not self._stop.is_set():
            try:
                resp = self._session.get(
                    f"{self.base_url}/getUpdates",
                    params={"offset": self._last_update_id + 1, "timeout": 30, "allowed_updates": ["message"]},
                    timeout=35
                )
                if resp.status_code != 200:
                    time.sleep(5); continue

                data = resp.json()
                for update in data.get('result', []):
                    self._last_update_id = update.get('update_id', self._last_update_id)
                    msg = update.get('message', {}) or {}
                    text = (msg.get('text') or '').strip()
                    chat_id = str((msg.get('chat') or {}).get('id', ''))

                    if not text: continue
                    if chat_id == self.chat_id and text.startswith('/'):
                        self._handle_command(text)
            except:
                time.sleep(5)
            time.sleep(C.TG_POLL_INTERVAL)

    def _handle_command(self, text: str):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        handlers = {
            '/start': self._cmd_help, '/help': self._cmd_help, '/status': self._cmd_status,
            '/pause': self._cmd_pause, '/resume': self._cmd_resume, '/limit': self._cmd_limit,
            '/log': self._cmd_log, '/cookie': self._cmd_cookie, '/config': self._cmd_config,
            '/stats': self._cmd_stats,
        }
        handler = handlers.get(cmd, self._cmd_unknown)
        try: handler(args)
        except Exception as e: self.send_immediate(f"❌ 命令执行出错: {e}")
    
    # ═══════════════════════════════════════════
    # 命令处理器 (完全保留原逻辑)
    # ═══════════════════════════════════════════
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

🔧 <b>配置管理</b>
├ /cookie - 检查U2 Cookie状态
└ /config <参数> <值> - 修改配置
━━━━━━━━━━━━━━━━━━━━━"""
        self.send_immediate(msg)
    
    def _cmd_status(self, args: str):
        if not self.controller: return
        states = self.controller.states
        if not states:
            self.send_immediate("📭 当前没有正在监控的种子")
            return
        
        now = wall_time()
        lines = ["📊 <b>种子状态总览</b>", "━━━━━━━━━━━━━━━━━━━━━"]
        
        sorted_states = sorted(states.values(), key=lambda s: s.uploaded_in_cycle(0), reverse=True)
        for state in sorted_states[:15]:
            name = escape_html(state.name[:20])
            if state.tid and state.tid > 0:
                link = f"https://u2.dmhy.org/details.php?id={state.tid}"
                name_display = f"<a href='{link}'>{name}</a>"
            else:
                name_display = name
                
            phase = state.get_phase(now)
            tl = state.get_tl(now)
            speed = getattr(state.limit_controller.kalman, 'speed', 0) if hasattr(state, 'limit_controller') else 0
            
            phase_emoji = {'warmup': '🔥', 'catch': '🏃', 'steady': '⚖️', 'finish': '🎯'}.get(phase, '❓')
            lines.append(f"{phase_emoji} <b>{name_display}</b>")
            lines.append(f"   ↑{fmt_speed(speed)} | ⏱{tl:.0f}s | #{state.cycle_index}")
        
        if len(states) > 15: lines.append(f"\n... 还有 {len(states)-15} 个种子")
        
        status = "⏸️ 已暂停" if self.paused else "▶️ 运行中"
        target = self.temp_target_kib or self.controller.config.target_speed_kib
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"状态: {status} | 目标: {fmt_speed(target * 1024)}")
        self.send_immediate("\n".join(lines))
    
    def _cmd_pause(self, args: str):
        self.paused = True
        self.send_immediate("⏸️ <b>限速功能已暂停</b>\n所有种子将以最大速度运行")
    
    def _cmd_resume(self, args: str):
        self.paused = False
        self.send_immediate("▶️ <b>限速功能已恢复</b>")
    
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
        self.send_immediate(f"🎯 目标速度已修改为: <code>{fmt_speed(new_limit * 1024)}</code>\n(临时生效)")
    
    def _cmd_log(self, args: str):
        try: n = min(max(1, int(args) if args else 10), 30)
        except: n = 10
        logs = log_buffer.get_recent(n)
        if not logs:
            self.send_immediate("📜 暂无日志")
            return
        msg = f"📜 <b>最近 {len(logs)} 条日志</b>\n━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(f"<code>{escape_html(l)}</code>" for l in logs)
        self.send_immediate(msg)
    
    def _cmd_cookie(self, args: str):
        if not self.controller or not self.controller.u2_helper:
            self.send_immediate("❌ U2辅助功能未启用")
            return
        valid, msg = self.controller.u2_helper.check_cookie_valid()
        if valid: self.send_immediate(f"✅ <b>Cookie 正常</b>\n{msg}")
        else: self.send_immediate(f"❌ <b>Cookie 异常</b>\n{msg}")
    
    def _cmd_config(self, args: str):
        if not args:
            self.send_immediate("用法: /config <参数> <值>\n参数: qb_host, qb_user, qb_pass")
            return
        parts = args.split(maxsplit=1)
        if len(parts) != 2: return
        param, value = parts
        valid = {'qb_host': 'host', 'qb_user': 'username', 'qb_pass': 'password'}
        if param in valid and self.controller:
            self.controller.db.save_runtime_config(f"override_{valid[param]}", value)
            self.send_immediate(f"✅ 配置 {param} 已保存，重启生效")

    def _cmd_stats(self, args: str):
        if not self.controller: return
        stats = self.controller.stats
        uptime = wall_time() - self.start_time
        msg = f"""📈 <b>运行统计</b>
━━━━━━━━━━━━━━━━━━━━━
⏱️ 运行时长: <code>{fmt_duration(uptime)}</code>
📊 总周期: <code>{stats.total}</code>
📤 总上传: <code>{fmt_size(stats.uploaded)}</code>"""
        self.send_immediate(msg)

    def _cmd_unknown(self, args):
        self.send_immediate("❓ 未知命令")

    # ===========================
    # 通知方法
    # ===========================
    def startup(self, config, qb_version: str = "", u2_enabled: bool = False):
        if not self.enabled: return
        msg = f"""🚀 <b>qBit Smart Limit 已启动</b>
━━━━━━━━━━━━━━━━━━━━━
📌 <b>版本</b>: v{C.VERSION}
🎯 目标: <code>{fmt_speed(config.target_bytes)}</code>
🤖 qB核心: <code>{qb_version}</code>
🌐 U2助手: {'✅' if u2_enabled else '❌'}
🕒 时间: {datetime.now().strftime('%H:%M:%S')}"""
        self.send(msg, "startup", 0)

    def monitor_start(self, info: dict):
        if not self.enabled: return
        name = escape_html(info.get('name', 'Unknown'))
        tid = info.get('tid')
        promotion = info.get('promotion')
        total_size = info.get('total_size', 0)
        
        linked_name = f"<a href='https://u2.dmhy.org/details.php?id={tid}'>{name}</a>" if tid else name
        promo_html = f"\n🎉 <b>优惠</b>: {promotion}" if promotion and "无" not in str(promotion) else ""
            
        msg = f"""🎬 <b>开始监控</b>
━━━━━━━━━━━━━━━━━━━━━
📛 {linked_name}
📦 <b>大小</b>: {fmt_size(total_size)}{promo_html}
🕒 <b>时间</b>: {datetime.now().strftime('%H:%M:%S')}"""
        self.send(msg, f"start_{info.get('hash')}", 0)

    def check_finish(self, info: dict):
        if not self.enabled: return
        h = info.get('hash', '')
        progress = info.get('progress', 0)
        if progress >= 0.999 and h not in getattr(self, '_finish_notified', set()):
            if not hasattr(self, '_finish_notified'): self._finish_notified = set()
            self._finish_notified.add(h)
            name = escape_html(info.get('name', 'Unknown'))
            msg = f"✅ <b>下载完成</b>\n━━━━━━━━━━━━━━━━━━━━━\n📛 {name}"
            self.send(msg, f"finish_{h}", 0)

    def cycle_report(self, info: dict):
        if not self.enabled: return
        idx = info.get('idx', 0)
        if idx % 5 != 0 and idx != 1: return 

        name = escape_html(info.get('name', 'Unknown')[:30])
        speed = info.get('real_speed', 0)
        uploaded = info.get('uploaded', 0)
        msg = f"""📈 <b>周期汇报 #{idx}</b>
📛 {name}
⚡ 均速: <code>{fmt_speed(speed)}</code>
📤 本轮: <code>{fmt_size(uploaded)}</code>"""
        self.send(msg, f"cycle_{info.get('hash', '')}", 60)

    def overspeed_warning(self, name: str, real_speed: float, target: float, tid: int = None):
        msg = f"🚨 <b>超速警告</b>\n📛 {escape_html(name[:20])}\n⚠️ 速度: <code>{fmt_speed(real_speed)}</code>"
        self.send(msg, f"overspeed_{name[:10]}", 120)

    def dl_limit_notify(self, name: str, dl_limit: float, reason: str, tid: int = None):
        msg = f"📥 <b>下载限速触发</b>\n📛 {escape_html(name[:20])}\n🔒 限制: <code>{fmt_speed(dl_limit*1024)}</code>\n📝 原因: {reason}"
        self.send(msg, f"dl_limit_{name[:10]}", 60)

    def reannounce_notify(self, name: str, reason: str, tid: int = None):
        msg = f"🔄 <b>强制汇报</b>\n📛 {escape_html(name[:20])}\n📝 原因: {reason}"
        self.send(msg, f"reannounce_{name[:10]}", 60)
    
    def limit_notify(self, state, speed_limit): pass
    
    def shutdown_report(self):
        if not self.enabled: return
        self.send_immediate(f"🛑 <b>脚本已停止</b>\n⏱️ {datetime.now().strftime('%H:%M:%S')}")

    def cookie_invalid_notify(self):
        self.send("⚠️ <b>U2 Cookie 已失效</b>，请更新配置！", "cookie_invalid", 3600)
    
    def rss_notify(self, count: int, duration: float):
        if not self.enabled: return
        msg = f"📡 <b>RSS 抓取报告</b>\n━━━━━━━━━━━━━━━━━━━━━\n🌱 新增种子: <b>{count}</b> 个\n⏱️ 耗时: {duration:.2f}s"
        self.send(msg, "rss_run", 0)

    def autoremove_notify(self, info: dict):
        if not self.enabled: return
        name = escape_html(info.get('name', 'Unknown'))
        reason = escape_html(info.get('reason', 'Unknown'))
        size = fmt_size(info.get('size', 0))
        msg = f"🗑️ <b>自动删种执行</b>\n━━━━━━━━━━━━━━━━━━━━━\n📛 <b>{name}</b>\n💥 原因: {reason}\n📦 释放: <code>{size}</code>"
        self.send(msg, f"autorm_{name[:10]}", 0)
