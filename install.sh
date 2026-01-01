#!/bin/bash
#
# qBit Smart Limit 管理脚本 v11.1.0 PRO
# 适配 Python 集成架构 (FlexGet & AutoRemove 内置版)
#

# ==============================================================================
GITHUB_RAW="https://raw.githubusercontent.com/1336665/qbit_smart_limit/main"
# ==============================================================================

SCRIPT_PATH="/usr/local/bin/qsl"
INSTALL_DIR="/opt/qbit-smart-limit"
CONFIG_FILE="${INSTALL_DIR}/config.json"
MAIN_PY="${INSTALL_DIR}/main.py"
SERVICE_FILE="/etc/systemd/system/qbit-smart-limit.service"
SCRIPT_VER="11.1.0"

# 模块路径
FLEXGET_DIR="${INSTALL_DIR}/flexget"
AUTORM_DIR="${INSTALL_DIR}/autoremove"
FLEXGET_CFG="${FLEXGET_DIR}/config.yml"
FLEXGET_SUBS="${FLEXGET_DIR}/subscriptions.json"
FLEXGET_LOG="/var/log/qsl-flexget.log"

AUTORM_RULES="${AUTORM_DIR}/rules.json"
AUTORM_STATE="${AUTORM_DIR}/state.json"
AUTORM_LOG="/var/log/qsl-autoremove.log"

# 颜色定义
R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
B='\033[0;34m'
C='\033[0;36m'
W='\033[1;37m'
D='\033[0;90m'
N='\033[0m'

# ════════════════════════════════════════════════════════════
# 管道安装检测
# ════════════════════════════════════════════════════════════
if [[ ! -t 0 ]]; then
    echo ""
    echo -e "  ${C}安装管理脚本...${N}"
    cat > "$SCRIPT_PATH"
    chmod +x "$SCRIPT_PATH"
    echo -e "  ${G}✓${N} 已安装到 $SCRIPT_PATH"
    echo -e "  ${W}请运行 qsl 打开管理菜单${N}"
    echo ""
    exit 0
fi

# ════════════════════════════════════════════════════════════
# 基础工具函数
# ════════════════════════════════════════════════════════════
ok()   { echo -e "  ${G}✓${N} $1"; }
err()  { echo -e "  ${R}✗${N} $1"; }
warn() { echo -e "  ${Y}!${N} $1"; }
info() { echo -e "  ${C}i${N} $1"; }

is_installed() { [[ -f "$MAIN_PY" && -f "$CONFIG_FILE" ]]; }
is_running() { systemctl is-active --quiet qbit-smart-limit 2>/dev/null; }

get_local_ver() {
    [[ -f "${INSTALL_DIR}/src/consts.py" ]] && grep -oP 'VERSION = "\K[^"]+' "${INSTALL_DIR}/src/consts.py" 2>/dev/null | head -1 || echo "-"
}

get_remote_ver() {
    curl -sL --connect-timeout 5 "${GITHUB_RAW}/src/consts.py" 2>/dev/null | grep -oP 'VERSION = "\K[^"]+' | head -1
}

json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    echo "$s"
}

clean_cookie() {
    local c="$1"
    c="${c#nexusphp_u2=}"
    c="${c#\"}"
    c="${c%\"}"
    c="${c#\'}"
    c="${c%\'}"
    c="${c## }"
    c="${c%% }"
    echo "$c"
}

get_config_val() {
    local key="$1" default="$2"
    if [[ -f "$CONFIG_FILE" ]]; then
        local val
        val=$(jq -r ".$key // \"$default\"" "$CONFIG_FILE" 2>/dev/null)
        [[ "$val" == "null" ]] && echo "$default" || echo "$val"
    else
        echo "$default"
    fi
}

get_config_bool() {
    local key="$1" default="$2"
    if [[ -f "$CONFIG_FILE" ]]; then
        local val
        val=$(jq -r ".$key" "$CONFIG_FILE" 2>/dev/null)
        if [[ "$val" == "true" ]]; then echo "true"; elif [[ "$val" == "false" ]]; then echo "false"; else echo "$default"; fi
    else
        echo "$default"
    fi
}

set_config_bool() {
    local key="$1" value="$2"
    local tmp_cfg="/tmp/cfg_set_$$.json"
    if [[ "$value" == "true" ]]; then
        jq ".$key = true" "$CONFIG_FILE" > "$tmp_cfg" 2>/dev/null
    else
        jq ".$key = false" "$CONFIG_FILE" > "$tmp_cfg" 2>/dev/null
    fi
    if [[ -s "$tmp_cfg" ]] && jq empty "$tmp_cfg" 2>/dev/null; then
        mv "$tmp_cfg" "$CONFIG_FILE"
        chmod 600 "$CONFIG_FILE"
        return 0
    else
        rm -f "$tmp_cfg" 2>/dev/null
        return 1
    fi
}

ensure_dirs() {
    mkdir -p "$FLEXGET_DIR" "$AUTORM_DIR" "${INSTALL_DIR}/src" >/dev/null 2>&1 || true
    mkdir -p /var/log >/dev/null 2>&1 || true
}

cleanup() {
    rm -f /tmp/qsl_*.tmp /tmp/cfg_*.json 2>/dev/null
}
trap cleanup EXIT

# ════════════════════════════════════════════════════════════
# 界面显示
# ════════════════════════════════════════════════════════════
show_banner() {
    clear
    echo ""
    echo -e "${C}  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${N}"
    echo -e "${C}  ┃${N}  ${G} ██████  ${W}██████  ${C}██${N} ████████   ${G}███████${N} ${W}██${N}          ${C}┃${N}"
    echo -e "${C}  ┃${N}  ${G}██    ██ ${W}██   ██ ${C}██${N}    ██      ${G}██     ${N} ${W}██${N}          ${C}┃${N}"
    echo -e "${C}  ┃${N}  ${G}██    ██ ${W}██████  ${C}██${N}    ██      ${G}███████${N} ${W}██${N}          ${C}┃${N}"
    echo -e "${C}  ┃${N}  ${G}██ ▄▄ ██ ${W}██   ██ ${C}██${N}    ██           ${G}██${N} ${W}██${N}          ${C}┃${N}"
    echo -e "${C}  ┃${N}  ${G} ██████  ${W}██████  ${C}██${N}    ██      ${G}███████${N} ${W}███████${N}     ${C}┃${N}"
    echo -e "${C}  ┃${N}  ${G}    ▀▀${N}                                              ${C}┃${N}"
    echo -e "${C}  ┃${N}         ${Y}qBit Smart Limit v${SCRIPT_VER} PRO${N}              ${C}┃${N}"
    echo -e "${C}  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${N}"
    echo ""
}

show_status() {
    local inst_st serv_st local_v u2_st dl_st ra_st flex_st ar_st
    
    if is_installed; then
        inst_st="${G}● 已安装${N}"
        local_v=$(get_local_ver)
    else
        inst_st="${Y}○ 未安装${N}"
        local_v="-"
    fi
    
    if is_running; then
        serv_st="${G}● 运行中${N}"
    else
        serv_st="${R}○ 已停止${N}"
    fi
    
    # 功能状态检测
    u2_st="${D}○ 未配置${N}"
    dl_st="${D}○ 未配置${N}"
    ra_st="${D}○ 未配置${N}"
    flex_st="${D}○ 未配置${N}"
    ar_st="${D}○ 未配置${N}"

    if [[ -f "$CONFIG_FILE" ]]; then
        # U2
        local u2_cookie
        u2_cookie=$(jq -r '.u2_cookie // ""' "$CONFIG_FILE" 2>/dev/null)
        if [[ -n "$u2_cookie" && "$u2_cookie" != "null" ]]; then
            u2_st="${G}● 已启用${N}"
        fi
        
        # 核心功能
        [[ $(get_config_bool "enable_dl_limit" "true") == "true" ]] && dl_st="${G}● 已启用${N}" || dl_st="${R}○ 未启用${N}"
        [[ $(get_config_bool "enable_reannounce_opt" "true") == "true" ]] && ra_st="${G}● 已启用${N}" || ra_st="${R}○ 未启用${N}"
        
        # 集成模块 (读取 Config 开关)
        [[ $(get_config_bool "flexget_enabled" "false") == "true" ]] && flex_st="${G}● 已启用${N}" || flex_st="${R}○ 未启用${N}"
        [[ $(get_config_bool "autoremove_enabled" "false") == "true" ]] && ar_st="${G}● 已启用${N}" || ar_st="${R}○ 未启用${N}"
    fi

    echo -e "  ${D}┌────────────────────────────────────────────────────────────────┐${N}"
    echo -e "  ${D}│${N}  ${W}安装状态${N}  $inst_st        ${W}服务状态${N}  $serv_st            ${D}│${N}"
    echo -e "  ${D}│${N}  ${W}核心版本${N}  ${C}${local_v}${N}    ${W}脚本版本${N}  ${D}v${SCRIPT_VER}${N}              ${D}│${N}"
    echo -e "  ${D}├────────────────────────────────────────────────────────────────┤${N}"
    echo -e "  ${D}│${N}  ${W}U2 辅助${N}   $u2_st        ${W}Telegram${N}  ${D}见配置${N}               ${D}│${N}"
    echo -e "  ${D}│${N}  ${W}下载限速${N}  $dl_st        ${W}汇报优化${N}  $ra_st            ${D}│${N}"
    echo -e "  ${D}│${N}  ${W}FlexGet${N}   $flex_st        ${W}AutoRemove${N}  $ar_st            ${D}│${N}"
    echo -e "  ${D}└────────────────────────────────────────────────────────────────┘${N}"
    echo ""
}

show_menu() {
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
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━ 自动化 ━━━━━━━━━━━━━━━━━━━${N}"
    echo ""
    echo -e "     ${G}10${N}. FlexGet 自动抓种        ${G}11${N}. AutoRemove 自动删种"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━ 其他 ━━━━━━━━━━━━━━━━━━━━━━${N}"
    echo ""
    echo -e "     ${G}8${N}. 检查更新              ${R}9${N}. 卸载程序"
    echo -e "     ${D}0${N}. 退出"
    echo ""
}

# ════════════════════════════════════════════════════════════
# 依赖安装
# ════════════════════════════════════════════════════════════
install_deps() {
    echo ""
    info "安装系统依赖..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq &>/dev/null || true
        apt-get install -y python3 python3-pip jq curl python3-requests python3-bs4 python3-lxml -qq &>/dev/null || true
    elif command -v yum &>/dev/null; then
        yum install -y python3 python3-pip jq curl -q &>/dev/null || true
    fi
    
    ok "系统依赖"
    info "检查 Python 依赖..."
    
    if ! python3 -c "import qbittorrentapi" &>/dev/null; then
        pip3 install --break-system-packages -q qbittorrent-api 2>/dev/null || pip3 install -q qbittorrent-api 2>/dev/null || true
    fi
    if ! command -v flexget &>/dev/null; then
        pip3 install --break-system-packages -q flexget 2>/dev/null || pip3 install -q flexget 2>/dev/null || true
    fi
    
    ok "Python 依赖"
    return 0
}

download() {
    local url="$1" dest="$2" name="$3"
    local tmp="/tmp/qsl_dl_$$.tmp"
    echo -ne "  ${C}↓${N} 下载 ${name}..."
    local http_code
    http_code=$(curl -sL --connect-timeout 15 -w "%{http_code}" "$url" -o "$tmp" 2>/dev/null)
    if [[ "$http_code" == "200" && -s "$tmp" ]]; then
        mv "$tmp" "$dest"
        chmod +x "$dest"
        echo -e "\r  ${G}✓${N} 下载 ${name}              "
        return 0
    fi
    rm -f "$tmp" 2>/dev/null
    echo -e "\r  ${R}✗${N} 下载 ${name} (HTTP $http_code)   "
    return 1
}

# 递归下载 src 目录中的文件 (简单模拟)
install_source_files() {
    mkdir -p "${INSTALL_DIR}/src"
    local base="${GITHUB_RAW}/src"
    local files=("__init__.py" "consts.py" "utils.py" "config.py" "database.py" "model.py" "algorithms.py" "logic.py" "helper_web.py" "helper_bot.py" "workers.py" "controller.py")
    
    for f in "${files[@]}"; do
        download "${base}/${f}" "${INSTALL_DIR}/src/${f}" "src/${f}" || return 1
    done
    return 0
}

# ════════════════════════════════════════════════════════════
# FlexGet 模块
# ════════════════════════════════════════════════════════════
flexget_init() {
    ensure_dirs
    [[ -f "$FLEXGET_SUBS" ]] || echo '{"tasks":[]}' > "$FLEXGET_SUBS"
    # 生成一个初始的 config.yml
    flexget_regen_config
}

flexget_regen_config() {
    ensure_dirs
    # 简易生成器，将订阅转为 config.yml
    python3 - <<'PY' >/dev/null 2>&1
import json
from pathlib import Path
CFG=Path("/opt/qbit-smart-limit/config.json")
SUBS=Path("/opt/qbit-smart-limit/flexget/subscriptions.json")
YML=Path("/opt/qbit-smart-limit/flexget/config.yml")

def load(p, d):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return d

cfg=load(CFG,{})
subs=load(SUBS,{"tasks":[]}).get("tasks",[])
tasks=[]
for t in subs:
    name=(t.get("name") or "").strip()
    rss=(t.get("rss") or "").strip()
    cat=(t.get("category") or "u2").strip()
    tags=t.get("tags") or []
    if not name or not rss: continue
    tasks.append(f"""  {name}:
    rss: "{rss}"
    accept_all: yes
    seen: local
    qbittorrent:
      host: "{cfg.get('host','')}"
      username: "{cfg.get('username','')}"
      password: "{cfg.get('password','')}"
      category: "{cat}"
      tags: {tags}
""")
if not tasks: YML.write_text("tasks: {}\n", encoding="utf-8")
else: YML.write_text("tasks:\n"+ "".join(tasks), encoding="utf-8")
PY
}

flexget_list_subs() {
    ensure_dirs
    [[ -f "$FLEXGET_SUBS" ]] || { echo -e "  ${D}暂无订阅${N}"; return; }
    local cnt
    cnt=$(jq '.tasks|length' "$FLEXGET_SUBS" 2>/dev/null || echo 0)
    echo -e "  ${W}当前订阅数:${N} ${C}${cnt}${N}"
    if [[ "$cnt" -gt 0 ]]; then
        jq -r '.tasks[] | "  - \(.name)  [cat=\(.category)]"' "$FLEXGET_SUBS" 2>/dev/null || true
    fi
}

flexget_add_sub() {
    ensure_dirs
    echo ""
    read -rp "  订阅名称(英文/数字) [u2_auto]: " name
    name=${name:-u2_auto}
    read -rp "  RSS 地址: " rss
    [[ -z "$rss" ]] && { err "RSS 不能为空"; return; }
    read -rp "  qB 分类 [u2]: " cat; cat=${cat:-u2}
    
    tmp="/tmp/qsl_flexget_$$.json"
    if jq --arg name "$name" --arg rss "$rss" --arg cat "$cat" \
        '.tasks += [{"name":$name,"rss":$rss,"category":$cat,"tags":[]}]' "$FLEXGET_SUBS" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$FLEXGET_SUBS"
        ok "已添加订阅: $name"
        flexget_regen_config
    else
        rm -f "$tmp"; err "添加失败"
    fi
}

flexget_del_sub() {
    ensure_dirs
    echo ""; flexget_list_subs; echo ""
    read -rp "  输入要删除的序号(从1开始): " n
    [[ ! "$n" =~ ^[0-9]+$ ]] && return
    tmp="/tmp/qsl_flexget_$$.json"
    if jq " .tasks |= (del(.[$((n-1))])) " "$FLEXGET_SUBS" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$FLEXGET_SUBS"
        ok "已删除"
        flexget_regen_config
    else
        rm -f "$tmp"; err "删除失败"
    fi
}

flexget_toggle() {
    local cur
    cur=$(get_config_bool "flexget_enabled" "false")
    echo ""
    if [[ "$cur" == "true" ]]; then
        read -rp "  确认关闭 FlexGet? [y/N]: " c
        if [[ "$c" =~ ^[Yy] ]]; then
            set_config_bool "flexget_enabled" "false"
            warn "FlexGet 已关闭 (请重启服务生效)"
        fi
    else
        read -rp "  确认开启 FlexGet? [Y/n]: " c
        if [[ ! "$c" =~ ^[Nn] ]]; then
            set_config_bool "flexget_enabled" "true"
            ok "FlexGet 已开启 (请重启服务生效)"
        fi
    fi
}

flexget_set_interval() {
    local cur
    cur=$(jq -r '.flexget_interval_sec // 120' "$CONFIG_FILE")
    echo ""
    echo -e "  当前间隔: ${C}${cur}${N} 秒"
    read -rp "  新间隔(秒): " v
    if [[ "$v" =~ ^[0-9]+$ ]]; then
        tmp=$(mktemp)
        jq ".flexget_interval_sec = $v" "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"
        ok "间隔已更新 (请重启服务生效)"
    fi
}

flexget_run_now() {
    echo ""
    info "立即执行 FlexGet (CLI)..."
    flexget -c "$FLEXGET_CFG" execute
    echo ""
    read -rp "按回车继续..."
}

flexget_menu() {
    flexget_init
    while true; do
        show_banner; show_status
        echo -e "  ${C}━━━━━━━━━━━━━━━━ FlexGet 菜单 ━━━━━━━━━━━━━━━━${N}"
        echo -e "     ${G}1${N}. 查看订阅任务      ${G}2${N}. 添加订阅任务"
        echo -e "     ${G}3${N}. 删除订阅任务      ${G}4${N}. 立即执行一次"
        echo -e "     ${G}5${N}. 修改抓取间隔      ${G}6${N}. 开关服务"
        echo -e "     ${G}7${N}. 查看日志"
        echo -e "     ${D}0${N}. 返回主菜单"
        read -rp "  选择: " c
        case "$c" in
            1) flexget_list_subs; read -rp "按回车继续..." ;;
            2) flexget_add_sub ;;
            3) flexget_del_sub ;;
            4) flexget_run_now ;;
            5) flexget_set_interval ;;
            6) flexget_toggle ;;
            7) tail -n 50 "$FLEXGET_LOG"; read -rp "按回车继续..." ;;
            0) return ;;
        esac
    done
}

# ════════════════════════════════════════════════════════════
# AutoRemove 模块
# ════════════════════════════════════════════════════════════
autorm_init() {
    ensure_dirs
    [[ -f "$AUTORM_RULES" ]] || echo '[{"name":"Default Rule","min_free_gb":10,"max_up_bps":102400,"min_low_sec":60}]' > "$AUTORM_RULES"
}

autorm_show_rules() {
    ensure_dirs
    echo -e "  ${W}当前规则:${N}"
    jq -r 'to_entries[] | "  \(.key+1). \(.value.name) [剩余<\(.value.min_free_gb)G]"' "$AUTORM_RULES" 2>/dev/null || true
}

autorm_toggle() {
    local cur
    cur=$(get_config_bool "autoremove_enabled" "false")
    echo ""
    if [[ "$cur" == "true" ]]; then
        read -rp "  确认关闭 自动删种? [y/N]: " c
        if [[ "$c" =~ ^[Yy] ]]; then
            set_config_bool "autoremove_enabled" "false"
            warn "自动删种 已关闭 (请重启服务生效)"
        fi
    else
        read -rp "  确认开启 自动删种? [Y/n]: " c
        if [[ ! "$c" =~ ^[Nn] ]]; then
            set_config_bool "autoremove_enabled" "true"
            ok "自动删种 已开启 (请重启服务生效)"
        fi
    fi
}

autorm_set_interval() {
    local cur
    cur=$(jq -r '.autoremove_interval_sec // 1800' "$CONFIG_FILE")
    echo ""
    echo -e "  当前间隔: ${C}${cur}${N} 秒"
    read -rp "  新间隔(秒): " v
    if [[ "$v" =~ ^[0-9]+$ ]]; then
        tmp=$(mktemp)
        jq ".autoremove_interval_sec = $v" "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"
        ok "间隔已更新 (请重启服务生效)"
    fi
}

autorm_menu() {
    autorm_init
    while true; do
        show_banner; show_status
        echo -e "  ${C}━━━━━━━━━━━━━━━ AutoRemove 菜单 ━━━━━━━━━━━━━━${N}"
        echo -e "     ${G}1${N}. 查看当前策略      ${G}2${N}. 编辑策略文件"
        echo -e "     ${G}3${N}. 修改检查间隔      ${G}4${N}. 开关服务"
        echo -e "     ${G}5${N}. 查看日志"
        echo -e "     ${D}0${N}. 返回主菜单"
        read -rp "  选择: " c
        case "$c" in
            1) autorm_show_rules; read -rp "按回车继续..." ;;
            2) ${EDITOR:-nano} "$AUTORM_RULES" ;;
            3) autorm_set_interval ;;
            4) autorm_toggle ;;
            5) tail -n 50 "$AUTORM_LOG"; read -rp "按回车继续..." ;;
            0) return ;;
        esac
    done
}

# ════════════════════════════════════════════════════════════
# 配置输入与保存
# ════════════════════════════════════════════════════════════
get_input() {
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━ qBittorrent 设置 ━━━━━━━━━━━━━━━${N}"
    read -rp "  WebUI 地址 [http://127.0.0.1:8080]: " QB_HOST
    QB_HOST=${QB_HOST:-"http://127.0.0.1:8080"}
    read -rp "  用户名 [admin]: " QB_USER
    QB_USER=${QB_USER:-"admin"}
    read -rsp "  密码: " QB_PASS
    echo ""
    [[ -z "$QB_PASS" ]] && { err "密码不能为空"; return 1; }
    
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━ 速度设置 ━━━━━━━━━━━━━━━━━━━${N}"
    read -rp "  目标速度 KiB/s [51200]: " TARGET
    TARGET=${TARGET:-51200}
    read -rp "  安全系数 [0.98]: " SAFETY
    SAFETY=${SAFETY:-0.98}
    read -rp "  Tracker 关键词 (留空匹配所有): " TRACKER
    TRACKER=${TRACKER:-""}
    
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━ 高级功能 (PRO) ━━━━━━━━━━━━━━━${N}"
    read -rp "  启用下载限速? [Y/n]: " DL_LIMIT
    [[ "$DL_LIMIT" =~ ^[Nn] ]] && ENABLE_DL_LIMIT="false" || ENABLE_DL_LIMIT="true"
    read -rp "  启用汇报优化? [Y/n]: " RA_OPT
    [[ "$RA_OPT" =~ ^[Nn] ]] && ENABLE_RA_OPT="false" || ENABLE_RA_OPT="true"
    
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━ Telegram 通知 (可选) ━━━━━━━━━━━━${N}"
    read -rp "  Bot Token: " TG_TOKEN
    TG_TOKEN=${TG_TOKEN:-""}
    TG_CHAT=""
    if [[ -n "$TG_TOKEN" ]]; then read -rp "  Chat ID: " TG_CHAT; fi
    
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━ U2 Cookie (可选) ━━━━━━━━━━━━━━━${N}"
    read -rp "  Cookie (Value only): " U2_COOKIE
    U2_COOKIE=$(clean_cookie "${U2_COOKIE:-""}")
    read -rp "  HTTP 代理 (可选): " PROXY
    PROXY=${PROXY:-""}
    return 0
}

save_config() {
    mkdir -p "$INSTALL_DIR"
    local peer="false"
    [[ -n "$U2_COOKIE" ]] && peer="true"
    local esc_pass esc_token esc_chat esc_cookie esc_proxy
    esc_pass=$(json_escape "$QB_PASS")
    esc_token=$(json_escape "$TG_TOKEN")
    esc_chat=$(json_escape "$TG_CHAT")
    esc_cookie=$(json_escape "$U2_COOKIE")
    esc_proxy=$(json_escape "$PROXY")
    
    cat > "$CONFIG_FILE" << EOFCFG
{
  "host": "$QB_HOST",
  "username": "$QB_USER",
  "password": "$esc_pass",
  "target_speed_kib": $TARGET,
  "safety_margin": $SAFETY,
  "log_level": "INFO",
  "target_tracker_keyword": "$TRACKER",
  "exclude_tracker_keyword": "",
  "telegram_bot_token": "$esc_token",
  "telegram_chat_id": "$esc_chat",
  "max_physical_speed_kib": 0,
  "api_rate_limit": 20,
  "u2_cookie": "$esc_cookie",
  "proxy": "$esc_proxy",
  "peer_list_enabled": $peer,
  "enable_dl_limit": $ENABLE_DL_LIMIT,
  "enable_reannounce_opt": $ENABLE_RA_OPT,
  "flexget_enabled": false,
  "flexget_interval_sec": 120,
  "autoremove_enabled": false,
  "autoremove_interval_sec": 1800
}
EOFCFG
    chmod 600 "$CONFIG_FILE"
    if ! jq empty "$CONFIG_FILE" &>/dev/null; then err "配置文件格式错误"; return 1; fi
    return 0
}

create_service() {
    cat > "$SERVICE_FILE" << EOFSVC
[Unit]
Description=qBit Smart Limit Service
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $MAIN_PY
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOFSVC
    systemctl daemon-reload
}

# ════════════════════════════════════════════════════════════
# 主逻辑
# ════════════════════════════════════════════════════════════
do_install() {
    show_banner
    echo -e "  ${W}>>> 安装 qBit Smart Limit PRO <<<${N}"
    echo ""
    install_deps || return 1
    mkdir -p "$INSTALL_DIR"
    
    download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py" || return 1
    # 核心：下载 src 包
    install_source_files || return 1
    
    get_input || return 1
    echo ""
    if ! save_config; then err "保存配置失败"; return 1; fi
    create_service && ok "系统服务已创建"
    download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "管理脚本" || true
    systemctl enable qbit-smart-limit &>/dev/null || true
    systemctl start qbit-smart-limit && ok "服务已启动"
    
    # 自动清理旧版定时器 (如果存在)
    systemctl stop flexget-qsl.timer autoremove-qsl.timer 2>/dev/null || true
    systemctl disable flexget-qsl.timer autoremove-qsl.timer 2>/dev/null || true
    rm -f /etc/systemd/system/flexget-qsl.* /etc/systemd/system/autoremove-qsl.*
    systemctl daemon-reload
    
    echo ""
    echo -e "  ${G}安装完成! 运行 qsl 打开菜单${N}"
}

do_update() {
    echo ""
    echo -e "  ${W}>>> 检查更新 <<<${N}"
    local remote_v; remote_v=$(get_remote_ver)
    if [[ -z "$remote_v" ]]; then err "无法获取远程版本"; return; fi
    echo -e "  远程版本: ${C}$remote_v${N}"
    echo -e "  本地版本: ${W}$(get_local_ver)${N}"
    read -rp "  确认更新? [y/N]: " c
    if [[ "$c" =~ ^[Yy] ]]; then
        if download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py" && install_source_files; then
            systemctl restart qbit-smart-limit
            ok "更新完成并重启服务"
        fi
    fi
}

do_uninstall() {
    echo ""; echo -e "  ${R}>>> 卸载 <<<${N}"
    read -rp "  确认卸载? [y/N]: " confirm
    [[ ! "$confirm" =~ ^[Yy] ]] && return
    systemctl stop qbit-smart-limit 2>/dev/null
    systemctl disable qbit-smart-limit 2>/dev/null
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
    rm -f "$SCRIPT_PATH"
    read -rp "  删除配置文件? [y/N]: " d
    [[ "$d" =~ ^[Yy] ]] && rm -rf "$INSTALL_DIR"
    ok "卸载完成"
}

main() {
    if [[ $EUID -ne 0 ]]; then echo -e "${R}请使用 root 运行${N}"; exit 1; fi
    while true; do
        show_banner; show_status; show_menu
        read -rp "  请选择 [0-11]: " choice
        case "$choice" in
            1) do_install ;;
            2) ${EDITOR:-nano} "$CONFIG_FILE" && systemctl restart qbit-smart-limit ;;
            3) show_status; read -rp "按回车继续..." ;;
            4) journalctl -u qbit-smart-limit -f ;;
            5) systemctl start qbit-smart-limit && ok "已启动" ;;
            6) systemctl stop qbit-smart-limit && warn "已停止" ;;
            7) systemctl restart qbit-smart-limit && ok "已重启" ;;
            8) do_update ;;
            9) do_uninstall ;;
            10) flexget_menu ;;
            11) autoremove_menu ;;
            0) exit 0 ;;
            *) err "无效选择" ;;
        esac
        echo ""; read -rp "  按回车继续..."
    done
}

main "$@"
