#!/bin/bash
#
# qBit Smart Limit 管理脚本 v11.1.0 PRO
# 适配 Python 集成架构 | 包含一键配置向导
#

# =========================================================
# ⚠️ 请修改此处为你的 GitHub 仓库地址
GITHUB_RAW="https://raw.githubusercontent.com/1336665/qbit_smart_limit/main"
# =========================================================

INSTALL_DIR="/opt/qbit-smart-limit"
CONFIG_FILE="${INSTALL_DIR}/config.json"
SERVICE_FILE="/etc/systemd/system/qbit-smart-limit.service"
SCRIPT_PATH="/usr/local/bin/qsl"
MAIN_PY="${INSTALL_DIR}/main.py"

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
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; C='\033[0;36m'; W='\033[1;37m'; D='\033[0;90m'; N='\033[0m'

# ════════════════════════════════════════════════════════════
# 管道安装检测
# ════════════════════════════════════════════════════════════
if [[ ! -t 0 ]]; then
    echo ""; echo -e "  ${C}安装管理脚本...${N}"
    cat > "$SCRIPT_PATH"; chmod +x "$SCRIPT_PATH"
    echo -e "  ${G}✓${N} 已安装到 $SCRIPT_PATH"; echo -e "  ${W}请运行 qsl 打开菜单${N}"; echo ""
    exit 0
fi

# ════════════════════════════════════════════════════════════
# 基础工具函数 (修复报错)
# ════════════════════════════════════════════════════════════
ok()   { echo -e "  ${G}✓${N} $1"; }
err()  { echo -e "  ${R}✗${N} $1"; }
warn() { echo -e "  ${Y}!${N} $1"; }
info() { echo -e "  ${C}i${N} $1"; }

get_bool() { jq -r ".$1 // false" "$CONFIG_FILE" 2>/dev/null; }
get_val() { jq -r ".$1 // \"$2\"" "$CONFIG_FILE" 2>/dev/null; }

# 设置配置项 (兼容 bool/int/string)
set_kv() {
    local k="$1" v="$2"
    tmp=$(mktemp)
    if [[ "$v" == "true" || "$v" == "false" ]]; then
        jq ".$k = $v" "$CONFIG_FILE" > "$tmp"
    elif [[ "$v" =~ ^[0-9]+$ ]]; then
        jq ".$k = $v" "$CONFIG_FILE" > "$tmp"
    else
        jq --arg val "$v" ".$k = \$val" "$CONFIG_FILE" > "$tmp"
    fi
    mv "$tmp" "$CONFIG_FILE" && chmod 600 "$CONFIG_FILE"
}

# 确保目录存在
ensure_dirs() {
    mkdir -p "$FLEXGET_DIR" "$AUTORM_DIR" "${INSTALL_DIR}/src" "/var/log" >/dev/null 2>&1 || true
    [[ -f "$FLEXGET_SUBS" ]] || echo '{"tasks":[]}' > "$FLEXGET_SUBS"
    [[ -f "$AUTORM_RULES" ]] || echo '[]' > "$AUTORM_RULES"
    [[ -f "$FLEXGET_CFG" ]] || touch "$FLEXGET_CFG"
}

# 获取本地版本 (从 src/consts.py 读取)
get_local_ver() {
    [[ -f "${INSTALL_DIR}/src/consts.py" ]] && grep -oP 'VERSION = "\K[^"]+' "${INSTALL_DIR}/src/consts.py" 2>/dev/null | head -1 || echo "-"
}

# 获取远程版本
get_remote_ver() {
    curl -sL --connect-timeout 5 "${GITHUB_RAW}/src/consts.py" 2>/dev/null | grep -oP 'VERSION = "\K[^"]+' | head -1
}

# 简单的下载函数
download() {
    local url="$1" dest="$2" name="$3"
    local tmp="/tmp/qsl_dl_$$.tmp"
    echo -ne "  ${C}↓${N} 下载 ${name}..."
    local http_code
    http_code=$(curl -sL --connect-timeout 15 -w "%{http_code}" "$url" -o "$tmp" 2>/dev/null)
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

# 下载所有源文件 (src目录)
install_source_files() {
    mkdir -p "${INSTALL_DIR}/src"
    local base="${GITHUB_RAW}/src"
    # 这里列出所有拆分后的文件
    local files=("__init__.py" "consts.py" "utils.py" "config.py" "database.py" "model.py" "algorithms.py" "logic.py" "helper_web.py" "helper_bot.py" "workers.py" "controller.py")
    
    for f in "${files[@]}"; do
        download "${base}/${f}" "${INSTALL_DIR}/src/${f}" "src/${f}" || return 1
    done
    return 0
}

# 安装依赖
install_deps() {
    echo ""; info "安装系统依赖..."
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
    # 尝试安装 FlexGet (可选)
    if ! command -v flexget &>/dev/null; then
        pip3 install --break-system-packages -q flexget 2>/dev/null || pip3 install -q flexget 2>/dev/null || true
    fi
    ok "Python 依赖"
    return 0
}

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
    echo -e "${C}  ┃${N}         ${Y}qBit Smart Limit v${SCRIPT_VER:-11.1.0} PRO${N}            ${C}┃${N}"
    echo -e "${C}  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${N}"
    echo ""
}

show_status() {
    # 核心服务状态
    if systemctl is-active --quiet qbit-smart-limit; then
        serv_st="${G}● 运行中${N}"
    else
        serv_st="${R}○ 已停止${N}"
    fi

    # 读取配置状态
    if [[ -f "$CONFIG_FILE" ]]; then
        # 核心功能
        [[ $(get_bool "enable_dl_limit") == "true" ]] && dl_st="${G}● 已启用${N}" || dl_st="${R}○ 未启用${N}"
        [[ $(get_bool "enable_reannounce_opt") == "true" ]] && ra_st="${G}● 已启用${N}" || ra_st="${R}○ 未启用${N}"
        
        # U2
        u2_c=$(get_val "u2_cookie" "")
        [[ -n "$u2_c" ]] && u2_st="${G}● 已配置${N}" || u2_st="${D}○ 未配置${N}"

        # 模块开关
        [[ $(get_bool "flexget_enabled") == "true" ]] && flex_st="${G}● 已启用${N}" || flex_st="${R}○ 未启用${N}"
        [[ $(get_bool "autoremove_enabled") == "true" ]] && ar_st="${G}● 已启用${N}" || ar_st="${R}○ 未启用${N}"
    else
        dl_st="${D}未知${N}"; ra_st="${D}未知${N}"; u2_st="${D}未知${N}"; flex_st="${D}未知${N}"; ar_st="${D}未知${N}"
    fi

    echo -e "  ${D}┌────────────────────────────────────────────────────────────────┐${N}"
    echo -e "  ${D}│${N}  ${W}服务状态${N}  $serv_st        ${W}U2 辅助${N}   $u2_st               ${D}│${N}"
    echo -e "  ${D}│${N}  ${W}下载限速${N}  $dl_st        ${W}汇报优化${N}  $ra_st               ${D}│${N}"
    echo -e "  ${D}│${N}  ${W}FlexGet${N}   $flex_st        ${W}AutoRemove${N}  $ar_st               ${D}│${N}"
    echo -e "  ${D}└────────────────────────────────────────────────────────────────┘${N}"
    echo ""
}

show_menu() {
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━━ 主菜单 ━━━━━━━━━━━━━━━━━━━━${N}"
    echo ""
    echo -e "     ${G}1${N}. 启动/重启服务           ${G}2${N}. 停止服务"
    echo -e "     ${G}3${N}. 查看实时日志            ${G}4${N}. 修改主配置"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━ 自动化模块 ━━━━━━━━━━━━━━━━━━${N}"
    echo ""
    echo -e "     ${Y}5${N}. FlexGet 自动抓种        ${Y}6${N}. AutoRemove 自动删种"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━ 其他 ━━━━━━━━━━━━━━━━━━━━━━${N}"
    echo ""
    echo -e "     ${G}8${N}. 检查更新                ${R}9${N}. 卸载程序"
    echo -e "     ${D}0${N}. 退出"
    echo ""
}

# ════════════════════════════════════════════════════════════
# FlexGet 功能区
# ════════════════════════════════════════════════════════════
flexget_regen_config() {
    ensure_dirs
    # 根据 subscriptions.json 生成 config.yml
    python3 - <<'PY' >/dev/null 2>&1
import json, os
from pathlib import Path
CFG=Path("/opt/qbit-smart-limit/config.json")
SUBS=Path("/opt/qbit-smart-limit/flexget/subscriptions.json")
YML=Path("/opt/qbit-smart-limit/flexget/config.yml")

def load(p, d):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return d

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
    echo -e "  ${C}当前订阅列表:${N}"
    jq -r 'to_entries[] | "  \(.key+1). \(.value.name) [\(.value.category)]"' <(jq '.tasks' "$FLEXGET_SUBS") 2>/dev/null || echo "  暂无订阅"
}

flexget_add_sub() {
    ensure_dirs
    echo ""
    read -rp "  订阅名称(英文): " name
    read -rp "  RSS 地址: " rss
    read -rp "  分类 [u2]: " cat; cat=${cat:-u2}
    tmp="/tmp/qsl_flexget_$$.json"
    if jq --arg name "$name" --arg rss "$rss" --arg cat "$cat" \
        '.tasks += [{"name":$name,"rss":$rss,"category":$cat,"tags":[]}]' "$FLEXGET_SUBS" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$FLEXGET_SUBS"
        flexget_regen_config
        ok "已添加订阅"
    else rm -f "$tmp"; err "添加失败"; fi
}

flexget_del_sub() {
    flexget_list_subs
    echo ""
    read -rp "  输入序号删除: " n
    [[ ! "$n" =~ ^[0-9]+$ ]] && return
    tmp="/tmp/qsl_flexget_$$.json"
    if jq " .tasks |= (del(.[$((n-1))])) " "$FLEXGET_SUBS" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$FLEXGET_SUBS"
        flexget_regen_config
        ok "已删除"
    else rm -f "$tmp"; err "删除失败"; fi
}

# FlexGet 一键配置
flexget_quick_setup() {
    echo ""
    echo -e "  ${W}>>> FlexGet 一键配置向导 <<<${N}"
    echo ""
    
    # 1. 启用模块
    read -rp "  是否启用 FlexGet 自动抓种? [Y/n]: " c
    if [[ ! "$c" =~ ^[Nn] ]]; then
        set_kv "flexget_enabled" "true"
        ok "模块已启用"
    else
        set_kv "flexget_enabled" "false"
        warn "模块已禁用"
        return
    fi
    
    # 2. 设置间隔
    read -rp "  抓取间隔(秒) [120]: " iv
    iv=${iv:-120}
    if [[ "$iv" =~ ^[0-9]+$ ]]; then
        set_kv "flexget_interval_sec" "$iv"
        ok "间隔已设为 ${iv}秒"
    fi
    
    # 3. 添加订阅
    echo ""
    read -rp "  是否现在添加订阅? [Y/n]: " s
    if [[ ! "$s" =~ ^[Nn] ]]; then
        flexget_add_sub
    fi
    
    echo ""
    read -rp "  立即重启服务生效? [Y/n]: " r
    if [[ ! "$r" =~ ^[Nn] ]]; then
        systemctl restart qbit-smart-limit && ok "服务已重启"
    fi
}

flexget_menu() {
    ensure_dirs
    flexget_regen_config
    while true; do
        show_banner; show_status
        echo -e "  ${C}━━━━━━━━━━━━━━━━ FlexGet 菜单 ━━━━━━━━━━━━━━━━${N}"
        echo -e "     ${G}1${N}. 一键配置向导 (推荐)    ${G}2${N}. 开关模块"
        echo -e "     ${G}3${N}. 添加订阅              ${G}4${N}. 删除订阅"
        echo -e "     ${G}5${N}. 查看订阅列表          ${G}6${N}. 修改抓取间隔"
        echo -e "     ${G}7${N}. 手动测试运行          ${G}8${N}. 查看日志"
        echo -e "     ${D}0${N}. 返回"
        echo ""
        read -rp "  选择: " c
        case "$c" in
            1) flexget_quick_setup; read -rp "按回车继续..." ;;
            2) 
                cur=$(get_bool "flexget_enabled")
                [[ "$cur" == "true" ]] && set_kv "flexget_enabled" "false" || set_kv "flexget_enabled" "true"
                systemctl restart qbit-smart-limit
                ok "状态已切换 (服务已重启)"
                sleep 1
                ;;
            3) flexget_add_sub ;;
            4) flexget_del_sub ;;
            5) flexget_list_subs; read -rp "按回车继续..." ;;
            6) 
                read -rp "  新间隔(秒): " v
                [[ "$v" =~ ^[0-9]+$ ]] && set_kv "flexget_interval_sec" "$v" && systemctl restart qbit-smart-limit && ok "已更新"
                ;;
            7) 
                echo "运行 FlexGet CLI..."
                flexget -c "$FLEXGET_CFG" execute
                read -rp "按回车继续..."
                ;;
            8) tail -n 20 "$FLEXGET_LOG"; read -rp "按回车继续..." ;;
            0) return ;;
        esac
    done
}

# ════════════════════════════════════════════════════════════
# AutoRemove 功能区
# ════════════════════════════════════════════════════════════
autorm_show_rules() {
    ensure_dirs
    echo -e "  ${C}当前删种策略:${N}"
    jq -r 'to_entries[] | "  \(.key+1). \(.value.name) [剩<\(.value.min_free_gb)G, 上传<\(.value.max_up_bps)B/s, 持续\(.value.min_low_sec)s]"' "$AUTORM_RULES" 2>/dev/null || echo "  暂无规则"
}

autorm_add_rule() {
    ensure_dirs
    echo ""
    echo -e "  ${Y}添加删种规则${N}"
    read -rp "  规则名称: " name
    read -rp "  最小剩余空间(GB) [10]: " free; free=${free:-10}
    read -rp "  最大上传速度(B/s) [102400]: " up; up=${up:-102400}
    read -rp "  持续低速时间(秒) [60]: " sec; sec=${sec:-60}
    read -rp "  是否要求必须完成(true/false) [false]: " comp; comp=${comp:-false}
    
    tmp="/tmp/qsl_autorm_$$.json"
    if jq --arg n "$name" --arg f "$free" --arg u "$up" --arg s "$sec" --arg c "$comp" \
       '. += [{"name":$n,"min_free_gb":($f|tonumber),"max_up_bps":($u|tonumber),"min_low_sec":($s|tonumber),"require_complete":($c|test("true"))}]' \
       "$AUTORM_RULES" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$AUTORM_RULES"
        ok "规则已添加"
    else rm -f "$tmp"; err "添加失败"; fi
}

autorm_del_rule() {
    autorm_show_rules
    echo ""
    read -rp "  输入序号删除: " n
    [[ ! "$n" =~ ^[0-9]+$ ]] && return
    tmp="/tmp/qsl_autorm_$$.json"
    if jq " del(.[$((n-1))]) " "$AUTORM_RULES" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$AUTORM_RULES"
        ok "已删除"
    else rm -f "$tmp"; err "删除失败"; fi
}

# 生成临时预览脚本
autorm_preview() {
    info "正在生成预览报告..."
    python3 - <<'PY'
import json, os, time
import qbittorrentapi
from pathlib import Path

# 配置路径
CFG = Path("/opt/qbit-smart-limit/config.json")
RULES = Path("/opt/qbit-smart-limit/autoremove/rules.json")

def fmt_size(b):
    for u in ['B','K','M','G']:
        if b<1024: return f"{b:.2f}{u}"
        b/=1024
    return f"{b:.2f}T"

try:
    cfg = json.loads(CFG.read_text())
    rules = json.loads(RULES.read_text())
    client = qbittorrentapi.Client(host=cfg['host'], username=cfg['username'], password=cfg['password'])
    client.auth_log_in()
    
    print(f"\n{'[待删除]':<10} {'[规则]':<20} {'[种子名称]'}")
    print("-" * 60)
    
    torrents = client.torrents_info()
    count = 0
    
    for t in torrents:
        try:
            st = os.statvfs(t.save_path)
            free = st.f_bavail * st.f_frsize
        except: free = 0
        
        for r in rules:
            min_free = float(r.get("min_free_gb",0)) * 1024**3
            max_up = int(r.get("max_up_bps",0))
            if min_free > 0 and free >= min_free: continue
            if r.get("require_complete") and t.progress < 0.999: continue
            
            if t.upspeed <= max_up:
                print(f"{'PREVIEW':<10} {r.get('name')[:20]:<20} {t.name[:40]}")
                count += 1
                break
    
    print("-" * 60)
    print(f"共发现 {count} 个符合删除条件的种子 (仅预览，未删除)")

except Exception as e:
    print(f"错误: {e}")
PY
    echo ""
    read -rp "按回车继续..."
}

# AutoRemove 一键配置
autorm_quick_setup() {
    echo ""
    echo -e "  ${W}>>> AutoRemove 一键配置向导 <<<${N}"
    echo ""
    
    # 1. 启用
    read -rp "  是否启用自动删种? [Y/n]: " c
    if [[ ! "$c" =~ ^[Nn] ]]; then
        set_kv "autoremove_enabled" "true"
        ok "模块已启用"
    else
        set_kv "autoremove_enabled" "false"
        warn "模块已禁用"
        return
    fi
    
    # 2. 间隔
    read -rp "  检查间隔(秒) [1800]: " iv
    iv=${iv:-1800}
    if [[ "$iv" =~ ^[0-9]+$ ]]; then
        set_kv "autoremove_interval_sec" "$iv"
        ok "间隔已设为 ${iv}秒"
    fi
    
    # 3. 写入默认规则
    echo ""
    info "正在检查规则..."
    cnt=$(jq 'length' "$AUTORM_RULES" 2>/dev/null || echo 0)
    if [[ "$cnt" -eq 0 ]]; then
        echo '[{"name":"Default Rule","min_free_gb":10,"max_up_bps":102400,"min_low_sec":60,"require_complete":false}]' > "$AUTORM_RULES"
        ok "已写入默认规则 (剩余空间<10G & 上传<100K)"
    else
        info "已有 ${cnt} 条规则，跳过默认写入"
    fi
    
    echo ""
    read -rp "  立即重启服务生效? [Y/n]: " r
    if [[ ! "$r" =~ ^[Nn] ]]; then
        systemctl restart qbit-smart-limit && ok "服务已重启"
    fi
}

autorm_menu() {
    ensure_dirs
    while true; do
        show_banner; show_status
        echo -e "  ${C}━━━━━━━━━━━━━━━ AutoRemove 菜单 ━━━━━━━━━━━━━━${N}"
        echo -e "     ${G}1${N}. 一键配置向导 (推荐)    ${G}2${N}. 开关模块"
        echo -e "     ${G}3${N}. 查看策略列表          ${G}4${N}. 添加删除策略"
        echo -e "     ${G}5${N}. 删除删除策略          ${G}6${N}. 修改检查间隔"
        echo -e "     ${G}7${N}. 模拟预览 (Dry Run)    ${G}8${N}. 查看日志"
        echo -e "     ${D}0${N}. 返回"
        echo ""
        read -rp "  选择: " c
        case "$c" in
            1) autorm_quick_setup; read -rp "按回车继续..." ;;
            2) 
                cur=$(get_bool "autoremove_enabled")
                [[ "$cur" == "true" ]] && set_kv "autoremove_enabled" "false" || set_kv "autoremove_enabled" "true"
                systemctl restart qbit-smart-limit
                ok "状态已切换 (服务已重启)"
                sleep 1
                ;;
            3) autorm_show_rules; read -rp "按回车继续..." ;;
            4) autorm_add_rule ;;
            5) autorm_del_rule ;;
            6) 
                read -rp "  新间隔(秒): " v
                [[ "$v" =~ ^[0-9]+$ ]] && set_kv "autoremove_interval_sec" "$v" && systemctl restart qbit-smart-limit && ok "已更新"
                ;;
            7) autorm_preview ;;
            8) tail -n 20 "$AUTORM_LOG"; read -rp "按回车继续..." ;;
            0) return ;;
        esac
    done
}

# ════════════════════════════════════════════════════════════
# 核心安装逻辑
# ════════════════════════════════════════════════════════════
do_install() {
    show_banner
    echo -e "  ${W}>>> 安装 qBit Smart Limit PRO <<<${N}"
    echo ""
    install_deps || return 1
    mkdir -p "$INSTALL_DIR"
    
    download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py" || return 1
    install_source_files || return 1
    
    # 简单的配置生成（如果不存在）
    if [[ ! -f "$CONFIG_FILE" ]]; then
        echo "{}" > "$CONFIG_FILE"
        # 使用 jq 初始化一个最小配置
        jq -n '{"log_level":"INFO"}' > "$CONFIG_FILE"
        chmod 600 "$CONFIG_FILE"
        ok "已生成空配置文件，请使用菜单配置"
    fi
    
    # 创建服务
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
    systemctl enable qbit-smart-limit &>/dev/null || true
    systemctl start qbit-smart-limit && ok "服务已启动"
    
    # 更新本地脚本
    download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "管理脚本" || true
    chmod +x "$SCRIPT_PATH"
    
    echo ""
    echo -e "  ${G}安装完成! 运行 qsl 打开菜单${N}"
}

do_update() {
    echo ""; echo -e "  ${W}>>> 检查更新 <<<${N}"
    local rv; rv=$(get_remote_ver)
    if [[ -z "$rv" ]]; then err "获取版本失败"; return; fi
    echo -e "  远程版本: ${C}$rv${N}"; echo -e "  本地版本: ${W}$(get_local_ver)${N}"
    read -rp "  确认更新? [y/N]: " c
    if [[ "$c" =~ ^[Yy] ]]; then
        download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py"
        install_source_files
        download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "管理脚本"
        systemctl restart qbit-smart-limit
        ok "更新完成"
    fi
}

do_uninstall() {
    echo ""; echo -e "  ${R}>>> 卸载 <<<${N}"
    read -rp "  确认卸载? [y/N]: " confirm
    [[ ! "$confirm" =~ ^[Yy] ]] && return
    systemctl stop qbit-smart-limit 2>/dev/null
    systemctl disable qbit-smart-limit 2>/dev/null
    rm -f "$SERVICE_FILE" "$SCRIPT_PATH"
    systemctl daemon-reload
    read -rp "  删除配置文件? [y/N]: " d
    [[ "$d" =~ ^[Yy] ]] && rm -rf "$INSTALL_DIR"
    ok "卸载完成"
}

# ════════════════════════════════════════════════════════════
# 主循环
# ════════════════════════════════════════════════════════════
init_env() {
    ensure_dirs
}

main() {
    if [[ $EUID -ne 0 ]]; then echo -e "${R}请使用 root 运行${N}"; exit 1; fi
    init_env
    while true; do
        show_banner; show_status; show_menu
        read -rp "  请选择: " choice
        case "$choice" in
            1) systemctl restart qbit-smart-limit && ok "服务已重启" ;;
            2) systemctl stop qbit-smart-limit && warn "服务已停止" ;;
            3) journalctl -u qbit-smart-limit -f ;;
            4) nano "$CONFIG_FILE" && systemctl restart qbit-smart-limit ;;
            5) flexget_menu ;;
            6) autorm_menu ;;
            8) do_update ;;
            9) do_uninstall ;;
            0) exit 0 ;;
            *) echo "无效选择" ;;
        esac
        echo ""; read -rp "  按回车继续..."
    done
}

main "$@"
