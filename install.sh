#!/bin/bash

# =================配置区域=================
REPO_URL="https://github.com/1336665/qbit_smart_limit.git"
INSTALL_DIR="/opt/qbit-smart-limit"
SERVICE_NAME="qbit-smart-limit"
# =========================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

# 检查是否为 Root 用户
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}请使用 sudo 或 root 权限运行此脚本${NC}"
  exit 1
fi

echo -e "${GREEN}🚀 开始安装 qBit Smart Limit...${NC}"

# 1. 检查并安装基础依赖
echo -e "${YELLOW}🔍 检查系统依赖...${NC}"
if [ -x "$(command -v apt-get)" ]; then
    apt-get update
    apt-get install -y git python3 python3-venv python3-pip
elif [ -x "$(command -v yum)" ]; then
    yum install -y git python3 python3-pip
else
    echo -e "${RED}无法检测到包管理器，请手动安装 git 和 python3-venv${NC}"
fi

# 2. 拉取代码
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}📂 检测到目录已存在，正在更新代码...${NC}"
    cd "$INSTALL_DIR"
    git fetch --all
    git reset --hard origin/main
    git pull
else
    echo -e "${YELLOW}📂 克隆仓库到 $INSTALL_DIR ...${NC}"
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 3. 创建 Python 虚拟环境
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}🐍 创建 Python 虚拟环境...${NC}"
    python3 -m venv venv
fi

# 4. 安装依赖
echo -e "${YELLOW}📦 安装/更新 Python 依赖...${NC}"
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 5. 处理配置文件
CONFIG_PATH="$INSTALL_DIR/config.json"
if [ ! -f "$CONFIG_PATH" ]; then
    echo -e "${YELLOW}⚙️ 生成默认配置文件...${NC}"
    cp config.template.json config.json
    echo -e "${GREEN}✅ 配置文件已生成: $CONFIG_PATH${NC}"
    echo -e "${RED}⚠️ 请务必编辑配置文件填入你的账号密码！${NC}"
else
    echo -e "${GREEN}✅ 配置文件已存在，跳过覆盖${NC}"
fi

# 6. 配置 Systemd 服务 (开机自启)
echo -e "${YELLOW}🔧 配置 Systemd 服务...${NC}"
cat > /etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=qBit Smart Limit Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 main.py $CONFIG_PATH
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable $SERVICE_NAME

echo -e "------------------------------------------------"
echo -e "${GREEN}🎉 安装完成！${NC}"
echo -e "------------------------------------------------"
echo -e "1. 编辑配置: ${YELLOW}nano $CONFIG_PATH${NC}"
echo -e "2. 启动服务: ${YELLOW}systemctl start $SERVICE_NAME${NC}"
echo -e "3. 查看日志: ${YELLOW}tail -f /var/log/qbit-smart-limit.log${NC}"
echo -e "------------------------------------------------"
