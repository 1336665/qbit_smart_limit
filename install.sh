#!/bin/bash
#
# qBit Smart Limit Installer
# GitHub: https://github.com/YOUR_USERNAME/YOUR_REPO
#

# =========================================================
# ⚠️ [发布前修改] 请将此处修改为你 GitHub 仓库的 RAW 地址
GITHUB_RAW="https://raw.githubusercontent.com/1336665/qbit_smart_limit/main"
# =========================================================

# 环境变量设置
export PATH=$PATH:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin:$HOME/.local/bin

# 路径常量
INSTALL_DIR="/opt/qbit-smart-limit"
CONFIG_FILE="${INSTALL_DIR}/config.json"
SERVICE_FILE="/etc/systemd/system/qbit-smart-limit.service"
SCRIPT_PATH="/usr/local/bin/qsl"
MAIN_PY="${INSTALL_DIR}/main.py"

# 模块数据路径
RSS_DIR="${INSTALL_DIR}/rss_data"
RSS_RULES="${RSS_DIR}/feeds.json"
RSS_LOG="/var/log/qsl-rss.log"
AUTORM_DIR="${INSTALL_DIR}/autoremove"
AUTORM_RULES="${AUTORM_DIR}/rules.json"
AUTORM_LOG="/var/log/qsl-autoremove.log"

# UI 颜色
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; W='\033[1;37m'; D='\033[0;90m'; N='\033[0m'

# ────────────────────────────────────────────────────────────
# 基础工具函数
# ────────────────────────────────────────────────────────────

# 只有在非交互模式(curl | bash)下才执行自下载
if [[ ! -t 0 ]]; then
    echo -e "\n  ${C}🚀 正在拉取安装脚本...${N}"
    if command -v curl >/dev/null; then 
        curl -sL "${GITHUB_RAW}/install.sh" -o "$SCRIPT_PATH"
    else 
        wget -qO "$SCRIPT_PATH" "${GITHUB_RAW}/install.sh"
    fi
    chmod +x "$SCRIPT_PATH"
    echo -e "  ${G}✓${N} 脚本就绪，正在启动管理界面..."; echo ""
    exec "$SCRIPT_PATH"
    exit 0
fi

ok()   { echo -e "  ${G}✓${N} $1"; }
err()  { echo -e "  ${R}✗${N} $1"; }
warn() { echo -e "  ${Y}!${N} $1"; }
info() { echo -e "  ${C}i${N} $1"; }

# 确保环境目录存在
ensure_env() {
    mkdir -p "$RSS_DIR" "$AUTORM_DIR" "${INSTALL_DIR}/src" "/var/log" >/dev/null 2>&1
    
    # 初始化空的规则文件，如果不存在
    if [[ ! -f "$RSS_RULES" ]]; then echo '[]' > "$RSS_RULES"; fi
    if [[ ! -f "$AUTORM_RULES" ]]; then echo '[]' > "$AUTORM_RULES"; fi
    
    # 创建日志文件并赋予权限
    touch "$RSS_LOG" "$AUTORM_LOG"
    chmod 666 "$RSS_LOG" "$AUTORM_LOG" 2>/dev/null || true
}

# JSON 配置文件读写工具
get_bool() { jq -r ".$1 // false" "$CONFIG_FILE" 2>/dev/null; }
set_kv() {
    local k="$1" v="$2"; tmp=$(mktemp)
    if [[ "$v" == "true" || "$v" == "false" ]]; then 
        jq ".$k = $v" "$CONFIG_FILE" > "$tmp"
    elif [[ "$v" =~ ^[0-9]+$ ]]; then 
        jq ".$k = $v" "$CONFIG_FILE" > "$tmp"
    else 
        jq --arg val "$v" ".$k = \$val" "$CONFIG_FILE" > "$tmp"
    fi
    mv "$tmp" "$CONFIG_FILE" && chmod 600 "$CONFIG_FILE"
}

# 版本检测
get_remote_ver() { curl -sL --connect-timeout 5 "${GITHUB_RAW}/src/consts.py" 2>/dev/null | grep -oP 'VERSION = "\K[^"]+' | head -1; }
get_local_ver() { [[ -f "${INSTALL_DIR}/src/consts.py" ]] && grep -oP 'VERSION = "\K[^"]+' "${INSTALL_DIR}/src/consts.py" 2>/dev/null | head -1 || echo "-"; }

# 下载器
download() {
    local url="$1" dest="$2" name="$3" tmp="/tmp/qsl_dl_$$.tmp"
    echo -ne "  ${C}↓${N} 下载 ${name}..."
    local http_code
    if command -v curl >/dev/null; then 
        http_code=$(curl -sL --connect-timeout 15 -w "%{http_code}" "$url" -o "$tmp" 2>/dev/null)
    else 
        wget -qO "$tmp" "$url" && http_code="200" || http_code="000"
    fi
    
    if [[ "$http_code" == "200" && -s "$tmp" ]]; then 
        mv "$tmp" "$dest"
        [[ "$dest" == *.sh || "$dest" == *.py ]] && chmod +x "$dest"
        echo -e "\r  ${G}✓${N} 下载 ${name}              "
        return 0
    fi
    rm -f "$tmp" 2>/dev/null
    echo -e "\r  ${R}✗${N} 下载 ${name} (HTTP $http_code)   "
    return 1
}

# ────────────────────────────────────────────────────────────
# 界面与菜单
# ────────────────────────────────────────────────────────────
show_banner() {
    clear
    echo ""
    echo -e "${C}  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${N}"
    echo -e "${C}  ┃${N}         ${Y}qBit Smart Limit Control Panel${N}               ${C}┃${N}"
    echo -e "${C}  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${N}"
    echo ""
}

show_status() {
    if systemctl is-active --quiet qbit-smart-limit; then serv_st="${G}● 运行中${N}"; else serv_st="${R}○ 已停止${N}"; fi
    
    if [[ -f "$CONFIG_FILE" ]]; then
        # 注意：底层变量仍沿用 flexget_enabled 以兼容旧代码，但显示为 Native RSS
        [[ $(get_bool "flexget_enabled") == "true" ]] && rss_st="${G}● 启用${N}" || rss_st="${R}○ 禁用${N}"
        [[ $(get_bool "autoremove_enabled") == "true" ]] && ar_st="${G}● 启用${N}" || ar_st="${R}○ 禁用${N}"
    else 
        rss_st="${D}?${N}"; ar_st="${D}?${N}"
    fi
    
    echo -e "  ${D}┌────────────────────────────────────────────────────────────────┐${N}"
    echo -e "  ${D}│${N}  ${W}服务状态${N}  $serv_st        ${W}Native RSS${N}  $rss_st              ${D}│${N}"
    echo -e "  ${D}│${N}  ${W}AutoRm${N}    $ar_st        ${W}配置路径${N}    ${G}config.json${N}          ${D}│${N}"
    echo -e "  ${D}└────────────────────────────────────────────────────────────────┘${N}"; echo ""
}

show_menu() {
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━━ 主菜单 ━━━━━━━━━━━━━━━━━━━━${N}"
    echo -e "     ${G}1${N}. 全新安装              ${G}2${N}. 修改主配置"
    echo -e "     ${G}3${N}. 启动/重启服务         ${G}4${N}. 停止服务"
    echo -e "     ${G}5${N}. 查看日志              ${G}6${N}. 检查更新"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━ 自动化模块 ━━━━━━━━━━━━━━━━━━${N}"
    echo -e "     ${Y}10${N}. 原生 RSS 订阅管理      ${Y}11${N}. AutoRemove 自动删种"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━ 其他 ━━━━━━━━━━━━━━━━━━━━━━${N}"
    echo -e "     ${R}99${N}. 卸载程序             ${D}0${N}. 退出"; echo ""
}

# ────────────────────────────────────────────────────────────
# Native RSS 管理
# ────────────────────────────────────────────────────────────
rss_list() {
    echo ""; echo -e "  ${W}当前订阅列表:${N}"
    if [[ ! -s "$RSS_RULES" || "$(cat "$RSS_RULES")" == "[]" ]]; then
        echo -e "  ${D}(暂无订阅)${N}"
    else
        jq -r 'to_entries[] | "  \(.key+1). \(.value.category) | <\(.value.max_size_gb)G | Scrape:\(.value.enable_scrape) | \(.value.url | split("?")[0])..."' "$RSS_RULES"
    fi
    echo ""
}

rss_add() {
    echo ""; echo -e "  ${C}>>> 添加 RSS 订阅 <<<${N}"
    read -rp "  1. RSS 链接: " url
    [[ -z "$url" ]] && return
    
    read -rp "  2. 种子分类 (默认 Racing): " cat; cat=${cat:-Racing}
    read -rp "  3. 最大体积 (GB) [30]: " size; size=${size:-30}
    read -rp "  4. 开启免费检测(需Cookie)? [y/N]: " scrape
    
    local enable_scrape="false"
    local cookie=""
    
    if [[ "$scrape" =~ ^[Yy] ]]; then
        enable_scrape="true"
        echo -e "  ${Y}请输入站点 Cookie (格式: nexusphp_u2=...):${N}"
        read -rp "  > " cookie
    fi
    
    tmp=$(mktemp)
    jq --arg url "$url" --arg cat "$cat" --arg size "$size" --arg scrape "$enable_scrape" --arg cookie "$cookie" \
       '. += [{"url":$url, "category":$cat, "max_size_gb":($size|tonumber), "enable_scrape":($scrape=="true"), "cookie":$cookie}]' \
       "$RSS_RULES" > "$tmp" && mv "$tmp" "$RSS_RULES"
       
    ok "订阅已添加"
}

rss_del() {
    rss_list
    read -rp "  请输入要删除的序号: " n
    if [[ "$n" =~ ^[0-9]+$ ]]; then
        tmp=$(mktemp)
        jq "del(.[$((n-1))])" "$RSS_RULES" > "$tmp" && mv "$tmp" "$RSS_RULES"
        ok "订阅已删除"
    else
        err "无效序号"
    fi
}

rss_edit_manual() {
    echo ""; info "正在打开编辑器，请直接修改 JSON 文件..."
    read -rp "按回车继续..."
    if command -v nano >/dev/null; then nano "$RSS_RULES"; else vi "$RSS_RULES"; fi
    ok "文件已保存，请重启服务生效"
}

rss_menu() {
    ensure_env
    while true; do
        show_banner; show_status
        echo -e "  ${C}━━━━━━━━━━━━━━━ 原生 RSS 菜单 ━━━━━━━━━━━━━━━${N}"
        echo -e "     ${G}1${N}. 添加订阅 (向导)       ${G}2${N}. 删除订阅"
        echo -e "     ${G}3${N}. 查看订阅列表          ${G}4${N}. 手动编辑配置文件"
        echo -e "     ${G}5${N}. 开关 RSS 模块         ${G}6${N}. 修改抓取间隔"
        echo -e "     ${G}7${N}. 查看 RSS 日志         ${D}0${N}. 返回"
        echo ""; read -rp "  选择: " c
        case "$c" in
            1) rss_add ;;
            2) rss_del ;;
            3) rss_list; read -rp "..." ;;
            4) rss_edit_manual ;;
            5) cur=$(get_bool "flexget_enabled"); [[ "$cur" == "true" ]] && set_kv "flexget_enabled" "false" || set_kv "flexget_enabled" "true"; systemctl restart qbit-smart-limit; ok "状态已切换"; sleep 1 ;;
            6) read -rp "  新间隔(秒): " v; [[ "$v" =~ ^[0-9]+$ ]] && set_kv "flexget_interval_sec" "$v" && systemctl restart qbit-smart-limit && ok "已更新" ;;
            7) tail -n 20 "$RSS_LOG"; read -rp "..." ;;
            0) return ;;
        esac
    done
}

# ────────────────────────────────────────────────────────────
# AutoRemove 逻辑
# ────────────────────────────────────────────────────────────
autorm_menu() {
    ensure_env
    while true; do
        show_banner; show_status
        echo -e "  ${C}━━━━━━━━━━━━━━━ AutoRemove 菜单 ━━━━━━━━━━━━━━${N}"
        echo -e "     ${G}1${N}. 开关模块              ${G}2${N}. 修改检查间隔"
        echo -e "     ${G}3${N}. 查看当前策略          ${G}4${N}. 手动编辑策略"
        echo -e "     ${G}5${N}. 查看删种日志          ${D}0${N}. 返回"
        echo ""; read -rp "  选择: " c
        case "$c" in
            1) cur=$(get_bool "autoremove_enabled"); [[ "$cur" == "true" ]] && set_kv "autoremove_enabled" "false" || set_kv "autoremove_enabled" "true"; systemctl restart qbit-smart-limit; ok "状态已切换"; sleep 1 ;;
            2) read -rp "  新间隔(秒): " v; [[ "$v" =~ ^[0-9]+$ ]] && set_kv "autoremove_interval_sec" "$v" && systemctl restart qbit-smart-limit && ok "已更新" ;;
            3) jq -r 'to_entries[]|"\(.key+1). \(.value.name)"' "$AUTORM_RULES"; read -rp "..." ;;
            4) if command -v nano >/dev/null; then nano "$AUTORM_RULES"; else vi "$AUTORM_RULES"; fi; systemctl restart qbit-smart-limit && ok "已保存并重启" ;;
            5) tail -n 20 "$AUTORM_LOG"; read -rp "..." ;;
            0) return ;;
        esac
    done
}

# ────────────────────────────────────────────────────────────
# 安装与更新
# ────────────────────────────────────────────────────────────
install_deps() {
    echo ""; info "正在安装系统依赖..."
    if command -v apt-get &>/dev/null; then 
        apt-get update -qq &>/dev/null || true
        apt-get install -y python3 python3-pip jq curl &>/dev/null || true
    elif command -v yum &>/dev/null; then
        yum install -y python3 python3-pip jq curl -q &>/dev/null || true
    fi
    ok "系统依赖安装完成"
    
    info "正在安装 Python 依赖 (轻量版)..."
    # 彻底移除 flexget，只安装核心库
    pip3 install --break-system-packages -q qbittorrent-api requests beautifulsoup4 lxml 2>/dev/null || pip3 install -q qbittorrent-api requests beautifulsoup4 lxml
    ok "Python 依赖安装完成"
}

install_source_files() {
    mkdir -p "${INSTALL_DIR}/src"
    local base="${GITHUB_RAW}/src"
    local files=("__init__.py" "consts.py" "utils.py" "config.py" "database.py" "model.py" "algorithms.py" "logic.py" "helper_web.py" "helper_bot.py" "workers.py" "controller.py")
    
    for f in "${files[@]}"; do 
        download "${base}/${f}" "${INSTALL_DIR}/src/${f}" "src/${f}"
    done
}

do_install() {
    show_banner
    echo -e "  ${W}>>> 安装 qBit Smart Limit PRO <<<${N}"; echo ""
    install_deps
    mkdir -p "$INSTALL_DIR"
    
    download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py"
    install_source_files
    
    echo ""; echo -e "  ${C}>>> 配置 qBittorrent <<<${N}"
    read -rp "  WebUI 地址 [http://127.0.0.1:8080]: " h; h=${h:-"http://127.0.0.1:8080"}
    read -rp "  用户名 [admin]: " u; u=${u:-"admin"}
    read -rsp "  密码: " p; echo ""
    
    # 写入初始配置 (包含默认 RSS 间隔和 AutoRemove 间隔)
    cat > "$CONFIG_FILE" <<EOF
{
  "host": "$h", "username": "$u", "password": "$(json_escape "$p")",
  "target_speed_kib": 51200, "safety_margin": 0.98, "log_level": "INFO",
  "telegram_bot_token": "", "telegram_chat_id": "", "u2_cookie": "",
  "flexget_enabled": false, "flexget_interval_sec": 120,
  "autoremove_enabled": false, "autoremove_interval_sec": 60
}
EOF
    chmod 600 "$CONFIG_FILE"

    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=qBit Smart Limit
After=network.target
[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $MAIN_PY
Restart=always
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now qbit-smart-limit
    
    # 再次下载自己，以便用户直接输入 qsl
    download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "管理脚本"
    chmod +x "$SCRIPT_PATH"
    
    echo ""; echo -e "  ${G}安装完成! 请运行 qsl 命令打开管理面板${N}"
}

do_update() {
    echo ""; echo -e "  ${W}>>> 检查更新 <<<${N}"
    local rv; rv=$(get_remote_ver)
    if [[ -z "$rv" ]]; then err "获取远程版本失败"; return; fi
    echo -e "  远程版本: ${C}$rv${N}"; echo -e "  本地版本: ${W}$(get_local_ver)${N}"
    
    read -rp "  确认更新? [y/N]: " c
    if [[ "$c" =~ ^[Yy] ]]; then
        download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py"
        install_source_files
        download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "管理脚本"
        chmod +x "$SCRIPT_PATH"
        systemctl restart qbit-smart-limit && ok "更新完成" || err "服务启动失败"
    fi
}

do_uninstall() {
    echo ""; read -rp "  确认卸载? [y/N]: " confirm
    [[ ! "$confirm" =~ ^[Yy] ]] && return
    systemctl disable --now qbit-smart-limit 2>/dev/null
    rm -f "$SERVICE_FILE" "$SCRIPT_PATH"
    systemctl daemon-reload
    read -rp "  删除数据文件(配置文件/日志)? [y/N]: " d
    [[ "$d" =~ ^[Yy] ]] && rm -rf "$INSTALL_DIR"
    ok "卸载完成"
}

# ────────────────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────────────────
main() {
    if [[ $EUID -ne 0 ]]; then echo -e "${R}请使用 root 运行${N}"; exit 1; fi
    ensure_env
    
    while true; do
        show_banner; show_status; show_menu
        read -rp "  请选择: " choice
        case "$choice" in
            1) do_install ;;
            2) if command -v nano >/dev/null; then nano "$CONFIG_FILE"; else vi "$CONFIG_FILE"; fi; systemctl restart qbit-smart-limit && ok "重启生效" ;;
            3) systemctl restart qbit-smart-limit && ok "已重启" ;;
            4) systemctl stop qbit-smart-limit && warn "已停止" ;;
            5) journalctl -u qbit-smart-limit -f ;;
            6) do_update ;;
            10) rss_menu ;;
            11) autorm_menu ;;
            99) do_uninstall ;;
            0) exit 0 ;;
            *) echo "无效选择" ;;
        esac
        echo ""; read -rp "  按回车继续..."
    done
}

main "$@"
