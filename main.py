#!/usr/bin/env python3
"""
qBit Smart Limit v11.3.3 PRO - Controller Entry
"""
import argparse
import os
import sys
import logging
from src.controller import Controller
from src.consts import C

def ensure_logs():
    """确保日志文件存在，防止面板 tail 报错"""
    for log_file in [C.FLEXGET_LOG, C.AUTORM_LOG]:
        try:
            if not os.path.exists(log_file):
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                with open(log_file, 'a') as f:
                    f.write("")
                os.chmod(log_file, 0o644)
        except: pass

def run_task(task_name, config_path):
    """运行单次任务"""
    print(f"🚀 正在执行任务: {task_name} ...")
    
    # 初始化控制器 (加载配置，但不启动监控循环)
    controller = Controller(config_path)
    
    if task_name == 'flexget':
        from src.workers import FlexGetWorker
        worker = FlexGetWorker(controller)
        worker.execute()
        
    elif task_name == 'autoremove':
        from src.workers import AutoRemoveWorker
        worker = AutoRemoveWorker(controller)
        # AutoRemove 需要连接 QB
        print("🔌 连接 qBittorrent...")
        controller._connect()
        worker.execute(dry_run=False)
        
    elif task_name == 'autoremove_preview':
        from src.workers import AutoRemoveWorker
        worker = AutoRemoveWorker(controller)
        print("🔌 连接 qBittorrent...")
        controller._connect()
        worker.execute(dry_run=True)

    print(f"✅ {task_name} 任务执行完毕")

def main():
    # 1. 确保日志文件存在 (最优先)
    ensure_logs()

    # 2. 参数解析
    parser = argparse.ArgumentParser(description="qBit Smart Limit Controller")
    parser.add_argument("-c", "--config", default=os.path.join(os.path.dirname(__file__), "config.json"), help="Config file path")
    parser.add_argument("--task", choices=['flexget', 'autoremove', 'autoremove_preview'], help="Run a specific task once and exit")
    args = parser.parse_args()

    # 3. 运行模式分支
    if args.task:
        # 命令行单次模式
        try:
            run_task(args.task, args.config)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"❌ 任务出错: {e}")
    else:
        # 守护进程模式
        controller = Controller(args.config)
        controller.run()

if __name__ == "__main__":
    main()
