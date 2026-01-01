#!/usr/bin/env python3
import sys
import os

# 确保能找到 src 包
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.controller import Controller

def main():
    # 默认配置文件路径列表
    config_paths = [
        "config.json",
        "/etc/qbit-smart-limit/config.json",
        os.path.expanduser("~/.config/qbit-smart-limit/config.json")
    ]
    
    config_path = None
    for p in config_paths:
        if os.path.exists(p):
            config_path = p
            break
    
    # 命令行参数覆盖
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    
    if not config_path or not os.path.exists(config_path):
        print("❌ 找不到配置文件")
        print("请创建 config.json 或指定配置文件路径")
        print(f"用法: {sys.argv[0]} [config.json]")
        sys.exit(1)
    
    controller = Controller(config_path)
    controller.run()

if __name__ == "__main__":
    main()
