#!/usr/bin/env python3
import argparse
import os
import sys
import json
import time
from src.controller import Controller
from src.consts import C

# ===========================
# 🎨 UI 美化与工具函数
# ===========================

class Col:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def clear_scr():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    clear_scr()
    print(f"{Col.CYAN}{Col.BOLD}")
    print(r"""
   ___  ____  _ _      _____                      _
  / _ \| __ )(_) |_   / _  /_ __ ___   __ _ _ __ | |_
 | | | |  _ \| | __|  \// /| '_ ` _ \ / _` | '__|| __|
 | |_| | |_) | | |_    / //\| | | | | | (_| | |  | |_
  \__\_\____/|_|\__|  /____/|_| |_| |_|\__,_|_|   \__|
    """)
    print(f"      {Col.HEADER}🚀 qBit Smart Limit {C.VERSION}{Col.ENDC}")
    print(f"{Col.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Col.ENDC}")

def input_clean(prompt, default=None):
    d_str = f" [{default}]" if default else ""
    val = input(f"{Col.GREEN}?{Col.ENDC} {prompt}{d_str}: ").strip()
    return val if val else default

def input_bool(prompt, default=False):
    d_str = "Y/n" if default else "y/N"
    val = input(f"{Col.GREEN}?{Col.ENDC} {prompt} [{d_str}]: ").strip().lower()
    if not val: return default
    return val in ['y', 'yes', '1', 'true']

def save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"{Col.GREEN}✅ 配置已保存!{Col.ENDC}")
    except Exception as e:
        print(f"{Col.FAIL}❌ 保存失败: {e}{Col.ENDC}")

def ensure_logs():
    for log_file in [C.RSS_LOG, C.AUTORM_LOG]:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            if not os.path.exists(log_file): open(log_file, 'a').close()
            os.chmod(log_file, 0o666)
        except: pass

# ===========================
# 🧙‍♂️ 交互式向导功能
# ===========================

def wizard_add_rss():
    print(f"\n{Col.BOLD}📡 添加 RSS 订阅源{Col.ENDC}")
    print(f"{Col.CYAN}------------------{Col.ENDC}")
    
    feeds = []
    if os.path.exists(C.RSS_RULES):
        try: feeds = json.load(open(C.RSS_RULES))
        except: pass

    # 1. 基础信息
    url = input_clean("RSS 订阅链接 (URL)")
    if not url: return
    
    category = input_clean("保存分类 (Category)", "Racing")
    
    # 2. 高级过滤
    print(f"\n{Col.BOLD}🔍 过滤规则{Col.ENDC}")
    must_contain = input_clean("必须包含的关键词 (留空不限制)")
    max_size = input_clean("最大体积限制 (GB, 0为不限)", "0")
    
    # 3. Cookie 增强
    print(f"\n{Col.BOLD}🍪 站点增强{Col.ENDC}")
    enable_scrape = input_bool("开启免费/优惠检测 (Scrape)?")
    cookie = ""
    if enable_scrape:
        cookie = input_clean("输入网站 Cookie (key=value)")
        
    # 4. 下载策略 (新增功能)
    print(f"\n{Col.BOLD}⚡ 下载策略{Col.ENDC}")
    prio_first_last = input_bool("是否优先下载首尾文件块? (推荐开启)", False)

    new_feed = {
        "url": url,
        "category": category,
        "must_contain": must_contain,
        "max_size_gb": float(max_size),
        "enable_scrape": enable_scrape,
        "cookie": cookie,
        "first_last_piece": prio_first_last  # <--- 新增字段
    }
    
    feeds.append(new_feed)
    save_json(C.RSS_RULES, feeds)
    input(f"\n按 {Col.BOLD}Enter{Col.ENDC} 键返回主菜单...")

def wizard_manage_autoremove():
    print(f"\n{Col.BOLD}🗑️ 自动删种规则管理{Col.ENDC}")
    print(f"{Col.CYAN}---------------------{Col.ENDC}")
    
    rules = []
    if os.path.exists(C.AUTORM_RULES):
        try: rules = json.load(open(C.AUTORM_RULES))
        except: pass
        
    print(f"当前已有 {len(rules)} 条规则。\n")
    print("1. 添加新规则")
    print("2. 清空所有规则")
    print("0. 返回")
    
    choice = input("\n请选择: ")
    
    if choice == '2':
        if input_bool(f"{Col.FAIL}确认清空所有删种规则吗?{Col.ENDC}"):
            save_json(C.AUTORM_RULES, [])
    
    elif choice == '1':
        name = input_clean("规则名称 (如: 删黑车)", "Rule1")
        print(f"\n{Col.WARNING}以下条件满足其一即可删除 (留0或空则不限制){Col.ENDC}")
        
        max_dl = input_clean("下载速度超过此值不删 (KiB/s)", "0")
        max_up = input_clean("上传速度超过此值不删 (KiB/s)", "0")
        min_ratio = input_clean("分享率低于此值才删", "0")
        seed_time = input_clean("做种时间超过此值才删 (秒)", "0")
        
        # 转换单位
        rule = {
            "name": name,
            "max_dl_bps": int(max_dl) * 1024,
            "max_up_bps": int(max_up) * 1024,
            "min_ratio": float(min_ratio),
            "min_seed_time": int(seed_time),
            "remove_files": True
        }
        rules.append(rule)
        save_json(C.AUTORM_RULES, rules)
        input(f"\n按 {Col.BOLD}Enter{Col.ENDC} 键返回...")

def show_menu(config_path):
    while True:
        print_banner()
        print(f"配置文件: {config_path}")
        print(f"{Col.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Col.ENDC}")
        print(f"{Col.BOLD}1.{Col.ENDC} 📡 添加 RSS 订阅 (RSS Wizard)")
        print(f"{Col.BOLD}2.{Col.ENDC} 🗑️ 管理 删种规则 (AutoRemove)")
        print(f"{Col.BOLD}3.{Col.ENDC} ▶️ 启动 主服务 (Start Daemon)")
        print(f"{Col.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Col.ENDC}")
        print(f"{Col.BOLD}0.{Col.ENDC} 退出")
        
        choice = input(f"\n{Col.GREEN}👉 请选择功能 [0-3]: {Col.ENDC}").strip()
        
        if choice == '1': wizard_add_rss()
        elif choice == '2': wizard_manage_autoremove()
        elif choice == '3':
            print(f"\n{Col.GREEN}正在启动服务... (按 Ctrl+C 停止){Col.ENDC}")
            try: Controller(config_path).run()
            except KeyboardInterrupt: pass
        elif choice == '0':
            sys.exit(0)

# ===========================
# 🚀 程序入口
# ===========================

def run_task(task_name, config_path):
    # 后台任务模式 (Systemd 调用)
    controller = Controller(config_path)
    if task_name == 'rss':
        from src.workers import NativeRssWorker
        controller._connect()
        NativeRssWorker(controller).execute()
    elif task_name == 'autoremove':
        from src.workers import AutoRemoveWorker
        controller._connect()
        AutoRemoveWorker(controller).execute(dry_run=False)

def main():
    ensure_logs()
    
    # 解析命令行参数
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", default=os.path.join(os.path.dirname(__file__), "config.json"))
    parser.add_argument("--task", choices=['rss', 'autoremove'], help="执行特定后台任务")
    parser.add_argument("--menu", action="store_true", help="强制显示菜单")
    args = parser.parse_args()

    # 如果有 --task 参数，直接执行后台任务 (Systemd 模式)
    if args.task:
        run_task(args.task, args.config)
        return

    # 否则，或者没有参数时，显示美化面板
    # (如果是在后台 Systemd 运行且没带参数，会自动进入 Controller.run)
    # 为了区分用户手动运行还是 Systemd 运行，简单的判断是看是否连接了 TTY
    if sys.stdout.isatty() or args.menu:
        try:
            show_menu(args.config)
        except KeyboardInterrupt:
            print("\n再见 👋")
    else:
        # 非交互模式 (服务模式)
        try: Controller(args.config).run()
        except KeyboardInterrupt: pass

if __name__ == "__main__":
    main()
