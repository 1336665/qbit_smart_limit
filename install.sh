#!/bin/bash
#
# qBit Smart Limit 管理脚本 v11.1.0 PRO
# 集成管理面板：核心服务 + FlexGet + AutoRemove
#

# =========================================================
# ⚠️ 请修改此处为你的 GitHub 仓库地址
GITHUB_RAW="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main"
# =========================================================

INSTALL_DIR="/opt/qbit-smart-limit"
CONFIG_FILE="${INSTALL_DIR}/config.json"
SERVICE_FILE="/etc/systemd/system/qbit-smart-limit.service"

# 子模块配置路径
FLEXGET_DIR="${INSTALL_DIR}/flexget"
AUTORM_DIR="${INSTALL_DIR}/autoremove"
FLEXGET_YML="${FLEXGET_DIR}/config.yml"
AUTORM_RULES="${AUTORM_DIR}/rules.json"

# 颜色
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; C='\033[0;36m'; N='\033[0m'

# 帮助函数
ok() { echo -e "  ${G}✓${N} $1"; }
warn() { echo -e "  ${Y}!${N} $1"; }
get_bool() { jq -r ".$1" "$CONFIG_FILE" 2>/dev/null; }
set_bool() {
    local k="$1" v="$2"
    tmp=$(mktemp)
    if [[ "$v" == "true" ]]; then jq ".$k = true" "$CONFIG_FILE" > "$tmp"; else jq ".$k = false" "$CONFIG_FILE" > "$tmp"; fi
    mv "$tmp" "$CONFIG_FILE" && chmod 600 "$CONFIG_FILE"
}

# 依赖检查与目录初始化
init_env() {
    mkdir -p "$FLEXGET_DIR" "$AUTORM_DIR"
    
    # 确保 flexget 配置文件存在
    if [[ ! -f "$FLEXGET_YML" ]]; then
        echo "tasks: {}" > "$FLEXGET_YML"
    fi
    
    # 确保 autoremove 规则存在
    if [[ ! -f "$AUTORM_RULES" ]]; then
        echo '[{"name":"Default Rule","min_free_gb":10,"max_up_bps":102400,"min_low_sec":60}]' > "$AUTORM_RULES"
    fi
}

# 状态显示
show_status() {
    clear
    echo ""
    echo -e "${C}  qBit Smart Limit v11.1.0 PRO 管理面板${N}"
    echo -e "${C}  ─────────────────────────────────────${N}"
    
    # 主服务状态
    if systemctl is-active --quiet qbit-smart-limit; then
        echo -e "  核心服务: ${G}● 运行中${N}"
    else
        echo -e "  核心服务: ${R}○ 已停止${N}"
    fi
    
    # 功能开关状态 (读取 config.json)
    if [[ -f "$CONFIG_FILE" ]]; then
        fg_st=$(get_bool "flexget_enabled")
        ar_st=$(get_bool "autoremove_enabled")
        
        [[ "$fg_st" == "true" ]] && fg_txt="${G}已启用${N}" || fg_txt="${R}已停用${N}"
        [[ "$ar_st" == "true" ]] && ar_txt="${G}已启用${N}" || ar_txt="${R}已停用${N}"
        
        echo -e "  FlexGet : $fg_txt"
        echo -e "  自动删种: $ar_txt"
    else
        echo -e "  ${R}配置文件丢失!${N}"
    fi
    echo ""
}

# 菜单
show_menu() {
    echo -e "  1. 启动/重启服务"
    echo -e "  2. 停止服务"
    echo -e "  3. 查看实时日志"
    echo -e "  4. 修改主配置 (config.json)"
    echo ""
    echo -e "  ${Y}--- FlexGet 管理 ---${N}"
    echo -e "  10. 开关 FlexGet 模块"
    echo -e "  11. 编辑 FlexGet 配置 (config.yml)"
    echo -e "  12. 手动测试运行 FlexGet (需停止服务)"
    echo ""
    echo -e "  ${Y}--- AutoRemove 管理 ---${N}"
    echo -e "  20. 开关 自动删种 模块"
    echo -e "  21. 编辑 删种规则 (rules.json)"
    echo ""
    echo -e "  0. 退出"
    echo ""
}

# 主逻辑
init_env
while true; do
    show_status
    show_menu
    read -rp "  请选择: " choice
    case "$choice" in
        1) systemctl restart qbit-smart-limit && ok "服务已重启" ;;
        2) systemctl stop qbit-smart-limit && warn "服务已停止" ;;
        3) journalctl -u qbit-smart-limit -f ;;
        4) nano "$CONFIG_FILE" && systemctl restart qbit-smart-limit ;;
        
        10) 
            cur=$(get_bool "flexget_enabled")
            if [[ "$cur" == "true" ]]; then
                set_bool "flexget_enabled" "false" && warn "FlexGet 已关闭 (重启生效)"
            else
                set_bool "flexget_enabled" "true" && ok "FlexGet 已开启 (重启生效)"
            fi
            sleep 1
            ;;
        11) nano "$FLEXGET_YML" ;;
        12) 
            echo "正在运行 FlexGet 测试..."
            flexget -c "$FLEXGET_YML" execute
            read -rp "按回车继续..." 
            ;;
            
        20)
            cur=$(get_bool "autoremove_enabled")
            if [[ "$cur" == "true" ]]; then
                set_bool "autoremove_enabled" "false" && warn "自动删种 已关闭 (重启生效)"
            else
                set_bool "autoremove_enabled" "true" && ok "自动删种 已开启 (重启生效)"
            fi
            sleep 1
            ;;
        21) nano "$AUTORM_RULES" ;;
        
        0) exit 0 ;;
        *) echo "无效选择" ;;
    esac
done
