#!/bin/bash
#
# qBit Smart Limit Manager (Cyberpunk UI Version)
#

# =========================================================
# ⚠️ [发布前修改] 请将此处修改为你 GitHub 仓库的 RAW 地址
GITHUB_RAW="https://raw.githubusercontent.com/1336665/qbit_smart_limit/main"
# =========================================================

# 环境变量
export PATH=$PATH:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin:$HOME/.local/bin

# 路径定义
INSTALL_DIR="/opt/qbit-smart-limit"
CONFIG_FILE="${INSTALL_DIR}/config.json"
SERVICE_FILE="/etc/systemd/system/qbit-smart-limit.service"
SCRIPT_PATH="/usr/local/bin/qsl"
MAIN_PY="${INSTALL_DIR}/main.py"

# 数据路径
RSS_RULES="${INSTALL_DIR}/rss_data/feeds.json"
RSS_LOG="/var/log/qsl-rss.log"
AUTORM_RULES="${INSTALL_DIR}/autoremove/rules.json"
AUTORM_LOG="/var/log/qsl-autoremove.log"

# 🎨 截图同款配色
# B=Blue(线框), Y=Orange(标题), G=Green(状态好), R=Red(状态差/卸载), W=White(文字), GR=Grey(辅助)
B='\033[34m'; C='\033[36m'; Y='\033[33m'; G='\033[32m'; R='\033[31m'; W='\033[37m'; GR='\033[90m'; N='\033[0m'

# ────────────────────────────────────────────────────────────
# 核心工具函数 (保持 Python 逻辑以确保稳定性)
# ────────────────────────────────────────────────────────────

# 自更新逻辑
if [[ ! -t 0 ]]; then
    echo -e "\n  ${C}🚀 正在拉取管理面板...${N}"
    if command -v curl >/dev/null; then curl -sL "${GITHUB_RAW}/install.sh" -o "$SCRIPT_PATH"; else wget -qO "$SCRIPT_PATH" "${GITHUB_RAW}/install.sh"; fi
    chmod +x "$SCRIPT_PATH"
    exec "$SCRIPT_PATH"
    exit 0
fi

ensure_env() {
    mkdir -p "${INSTALL_DIR}/rss_data" "${INSTALL_DIR}/autoremove" "${INSTALL_DIR}/src" "/var/log" >/dev/null 2>&1
    [[ ! -f "$RSS_RULES" ]] && echo '[]' > "$RSS_RULES"
    [[ ! -f "$AUTORM_RULES" ]] && echo '[]' > "$AUTORM_RULES"
    touch "$RSS_LOG" "$AUTORM_LOG"
    chmod 666 "$RSS_LOG" "$AUTORM_LOG" 2>/dev/null || true
}

# Python JSON 辅助 (读取/写入)
get_val() { python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('$1', ''))" 2>/dev/null; }
get_bool() { python3 -c "import json; print(str(json.load(open('$CONFIG_FILE')).get('$1', False)).lower())" 2>/dev/null; }
set_kv() {
    python3 -c "
import json
try:
    with open('$CONFIG_FILE', 'r') as f: d = json.load(f)
except: d = {}
val = '$2'
if val.lower() == 'true': val = True
elif val.lower() == 'false': val = False
elif val.isdigit(): val = int(val)
d['$1'] = val
with open('$CONFIG_FILE', 'w') as f: json.dump(d, f, indent=2)
"
}
json_escape() { echo -n "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()).strip("\""))' 2>/dev/null || echo "$1"; }

get_remote_ver() { curl -sL --connect-timeout 5 "${GITHUB_RAW}/src/consts.py" 2>/dev/null | grep -oP 'VERSION = "\K[^"]+' | head -1; }
get_local_ver() { [[ -f "${INSTALL_DIR}/src/consts.py" ]] && grep -oP 'VERSION = "\K[^"]+' "${INSTALL_DIR}/src/consts.py" 2>/dev/null | head -1 || echo "未知"; }

download() {
    local url="$1" dest="$2" name="$3" tmp="/tmp/qsl_dl_$$.tmp"
    echo -ne "  ${GR}📥 下载 ${name}...${N}"
    local code
    if command -v curl >/dev/null; then code=$(curl -sL -w "%{http_code}" "$url" -o "$tmp" 2>/dev/null); else wget -qO "$tmp" "$url" && code="200" || code="000"; fi
    if [[ "$code" == "200" && -s "$tmp" ]]; then 
        mv "$tmp" "$dest"; [[ "$dest" == *.sh || "$dest" == *.py ]] && chmod +x "$dest"
        echo -e "\r  ${G}✔${N} 下载 ${name} 完成        "
    else
        rm -f "$tmp"; echo -e "\r  ${R}✖${N} 下载 ${name} 失败 ($code)  "
    fi
}

# ────────────────────────────────────────────────────────────
# 🎨 UI 渲染 (1:1 复刻截图)
# ────────────────────────────────────────────────────────────

show_ui() {
    clear
    echo ""
    echo -e "${C}  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${N}"
    echo -e "${C}  ┃${N}  ${G} ██████  ${W}██████  ${C}██${N} ████████   ${G}███████${N} ${W}██${N}          ${C}┃${N}"
    echo -e "${C}  ┃${N}  ${G}██    ██ ${W}██   ██ ${C}██${N}    ██      ${G}██     ${N} ${W}██${N}          ${C}┃${N}"
    echo -e "${C}  ┃${N}  ${G}██    ██ ${W}██████  ${C}██${N}    ██      ${G}███████${N} ${W}██${N}          ${C}┃${N}"
    echo -e "${C}  ┃${N}  ${G}██ ▄▄ ██ ${W}██   ██ ${C}██${N}    ██           ${G}██${N} ${W}██${N}          ${C}┃${N}"
    echo -e "${C}  ┃${N}  ${G} ██████  ${W}██████  ${C}██${N}    ██      ${G}███████${N} ${W}███████${N}     ${C}┃${N}"
    echo -e "${C}  ┃${N}  ${G}    ▀▀${N}                                              ${C}┃${N}"
    echo -e "${C}  ┃${N}              ${Y}PT 上传速度精准控制器${N}                   ${C}┃${N}"
    echo -e "${C}  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${N}"
    echo ""

    # 安装状态
    local inst_st serv_st local_v u2_st dl_st ra_st tg_st fg_st ar_st
    if is_installed; then
        inst_st="${G}● 已安装${N}"
        local_v=$(get_local_ver)
    else
        inst_st="${Y}○ 未安装${N}"
        local_v="-"
    fi

    # 服务状态
    if is_running; then
        serv_st="${G}● 运行中${N}"
    else
        serv_st="${R}○ 已停止${N}"
    fi

    # Telegram 状态（只看配置是否填写）
    tg_st="${D}○ 未配置${N}"
    if [[ -f "$CONFIG_FILE" ]]; then
        local tg_token
        tg_token=$(jq -r '.telegram_bot_token // ""' "$CONFIG_FILE" 2>/dev/null)
        if [[ -n "$tg_token" && "$tg_token" != "null" ]]; then
            tg_st="${G}● 已配置${N}"
        fi
    fi

    # U2 状态
    u2_st="${D}○ 未配置${N}"
    if [[ -f "$CONFIG_FILE" ]]; then
        local u2_cookie
        u2_cookie=$(jq -r '.u2_cookie // ""' "$CONFIG_FILE" 2>/dev/null)
        if [[ -n "$u2_cookie" && "$u2_cookie" != "null" ]]; then
            if python3 -c "from bs4 import BeautifulSoup" &>/dev/null; then
                u2_st="${G}● 已启用${N}"
            else
                u2_st="${Y}● 缺bs4${N}"
            fi
        fi
    fi

    # 下载限速状态
    dl_st="${D}○ 未配置${N}"
    if [[ -f "$CONFIG_FILE" ]]; then
        local dl_enabled
        dl_enabled=$(get_bool "enable_dl_limit" "true")
        if [[ "$dl_enabled" == "true" ]]; then
            dl_st="${G}● 已启用${N}"
        else
            dl_st="${R}○ 未启用${N}"
        fi
    fi

    # 汇报优化状态
    ra_st="${D}○ 未配置${N}"
    if [[ -f "$CONFIG_FILE" ]]; then
        local ra_enabled
        ra_enabled=$(get_bool "enable_reannounce_opt" "true")
        if [[ "$ra_enabled" == "true" ]]; then
            ra_st="${G}● 已启用${N}"
        else
            ra_st="${R}○ 未启用${N}"
        fi
    fi

    # 抓种器（原 自动抓种 入口，对应 config: autograb_enabled）
    fg_st="${D}○ 未配置${N}"
    if [[ -f "$CONFIG_FILE" ]]; then
        local fg_enabled
        fg_enabled=$(get_bool "autograb_enabled" "false")
        if [[ "$fg_enabled" == "true" ]]; then
            fg_st="${G}● 已启用${N}"
        else
            fg_st="${R}○ 未启用${N}"
        fi
    fi

    # AutoRemove（对应 config: autoremove_enabled）
    ar_st="${D}○ 未配置${N}"
    if [[ -f "$CONFIG_FILE" ]]; then
        local ar_enabled
        ar_enabled=$(get_bool "autoremove_enabled" "false")
        if [[ "$ar_enabled" == "true" ]]; then
            ar_st="${G}● 已启用${N}"
        else
            ar_st="${R}○ 未启用${N}"
        fi
    fi

    echo -e "  ${D}┌────────────────────────────────────────────────────────────────┐${N}"
    echo -e "  ${D}│${N}  ${W}安装状态${N}  ${inst_st}        ${W}服务状态${N}  ${serv_st}            ${D}│${N}"
    echo -e "  ${D}│${N}  ${W}程序版本${N}  ${C}${local_v}${N}              ${W}脚本版本${N}  ${D}v${SCRIPT_VER}${N}               ${D}│${N}"
    echo -e "  ${D}├────────────────────────────────────────────────────────────────┤${N}"
    echo -e "  ${D}│${N}  ${W}U2 辅助${N}   ${u2_st}        ${W}Telegram${N}  ${tg_st}               ${D}│${N}"
    echo -e "  ${D}│${N}  ${W}下载限速${N}  ${dl_st}        ${W}汇报优化${N}  ${ra_st}            ${D}│${N}"
    echo -e "  ${D}│${N}  ${W}自动抓种${N}    ${fg_st}      ${W}AutoRemove${N} ${ar_st}        ${D}│${N}"
    echo -e "  ${D}└────────────────────────────────────────────────────────────────┘${N}"
    echo ""

    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━━ 主菜单 ━━━━━━━━━━━━━━━━━━━━${N}"
    echo ""
    echo -e "     ${G}1${N}. 全新安装              ${G}2${N}. 修改配置"
    echo -e "     ${G}3${N}. 查看状态              ${G}4${N}. 查看日志"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━ 服务管理 ━━━━━━━━━━━━━━━━━━━━${N}"
    echo ""
    echo -e "     ${Y}5${N}. 启动服务              ${Y}6${N}. 停止服务"
    echo -e "     ${Y}7${N}. 重启服务"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━ 功能扩展 ━━━━━━━━━━━━━━━━━━━━${N}"
    echo ""
    echo -e "     ${G}10${N}. 抓种器管理 (自动抓种)   ${G}11${N}. AutoRemove 删种管理"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━ 其他 ━━━━━━━━━━━━━━━━━━━━━━${N}"
    echo ""
    echo -e "     ${G}8${N}. 检查更新              ${R}9${N}. 卸载程序"
    echo -e "     ${D}0${N}. 退出"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
    echo ""
}


# ────────────────────────────────────────────────────────────
# 功能实现 (逻辑部分)
# ────────────────────────────────────────────────────────────

rss_render_list() {
    if [[ ! -s "$RSS_RULES" || "$(cat "$RSS_RULES")" == "[]" ]]; then
        echo -e "  ${Y}列表为空。${N}"
        return
    fi
    echo -e "  ${C}ID   分类      体积限制   首尾块     URL${N}"
    echo -e "  ${GR}────────────────────────────────────────────${N}"
    python3 -c "
import json
try:
    d = json.load(open('$RSS_RULES'))
    for i, item in enumerate(d):
        url = item.get('url', '')[:20] + '...'
        cat = item.get('category', 'Racing')
        size = str(item.get('max_size_gb', 0)) + 'G'
        prio = '✅' if item.get('first_last_piece') else '❌'
        print(f'  \033[32m{i+1:<3}\033[0m {cat:<9} {size:<9} {prio:<9} {url}')
except: pass
"
    echo ""
}

rss_add_wizard() {
    echo -e "\n  ${C}📡 新建 RSS 订阅${N}"
    read -rp "  1. RSS 链接: " url; [[ -z "$url" ]] && return
    read -rp "  2. 分类 (默认 Racing): " cat; cat=${cat:-Racing}
    read -rp "  3. 体积限制 (GB, 默认30): " size; size=${size:-30}
    read -rp "  4. 开启免费检测(需Cookie)? [y/N]: " scrape
    local enable_scrape="false" cookie=""
    if [[ "$scrape" =~ ^[Yy] ]]; then
        enable_scrape="true"
        read -rp "     Cookie (key=val): " cookie
    fi
    read -rp "  5. 优先下载首尾块? [y/N]: " prio
    local first_last="false"; [[ "$prio" =~ ^[Yy] ]] && first_last="true"
    
    python3 -c "
import json
try:
    with open('$RSS_RULES', 'r') as f: d = json.load(f)
except: d = []
d.append({'url':'$url','category':'$cat','max_size_gb':float('$size'),'enable_scrape':$enable_scrape,'cookie':'$cookie','first_last_piece':$first_last})
with open('$RSS_RULES', 'w') as f: json.dump(d, f, indent=2)
"
    echo -e "  ${G}✔ 添加成功${N}"; sleep 1
}

rss_del() {
    rss_render_list
    read -rp "  删除ID: " n
    if [[ "$n" =~ ^[0-9]+$ ]]; then
        res=$(python3 -c "
import json
try:
    with open('$RSS_RULES', 'r') as f: d = json.load(f)
    if 0 <= int('$n')-1 < len(d):
        del d[int('$n')-1]
        with open('$RSS_RULES', 'w') as f: json.dump(d, f, indent=2)
        print('ok')
except: print('err')
")
        [[ "$res" == "ok" ]] && echo -e "  ${G}✔ 已删除${N}" || echo -e "  ${R}✖ 失败${N}"
        sleep 1
    fi
}

rss_manager() {
    while true; do
        clear; echo -e "\n  ${B}──${N} ${C}Native RSS 管理${N} ${B}──${N}\n"
        rss_render_list
        echo -e "  ${C}1.${N} 添加订阅   ${C}2.${N} 删除订阅   ${C}3.${N} 修改间隔   ${C}4.${N} 开关模块   ${GR}0.${N} 返回"
        echo ""; read -rp "  选择: " op
        case "$op" in
            1) rss_add_wizard ;;
            2) rss_del ;;
            3) cur=$(get_val "autograb_interval_sec"); read -rp "  当前 ${cur}s，新间隔: " nv; [[ "$nv" =~ ^[0-9]+$ ]] && set_kv "autograb_interval_sec" "$nv" && systemctl restart qbit-smart-limit ;;
            4) cur=$(get_bool "autograb_enabled"); [[ "$cur" == "true" ]] && set_kv "autograb_enabled" "false" || set_kv "autograb_enabled" "true"; systemctl restart qbit-smart-limit ;;
            0) return ;;
        esac
    done
}

autorm_manager() {
    while true; do
        clear; echo -e "\n  ${B}──${N} ${C}AutoRemove 管理${N} ${B}──${N}\n"
        if [[ ! -s "$AUTORM_RULES" || "$(cat "$AUTORM_RULES")" == "[]" ]]; then echo -e "  ${GR}(无规则)${N}"; else
            python3 -c "import json; [print(f'  {i+1}. {x.get(\"name\")}') for i,x in enumerate(json.load(open('$AUTORM_RULES')))]" 2>/dev/null
        fi
        echo ""
        echo -e "  ${C}1.${N} 编辑规则文件   ${C}2.${N} 修改检测间隔   ${C}3.${N} 开关模块   ${GR}0.${N} 返回"
        echo ""; read -rp "  选择: " op
        case "$op" in
            1) if command -v nano >/dev/null; then nano "$AUTORM_RULES"; else vi "$AUTORM_RULES"; fi; systemctl restart qbit-smart-limit ;;
            2) cur=$(get_val "autoremove_interval_sec"); read -rp "  当前 ${cur}s，新间隔: " nv; [[ "$nv" =~ ^[0-9]+$ ]] && set_kv "autoremove_interval_sec" "$nv" && systemctl restart qbit-smart-limit ;;
            3) cur=$(get_bool "autoremove_enabled"); [[ "$cur" == "true" ]] && set_kv "autoremove_enabled" "false" || set_kv "autoremove_enabled" "true"; systemctl restart qbit-smart-limit ;;
            0) return ;;
        esac
    done
}

install_core() {
    echo -e "\n  ${B}📦 安装依赖...${N}"
    if command -v apt-get &>/dev/null; then apt-get update -qq; apt-get install -y python3 python3-pip curl -qq; fi
    if command -v yum &>/dev/null; then yum install -y python3 python3-pip curl -q; fi
    pip3 install --break-system-packages -q qbittorrent-api requests beautifulsoup4 lxml 2>/dev/null || \
    pip3 install -q qbittorrent-api requests beautifulsoup4 lxml
    
    download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py"
    mkdir -p "${INSTALL_DIR}/src"
    local base="${GITHUB_RAW}/src"
    local files=("__init__.py" "consts.py" "utils.py" "config.py" "database.py" "model.py" "algorithms.py" "logic.py" "helper_web.py" "helper_bot.py" "workers.py" "controller.py")
    for f in "${files[@]}"; do download "${base}/${f}" "${INSTALL_DIR}/src/${f}" "src/${f}"; done
}

do_install() {
    install_core
    echo -e "\n  ${C}⚙️ 连接配置${N}"
    read -rp "  Host [http://127.0.0.1:8080]: " h; h=${h:-"http://127.0.0.1:8080"}
    read -rp "  User [admin]: " u; u=${u:-"admin"}
    read -rsp "  Pass: " p; echo ""
    
    cat > "$CONFIG_FILE" <<EOF
{
  "host": "$h", "username": "$u", "password": "$(json_escape "$p")",
  "target_speed_kib": 51200, "safety_margin": 0.98, "log_level": "INFO",
  "telegram_bot_token": "", "telegram_chat_id": "", "u2_cookie": "",
  "autograb_enabled": false, "autograb_interval_sec": 120,
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
    systemctl daemon-reload; systemctl enable --now qbit-smart-limit
    download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "qsl命令"
    echo -e "\n  ${G}✨ 安装成功! 输入 qsl 即可进入管理${N}"; read -rp "  按回车继续..."
}

main() {
    if [[ $EUID -ne 0 ]]; then echo -e "${R}请使用 sudo qsl 运行${N}"; exit 1; fi
    ensure_env
    while true; do
        show_ui
        read -rp "  请选择 [0-11]: " choice
        choice="${choice//$'\r'/}"
        choice="${choice//[[:space:]]/}"
        case "$choice" in
            1) do_install ;;
            2) if command -v nano >/dev/null; then nano "$CONFIG_FILE"; else vi "$CONFIG_FILE"; fi; systemctl restart qbit-smart-limit ;;
            3) clear; systemctl status qbit-smart-limit; read -rp "..." ;;
            4) echo -e "\n  ${GR}按 Ctrl+C 退出${N}"; journalctl -u qbit-smart-limit -f ;;
            5) systemctl start qbit-smart-limit; echo -e "  ${G}已启动${N}"; sleep 1 ;;
            6) systemctl stop qbit-smart-limit; echo -e "  ${R}已停止${N}"; sleep 1 ;;
            7) systemctl restart qbit-smart-limit; echo -e "  ${G}已重启${N}"; sleep 1 ;;
            8) install_core; download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "脚本"; systemctl restart qbit-smart-limit; echo -e "  ${G}更新完成${N}"; sleep 1 ;;
            9) systemctl disable --now qbit-smart-limit; rm -rf "$INSTALL_DIR" "$SERVICE_FILE" "$SCRIPT_PATH"; echo "  已卸载"; exit 0 ;;
            10) rss_manager ;;
            11) autorm_manager ;;
            0) exit 0 ;;
            *) echo -e "  ${R}无效选择${N}"; sleep 1 ;;
        esac
    done
}

main "$@"
