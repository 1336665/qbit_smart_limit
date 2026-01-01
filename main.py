#!/usr/bin/env python3
import argparse
import os
import sys
from src.controller import Controller
from src.consts import C

def ensure_logs():
    for log_file in [C.RSS_LOG, C.AUTORM_LOG]:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            if not os.path.exists(log_file): open(log_file, 'a').close()
            os.chmod(log_file, 0o666)
        except: pass

def run_task(task_name, config_path):
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
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", default=os.path.join(os.path.dirname(__file__), "config.json"))
    parser.add_argument("--task", choices=['rss', 'autoremove'])
    args = parser.parse_args()

    if args.task:
        run_task(args.task, args.config)
    else:
        try: Controller(args.config).run()
        except KeyboardInterrupt: pass

if __name__ == "__main__":
    main()
