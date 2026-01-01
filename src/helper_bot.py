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
        self.start_time = wall_time() # 记录启动时间
        
        if self.enabled:
            self._session = requests.Session()
            threading.Thread(target=self._send_worker, daemon=True, name="TG-Sender").start()
            threading.Thread(target=self._poll_worker, daemon=True, name="TG-Poller").start()
    
    def close(self):
        self._stop.set()
    
    def _html_sanitize(self, msg: str) -> str:
        # 基本 HTML 转义，保留 Telegram 支持的标签
        if not msg: return msg
        # 简单处理：先全部转义，再把我们要用的标签还原回来是不太安全的
        # 这里我们假设输入的 msg 已经是构造好的 HTML (部分转义)，或者我们只转义变量部分
        # 为防止报错，这里只做简单的 & 符号处理，具体转义由调用方负责
        return msg

    def _send_worker(self):
        while not self._stop.is_set():
            try:
                msg = self._queue.get(timeout=5)
                if not msg: continue
                try:
                    resp = self._session.post(
                        f"{self.base_url}/sendMessage",
                        json={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
                        timeout=20
                    )
                    if resp.status_code == 429:
                        time.sleep(resp.json().get('parameters', {}).get('retry_after', 30) + 1)
                    time.sleep(3)
                except Exception as e:
                    logger.debug(f"TG send fail: {e}")
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
                json={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
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

    # ===========================
    # 🎮 命令处理
    # ===========================

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
        msg = """🤖 <b>qBit Smart Limit 命令列表</b>
━━━━━━━━━━━━━━━━━━━━━
📊 <b>监控</b>
/status - 查看当前种子状态
/stats - 查看运行统计 (上传量/速度)
/log - 查看最近日志

⚙️ <b>控制</b>
/pause - 暂停所有限速 (全速上传)
/resume - 恢复智能限速
/limit <数值> - 临时修改目标速度
   (例: /limit 50M 或 /limit 10000)

ℹ️ <b>其他</b>
/help - 显示此帮助"""
        self.send_immediate(msg)

    def _cmd_status(self, args: str):
        if not self.controller: return
        states = self.controller.states
        if not states:
            self.send_immediate("📭 当前没有正在监控的种子")
            return
        
        now = wall_time()
        lines = [f"📊 <b>监控列表 ({len(states)})</b>", "━━━━━━━━━━━━━━━━━━━━━"]
        
        # 按上传量排序
        sorted_states = sorted(states.values(), key=lambda s: s.uploaded_in_cycle(0), reverse=True)
        
        for state in sorted_states[:15]: # 最多显示15个
            name = escape_html(state.name[:20])
            # 构建超链接 (如果有 TID)
            if state.tid and state.tid > 0:
                link = f"https://u2.dmhy.org/details.php?id={state.tid}"
                name_display = f"<a href='{link}'>{name}</a>"
            else:
                name_display = name
                
            phase = state.get_phase(now)
            tl = state.get_tl(now)
            # 尝试获取速度
            speed_kib = 0
            if hasattr(state, 'limit_controller'):
                speed_kib = getattr(state.limit_controller.kalman, 'x', 0)
            
            phase_icon = {'warmup': '🔥', 'catch': '🚀', 'steady': '⚖️', 'finish': '🏁'}.get(phase, '❓')
            promo_tag = f"[{state.promotion}]" if state.promotion and "无" not in state.promotion else ""
            
            lines.append(f"{phase_icon} <b>{name_display}</b> {promo_tag}")
            lines.append(f"   └ ⚡{fmt_speed(speed_kib)} | ⏱{tl:.0f}s | #{state.cycle_index}")
        
        if len(states) > 15:
            lines.append(f"\n... 还有 {len(states)-15} 个种子")
            
        status_icon = "⏸️ 已暂停" if self.paused else "▶️ 运行中"
        target = self.temp_target_kib or self.controller.config.target_speed_kib
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"状态: {status_icon} | 目标: {fmt_speed(target * 1024)}")
        self.send_immediate("\n".join(lines))

    def _cmd_stats(self, args: str):
        if not self.controller: return
        
        # 计算统计数据
        uptime = wall_time() - self.start_time
        uptime_str = str(timedelta(seconds=int(uptime)))
        
        total_cycle = self.controller.stats.total_cycles
        total_up = self.controller.stats.total_uploaded
        
        # 估算当前总速度
        total_speed = 0
        for s in self.controller.states.values():
            if hasattr(s, 'limit_controller'):
                total_speed += getattr(s.limit_controller.kalman, 'x', 0)
        
        msg = f"""📊 <b>运行统计报告</b>
━━━━━━━━━━━━━━━━━━━━━
⏱️ <b>运行时间</b>: {uptime_str}
📦 <b>累计上传</b>: {fmt_size(total_up)}
🔄 <b>累计周期</b>: {total_cycle} 次

🚀 <b>实时数据</b>
├ 当前监控: {len(self.controller.states)} 个
└ 估算总速: {fmt_speed(total_speed)}

⚙️ <b>配置信息</b>
├ 目标速度: {fmt_speed(self.controller.config.target_bytes)}
├ DL限速: {'✅' if self.controller.config.enable_dl_limit else '❌'}
└ U2助手: {'✅' if self.controller.u2_helper else '❌'}"""
        self.send_immediate(msg)

    def _cmd_pause(self, args: str):
        self.paused = True
        self.send_immediate("⏸️ <b>限速功能已暂停</b>\n所有种子将尝试全速上传")
        # 可以在 controller 中处理暂停逻辑(例如解除限速)

    def _cmd_resume(self, args: str):
        self.paused = False
        self.send_immediate("▶️ <b>限速功能已恢复</b>")

    def _cmd_limit(self, args: str):
        if not args:
            current = self.temp_target_kib or self.controller.config.target_speed_kib
            self.send_immediate(f"🎯 当前目标: <code>{fmt_speed(current * 1024)}</code>")
            return
        new_limit = parse_speed_str(args)
        if not new_limit or new_limit <= 0:
            self.send_immediate("❌ 无效速度值")
            return
        self.temp_target_kib = new_limit
        self.send_immediate(f"🎯 目标速度已修改为: <code>{fmt_speed(new_limit * 1024)}</code>\n(重启后失效)")

    def _cmd_log(self, args: str):
        logs = log_buffer.get_recent(10)
        if not logs:
            self.send_immediate("📜 暂无日志")
            return
        msg = "📜 <b>最新日志</b>\n" + "\n".join(f"<code>{escape_html(l)}</code>" for l in logs)
        self.send_immediate(msg)

    def _cmd_config(self, args: str):
        self.send_immediate("⚠️ 请使用 WebUI 或 SSH 修改 config.json")

    def _cmd_unknown(self, args):
        self.send_immediate("❓ 未知命令，发送 /help 查看帮助")

    # ===========================
    # 📨 通知发送 (带HTML格式)
    # ===========================

    def startup(self, config, qb_version: str = "", u2_enabled: bool = False):
        if not self.enabled: return
        msg = f"""🚀 <b>qBit Smart Limit 已启动</b>
━━━━━━━━━━━━━━━━━━━━━
📌 <b>版本</b>: v{C.VERSION}
🎯 目标: <code>{fmt_speed(config.target_bytes)}</code>
🤖 qB核心: <code>{qb_version}</code>
🌐 U2助手: {'✅ 已连接' if u2_enabled else '❌ 未启用'}
🕒 时间: {datetime.now().strftime('%H:%M:%S')}"""
        self.send(msg, "startup", 0)

    def monitor_start(self, info: dict):
        if not self.enabled: return
        
        name = escape_html(info.get('name', 'Unknown'))
        tid = info.get('tid')
        promotion = info.get('promotion')
        total_size = info.get('total_size', 0)
        
        # 构建带超链接的标题
        if tid and tid > 0:
            link = f"https://u2.dmhy.org/details.php?id={tid}"
            title_html = f"<a href='{link}'>{name}</a>"
        else:
            title_html = name
            
        # 构建优惠标签
        promo_html = ""
        if promotion and "无" not in str(promotion):
            promo_html = f"\n🎉 <b>优惠</b>: {promotion}"
            
        msg = f"""🎬 <b>开始监控</b>
━━━━━━━━━━━━━━━━━━━━━
📛 {title_html}
📦 <b>大小</b>: {fmt_size(total_size)}{promo_html}
🕒 <b>时间</b>: {datetime.now().strftime('%H:%M:%S')}"""
        self.send(msg, f"start_{info.get('hash')}", 0)

    def check_finish(self, info: dict):
        if not self.enabled: return
        h = info.get('hash', '')
        progress = info.get('progress', 0)
        
        # 防止重复发送
        if progress >= 0.999 and h not in getattr(self, '_finish_notified', set()):
            if not hasattr(self, '_finish_notified'): self._finish_notified = set()
            self._finish_notified.add(h)
            
            name = escape_html(info.get('name', 'Unknown'))
            msg = f"✅ <b>下载完成</b>\n━━━━━━━━━━━━━━━━━━━━━\n📛 {name}\n🎉 任务已完成，开始做种"
            self.send(msg, f"finish_{h}", 0)

    def cycle_report(self, info: dict):
        if not self.enabled: return
        # 仅在关键节点或大流量时发送，防止刷屏
        # 这里设置为每 5 个周期更新一次，或者你可以根据需求调整
        idx = info.get('idx', 0)
        if idx % 10 != 0 and idx != 1: return 

        name = escape_html(info.get('name', 'Unknown')[:20])
        speed = info.get('real_speed', 0)
        uploaded = info.get('uploaded', 0)
        
        msg = f"""📈 <b>周期汇报 #{idx}</b>
📛 {name}
⚡ 均速: <code>{fmt_speed(speed)}</code>
📤 本轮: <code>{fmt_size(uploaded)}</code>"""
        self.send(msg, f"cycle_{info.get('hash', '')}", 60)

    def overspeed_warning(self, name: str, real_speed: float, target: float, tid: int = None):
        msg = f"🚨 <b>超速警告</b>\n📛 {escape_html(name[:20])}\n⚠️ 速度: <code>{fmt_speed(real_speed)}</code> > <code>{fmt_speed(target)}</code>"
        self.send(msg, f"overspeed_{name[:10]}", 120)

    def dl_limit_notify(self, name: str, dl_limit: float, reason: str, tid: int = None):
        msg = f"📥 <b>下载限速触发</b>\n📛 {escape_html(name[:20])}\n🔒 限制: <code>{fmt_speed(dl_limit*1024)}</code>\n📝 原因: {reason}"
        self.send(msg, f"dl_limit_{name[:10]}", 60)

    def reannounce_notify(self, name: str, reason: str, tid: int = None):
        msg = f"🔄 <b>强制汇报</b>\n📛 {escape_html(name[:20])}\n📝 {reason}"
        self.send(msg, f"reannounce_{name[:10]}", 60)
        
    def limit_notify(self, state, speed_limit):
        pass # 频繁调用，不发通知
    
    def shutdown_report(self):
        if not self.enabled: return
        self.send_immediate(f"🛑 <b>脚本已停止</b>\n⏱️ {datetime.now().strftime('%H:%M:%S')}")

    def cookie_invalid_notify(self):
        self.send("⚠️ <b>U2 Cookie 已失效</b>，请更新配置！", "cookie_invalid", 3600)

    def rss_notify(self, count: int, duration: float):
        if not self.enabled: return
        msg = f"""📡 <b>RSS 抓取报告</b>
━━━━━━━━━━━━━━━━━━━━━
🌱 新增种子: <b>{count}</b> 个
⏱️ 耗时: {duration:.2f}s"""
        self.send(msg, "rss_run", 0)

    def autoremove_notify(self, info: dict):
        if not self.enabled: return
        name = escape_html(info.get('name', 'Unknown'))
        reason = escape_html(info.get('reason', 'Unknown'))
        size = fmt_size(info.get('size', 0))
        
        emoji = "🗑️"
        if "极危" in reason or "红色" in reason: emoji = "🚨"
        elif "空间" in reason: emoji = "⚠️"
        
        msg = f"""{emoji} <b>自动删种执行</b>
━━━━━━━━━━━━━━━━━━━━━
📛 <b>{name}</b>
💥 原因: {reason}
📦 释放: <code>{size}</code>"""
        self.send(msg, f"autorm_{name[:10]}", 0)
