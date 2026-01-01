#!/usr/bin/env python3
"""
qBit Smart Limit PRO - Main Entry
GitHub: https://github.com/YOUR_USERNAME/YOUR_REPO
"""
import argparse
import os
import sys
import logging
from src.controller import Controller
from src.consts import C

def ensure_logs():
    """
    确保日志文件存在且有写入权限
    Fix: 适配 Native RSS 和 AutoRemove 的日志路径
    """
    # 这里对应 consts.py 里的定义
    log_files = [C.RSS_LOG, C.AUTORM_LOG]
    
    for log_file in log_files:
        try:
            # 如果目录不存在则创建
            log_dir = os.path.dirname(log_file)
            if not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            
            # 如果文件不存在则创建空文件
            if not os.path.exists(log_file):
                with open(log_file, 'a') as f:
                    f.write("")
            
            # 尝试放宽权限，防止不同用户运行时的权限问题
            os.chmod(log_file, 0o666)
        except Exception as e:
            # 即使权限修改失败也不阻断主程序启动
            print(f"Warning: Failed to init log {log_file}: {e}")

def run_task(task_name, config_path):
    """
    命令行单次任务模式 (CLI Mode)
    用于手动测试或脚本调用，不启动守护进程
    """
    print(f"🚀 Executing task: {task_name} ...")
    
    # 初始化控制器 (加载配置)
    controller = Controller(config_path)
    
    if task_name == 'rss':
        # 调用原生 RSS 模块
        from src.workers import NativeRssWorker
        print("📡 Running Native RSS Worker...")
        # 必须先连接 qB，因为 RSS 需要添加种子
        controller._connect()
        if controller.client:
            worker = NativeRssWorker(controller)
            worker.execute()
        else:
            print("❌ qBittorrent connection failed.")
        
    elif task_name == 'autoremove':
        from src.workers import AutoRemoveWorker
        worker = AutoRemoveWorker(controller)
        print("🔌 Connecting to qBittorrent...")
        controller._connect()
        if controller.client:
            worker.execute(dry_run=False)
        else:
            print("❌ qBittorrent connection failed.")
        
    elif task_name == 'autoremove_preview':
        from src.workers import AutoRemoveWorker
        worker = AutoRemoveWorker(controller)
        print("🔌 Connecting to qBittorrent (Preview Mode)...")
        controller._connect()
        if controller.client:
            worker.execute(dry_run=True)
        else:
            print("❌ qBittorrent connection failed.")

    print(f"✅ Task {task_name} completed.")

def main():
    # 1. 环境初始化
    ensure_logs()

    # 2. 参数解析
    parser = argparse.ArgumentParser(description="qBit Smart Limit Controller")
    parser.add_argument("-c", "--config", default=os.path.join(os.path.dirname(__file__), "config.json"), help="Config file path")
    # 更新 task 选项，移除 flexget，新增 rss
    parser.add_argument("--task", choices=['rss', 'autoremove', 'autoremove_preview'], help="Run a specific task once and exit")
    args = parser.parse_args()

    # 3. 模式选择
    if args.task:
        # CLI 模式 (跑完即停)
        try:
            run_task(args.task, args.config)
        except KeyboardInterrupt:
            print("\n🛑 Task interrupted.")
        except Exception as e:
            print(f"❌ Task Error: {e}")
            import traceback
            traceback.print_exc()
    else:
        # Daemon 模式 (长期运行)
        try:
            controller = Controller(args.config)
            controller.run()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"❌ Fatal Error: {e}")

if __name__ == "__main__":
    main()
