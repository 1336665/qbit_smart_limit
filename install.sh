#!/bin/bash
#
# qBit Smart Limit 管理脚本 v11.3.5 FINAL FIX
# 修复: FlexGet 调用方式 (Inline Python) | 确保常量一致性
#

# =========================================================
# ⚠️ 请修改此处为你的 GitHub 仓库地址 (RAW 链接)
GITHUB_RAW="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main"
# =========================================================

# 0. 强制环境变量
export PATH=$PATH:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin:$HOME/.local/bin

# 路径配置
INSTALL_DIR="/opt/qbit-smart-limit"
CONFIG_FILE="${INSTALL_DIR}/config.json"
SERVICE_FILE="/etc/systemd/system/qbit-smart-limit.service"
SCRIPT_PATH="/usr/local/bin/qsl"
MAIN_PY="${INSTALL_DIR}/main.py"

# 子模块路径
FLEXGET_DIR="${INSTALL_DIR}/flexget"
AUTORM_DIR="${INSTALL_DIR}/autoremove"
FLEXGET_CFG="${FLEXGET_DIR}/config.yml"
FLEXGET_SUBS="${FLEXGET_DIR}/subscriptions.json"
FLEXGET_LOG="/var/log/qsl-flexget.log"
AUTORM_RULES="${AUTORM_DIR}/rules.json"
AUTORM_STATE="${AUTORM_DIR}/state.json"
AUTORM_LOG="/var/log/qsl-autoremove.log"

# UI 颜色
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; C='\033[0;36m'; W='\033[1;37m'; D='\033[0;90m'; N='\033[0m'

# ════════════════════════════════════════════════════════════
# 1. 自检与基础函数
# ════════════════════════════════════════════════════════════
if [[ ! -t 0 ]]; then
    echo ""; echo -e "  ${C}安装脚本...${N}"
    if command -v curl >/dev/null; then curl -sL "${GITHUB_RAW}/install.sh" -o "$SCRIPT_PATH"; else wget -qO "$SCRIPT_PATH" "${GITHUB_RAW}/install.sh"; fi
    chmod +x "$SCRIPT_PATH"
    echo -e "  ${G}✓${N} 安装成功，请运行: ${G}qsl${N}"; echo ""
    exit 0
fi

ok()   { echo -e "  ${G}✓${N} $1"; }
err()  { echo -e "  ${R}✗${N} $1"; }
warn() { echo -e "  ${Y}!${N} $1"; }
info() { echo -e "  ${C}i${N} $1"; }

ensure_env() {
    mkdir -p "$FLEXGET_DIR" "$AUTORM_DIR" "${INSTALL_DIR}/src" "/var/log" >/dev/null 2>&1 || true
    [[ -f "$FLEXGET_SUBS" ]] || echo '{"tasks":[]}' > "$FLEXGET_SUBS"
    [[ -f "$AUTORM_RULES" ]] || echo '[]' > "$AUTORM_RULES"
    [[ -f "$FLEXGET_CFG" ]] || touch "$FLEXGET_CFG"
    # 强制创建日志，防止 tail 报错
    touch "$FLEXGET_LOG" "$AUTORM_LOG"
    chmod 666 "$FLEXGET_LOG" "$AUTORM_LOG" 2>/dev/null || true
}

get_bool() { jq -r ".$1 // false" "$CONFIG_FILE" 2>/dev/null; }
get_val() { jq -r ".$1 // \"$2\"" "$CONFIG_FILE" 2>/dev/null; }
set_kv() {
    local k="$1" v="$2"
    tmp=$(mktemp)
    if [[ "$v" == "true" || "$v" == "false" ]]; then jq ".$k = $v" "$CONFIG_FILE" > "$tmp"; elif [[ "$v" =~ ^[0-9]+$ ]]; then jq ".$k = $v" "$CONFIG_FILE" > "$tmp"; else jq --arg val "$v" ".$k = \$val" "$CONFIG_FILE" > "$tmp"; fi
    mv "$tmp" "$CONFIG_FILE" && chmod 600 "$CONFIG_FILE"
}

get_remote_ver() { curl -sL --connect-timeout 5 "${GITHUB_RAW}/src/consts.py" 2>/dev/null | grep -oP 'VERSION = "\K[^"]+' | head -1; }
get_local_ver() { [[ -f "${INSTALL_DIR}/src/consts.py" ]] && grep -oP 'VERSION = "\K[^"]+' "${INSTALL_DIR}/src/consts.py" 2>/dev/null | head -1 || echo "-"; }

download() {
    local url="$1" dest="$2" name="$3"
    local tmp="/tmp/qsl_dl_$$.tmp"
    echo -ne "  ${C}↓${N} 下载 ${name}..."
    local http_code
    if command -v curl >/dev/null; then http_code=$(curl -sL --connect-timeout 15 -w "%{http_code}" "$url" -o "$tmp" 2>/dev/null); else wget -qO "$tmp" "$url" && http_code="200" || http_code="000"; fi
    if [[ "$http_code" == "200" && -s "$tmp" ]]; then
        mv "$tmp" "$dest"; [[ "$dest" == *.sh || "$dest" == *.py || "$dest" == *"/bin/qsl" ]] && chmod +x "$dest"
        echo -e "\r  ${G}✓${N} 下载 ${name}              "; return 0
    fi
    rm -f "$tmp" 2>/dev/null; echo -e "\r  ${R}✗${N} 下载 ${name} (HTTP $http_code)   "; return 1
}

# ════════════════════════════════════════════════════════════
# 2. 界面显示
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
    echo -e "${C}  ┃${N}         ${Y}qBit Smart Limit v${SCRIPT_VER:-11.3.5} PRO${N}            ${C}┃${N}"
    echo -e "${C}  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${N}"
    echo ""
}

show_status() {
    if systemctl is-active --quiet qbit-smart-limit; then serv_st="${G}● 运行中${N}"; else serv_st="${R}○ 已停止${N}"; fi
    if [[ -f "$CONFIG_FILE" ]]; then
        [[ $(get_bool "enable_dl_limit") == "true" ]] && dl_st="${G}● 启用${N}" || dl_st="${R}○ 禁用${N}"
        [[ $(get_bool "enable_reannounce_opt") == "true" ]] && ra_st="${G}● 启用${N}" || ra_st="${R}○ 禁用${N}"
        [[ -n $(get_val "u2_cookie" "") ]] && u2_st="${G}● 配置${N}" || u2_st="${D}○ 空缺${N}"
        [[ $(get_bool "flexget_enabled") == "true" ]] && flex_st="${G}● 启用${N}" || flex_st="${R}○ 禁用${N}"
        [[ $(get_bool "autoremove_enabled") == "true" ]] && ar_st="${G}● 启用${N}" || ar_st="${R}○ 禁用${N}"
    else
        dl_st="${D}?${N}"; ra_st="${D}?${N}"; u2_st="${D}?${N}"; flex_st="${D}?${N}"; ar_st="${D}?${N}"
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
    echo -e "     ${G}1${N}. 全新安装              ${G}2${N}. 修改配置"
    echo -e "     ${G}3${N}. 启动/重启服务         ${G}4${N}. 停止服务"
    echo -e "     ${G}5${N}. 查看日志              ${G}6${N}. 检查更新"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━ 自动化模块 ━━━━━━━━━━━━━━━━━━${N}"
    echo -e "     ${Y}10${N}. FlexGet 自动抓种       ${Y}11${N}. AutoRemove 自动删种"
    echo ""
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━ 其他 ━━━━━━━━━━━━━━━━━━━━━━${N}"
    echo -e "     ${R}99${N}. 卸载程序             ${D}0${N}. 退出"
    echo ""
}

# ════════════════════════════════════════════════════════════
# 3. FlexGet 逻辑 (Python Code Call)
# ════════════════════════════════════════════════════════════
flexget_regen_config() {
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
    name=(t.get("name") or "").strip(); rss=(t.get("rss") or "").strip()
    cat=(t.get("category") or "u2").strip(); tags=t.get("tags") or []
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
YML.write_text("tasks: {}\n" if not tasks else "tasks:\n"+"".join(tasks), encoding="utf-8")
PY
}

flexget_run_now() {
    echo ""; info "准备运行 FlexGet (Import Mode)..."
    
    # 强制检查依赖
    if ! python3 -c "import flexget" &>/dev/null; then
        warn "FlexGet 模块缺失，尝试安装..."
        pip3 install --break-system-packages -q flexget 2>/dev/null || pip3 install -q flexget
    fi

    # 核心修复：直接用 Python 代码导入并运行，彻底解决 No module __main__ 错误
    python3 -c "import sys; from flexget import main; sys.argv=['flexget', '-c', '$FLEXGET_CFG', '--logfile', '$FLEXGET_LOG', 'execute']; main()"
    
    echo ""; ok "执行完毕"; read -rp "按回车继续..."
}

flexget_add_sub() {
    echo ""; read -rp "  名称: " name; read -rp "  RSS: " rss; read -rp "  分类[u2]: " cat; cat=${cat:-u2}
    tmp=$(mktemp); jq --arg n "$name" --arg r "$rss" --arg c "$cat" '.tasks += [{"name":$n,"rss":$r,"category":$c,"tags":[]}]' "$FLEXGET_SUBS" > "$tmp" && mv "$tmp" "$FLEXGET_SUBS" && flexget_regen_config && ok "已添加" || err "失败"
}

flexget_del_sub() {
    jq -r 'to_entries[]|"\(.key+1). \(.value.name)"' <(jq '.tasks' "$FLEXGET_SUBS"); read -rp "  序号: " n
    tmp=$(mktemp); jq " .tasks |= (del(.[$((n-1))])) " "$FLEXGET_SUBS" > "$tmp" && mv "$tmp" "$FLEXGET_SUBS" && flexget_regen_config && ok "已删除" || err "失败"
}

flexget_quick_setup() {
    echo ""; echo -e "  ${W}>>> FlexGet 一键配置向导 <<<${N}"; echo ""
    read -rp "  1. 启用 FlexGet? [Y/n]: " c
    if [[ ! "$c" =~ ^[Nn] ]]; then set_kv "flexget_enabled" "true"; ok "已启用"; else set_kv "flexget_enabled" "false"; warn "已禁用"; return; fi
    read -rp "  2. 抓取间隔(秒) [120]: " iv; iv=${iv:-120}
    [[ "$iv" =~ ^[0-9]+$ ]] && set_kv "flexget_interval_sec" "$iv" && ok "间隔: ${iv}s"
    echo ""; read -rp "  3. 添加订阅? [Y/n]: " s
    [[ ! "$s" =~ ^[Nn] ]] && flexget_add_sub
    echo ""; read -rp "  立即重启服务生效? [Y/n]: " r
    [[ ! "$r" =~ ^[Nn] ]] && systemctl restart qbit-smart-limit && ok "服务已重启"
}

flexget_menu() {
    ensure_env; flexget_regen_config
    while true; do
        show_banner; show_status
        echo -e "  ${C}━━━━━━━━━━━━━━━━ FlexGet 菜单 ━━━━━━━━━━━━━━━━${N}"
        echo -e "     ${G}1${N}. 一键配置向导 (推 荐)    ${G}2${N}. 开关模块"
        echo -e "     ${G}3${N}. 添加订阅              ${G}4${N}. 删除订阅"
        echo -e "     ${G}5${N}. 查看订阅列表          ${G}6${N}. 修改抓取间隔"
        echo -e "     ${G}7${N}. 手动测试运行          ${G}8${N}. 查看日志"
        echo -e "     ${D}0${N}. 返回"
        echo ""; read -rp "  选择: " c
        case "$c" in
            1) flexget_quick_setup; read -rp "按回车..." ;;
            2) cur=$(get_bool "flexget_enabled"); [[ "$cur" == "true" ]] && set_kv "flexget_enabled" "false" || set_kv "flexget_enabled" "true"; systemctl restart qbit-smart-limit; ok "状态已切换"; sleep 1 ;;
            3) flexget_add_sub ;;
            4) flexget_del_sub ;;
            5) echo ""; jq -r '.tasks[]|"  - \(.name) [\(.category)]"' "$FLEXGET_SUBS"; read -rp "..." ;;
            6) read -rp "  新间隔(秒): " v; [[ "$v" =~ ^[0-9]+$ ]] && set_kv "flexget_interval_sec" "$v" && systemctl restart qbit-smart-limit && ok "已更新" ;;
            7) flexget_run_now ;;
            8) tail -n 20 "$FLEXGET_LOG"; read -rp "..." ;;
            0) return ;;
        esac
    done
}

# ════════════════════════════════════════════════════════════
# 4. AutoRemove 逻辑 (含定制规则)
# ════════════════════════════════════════════════════════════
autorm_preview() {
    info "正在生成预览报告 (Dry Run)..."
    python3 - <<'PY'
import json, os, qbittorrentapi
from pathlib import Path
CFG=Path("/opt/qbit-smart-limit/config.json"); RULES=Path("/opt/qbit-smart-limit/autoremove/rules.json")
def fmt(b):
    for u in ['B','K','M','G']:
        if b<1024: return f"{b:.2f}{u}"; b/=1024
    return f"{b:.2f}T"
try:
    cfg=json.loads(CFG.read_text()); rules=json.loads(RULES.read_text())
    qb=qbittorrentapi.Client(host=cfg['host'], username=cfg['username'], password=cfg['password']); qb.auth_log_in()
    print(f"\n{'[待删除]':<10} {'[规则]':<20} {'[种子名称]'}")
    print("-" * 60); count=0
    for t in qb.torrents_info():
        try: st=os.statvfs(t.save_path); free=st.f_bavail*st.f_frsize
        except: free=0
        for r in rules:
            mf=float(r.get("min_free_gb",0))*1024**3; mu=int(r.get("max_up_bps",0))
            if mf>0 and free>=mf: continue
            if r.get("require_complete") and t.progress<0.999: continue
            if t.upspeed<=mu:
                print(f"{'PREVIEW':<10} {r.get('name')[:20]:<20} {t.name[:40]}")
                count+=1; break
    print("-" * 60); print(f"共发现 {count} 个符合条件的种子")
except Exception as e: print(f"错误: {e}")
PY
    echo ""; read -rp "按回车继续..."
}

autorm_quick_setup() {
    echo ""; echo -e "  ${W}>>> AutoRemove 一键配置向导 <<<${N}"; echo ""
    read -rp "  1. 启用自动删种? [Y/n]: " c
    if [[ ! "$c" =~ ^[Nn] ]]; then set_kv "autoremove_enabled" "true"; ok "已启用"; else set_kv "autoremove_enabled" "false"; warn "已禁用"; return; fi
    read -rp "  2. 检查间隔(秒) [1800]: " iv; iv=${iv:-1800}
    [[ "$iv" =~ ^[0-9]+$ ]] && set_kv "autoremove_interval_sec" "$iv" && ok "间隔: ${iv}s"
    
    echo ""; info "写入默认删种规则 (5G/10G/20G)..."
    cat > "$AUTORM_RULES" <<EOF
[
  {"name":"空间极危 (<5G)","min_free_gb":5,"max_up_bps":5242880,"min_low_sec":60,"require_complete":false},
  {"name":"空间紧张 (<10G)","min_free_gb":10,"max_up_bps":1048576,"min_low_sec":60,"require_complete":false},
  {"name":"完种清理 (<20G)","min_free_gb":20,"max_up_bps":524288,"min_low_sec":60,"require_complete":true}
]
EOF
    ok "规则已写入"; echo ""
    read -rp "  立即重启服务生效? [Y/n]: " r
    [[ ! "$r" =~ ^[Nn] ]] && systemctl restart qbit-smart-limit && ok "服务已重启"
}

autorm_add_rule() {
    echo ""; read -rp "名称: " n; read -rp "最小剩余(GB): " f; read -rp "最大上传(B/s): " u
    tmp=$(mktemp); jq --arg n "$n" --arg f "$f" --arg u "$u" '.+=[{"name":$n,"min_free_gb":($f|tonumber),"max_up_bps":($u|tonumber),"min_low_sec":60,"require_complete":false}]' "$AUTORM_RULES" > "$tmp" && mv "$tmp" "$AUTORM_RULES" && ok "已添加" || err "失败"
}

autorm_del_rule() {
    jq -r 'to_entries[]|"\(.key+1). \(.value.name)"' "$AUTORM_RULES"; read -rp "序号: " n
    tmp=$(mktemp); jq "del(.[$((n-1))])" "$AUTORM_RULES" > "$tmp" && mv "$tmp" "$AUTORM_RULES" && ok "已删除" || err "失败"
}

autorm_menu() {
    ensure_env
    while true; do
        show_banner; show_status
        echo -e "  ${C}━━━━━━━━━━━━━━━ AutoRemove 菜单 ━━━━━━━━━━━━━━${N}"
        echo -e "     ${G}1${N}. 一键配置向导 (推 荐)    ${G}2${N}. 开关模块"
        echo -e "     ${G}3${N}. 查看策略列表          ${G}4${N}. 添加删除策略"
        echo -e "     ${G}5${N}. 删除删除策略          ${G}6${N}. 修改检查间隔"
        echo -e "     ${G}7${N}. 模拟预览 (Dry Run)    ${G}8${N}. 查看日志"
        echo -e "     ${D}0${N}. 返回"
        echo ""; read -rp "  选择: " c
        case "$c" in
            1) autorm_quick_setup; read -rp "按回车..." ;;
            2) cur=$(get_bool "autoremove_enabled"); [[ "$cur" == "true" ]] && set_kv "autoremove_enabled" "false" || set_kv "autoremove_enabled" "true"; systemctl restart qbit-smart-limit; ok "状态已切换"; sleep 1 ;;
            3) jq -r 'to_entries[]|"\(.key+1). \(.value.name) [剩<\(.value.min_free_gb)G, 上传<\(.value.max_up_bps)B/s]"' "$AUTORM_RULES"; read -rp "..." ;;
            4) autorm_add_rule ;;
            5) autorm_del_rule ;;
            6) read -rp "  新间隔(秒): " v; [[ "$v" =~ ^[0-9]+$ ]] && set_kv "autoremove_interval_sec" "$v" && systemctl restart qbit-smart-limit && ok "已更新" ;;
            7) autorm_preview ;;
            8) tail -n 20 "$AUTORM_LOG"; read -rp "..." ;;
            0) return ;;
        esac
    done
}

# ════════════════════════════════════════════════════════════
# 5. 安装与更新逻辑
# ════════════════════════════════════════════════════════════
install_deps() {
    echo ""; info "安装系统依赖..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq &>/dev/null || true
        apt-get install -y python3 python3-pip jq curl python3-requests python3-bs4 python3-lxml -qq &>/dev/null || true
    elif command -v yum &>/dev/null; then
        yum install -y python3 python3-pip jq curl -q &>/dev/null || true
    fi
    ok "系统依赖安装完成"
    
    info "安装 Python 依赖 (含 FlexGet)..."
    python3 -m pip install --break-system-packages -q qbittorrent-api flexget requests beautifulsoup4 lxml 2>/dev/null || python3 -m pip install -q qbittorrent-api flexget requests beautifulsoup4 lxml
    ok "Python 依赖安装完成"
}

install_source_files() {
    mkdir -p "${INSTALL_DIR}/src"
    local base="${GITHUB_RAW}/src"
    local files=("__init__.py" "consts.py" "utils.py" "config.py" "database.py" "model.py" "algorithms.py" "logic.py" "helper_web.py" "helper_bot.py" "workers.py" "controller.py")
    for f in "${files[@]}"; do
        download "${base}/${f}" "${INSTALL_DIR}/src/${f}" "src/${f}" || return 1
    done
}

get_input() {
    echo ""; echo -e "  ${C}━━━━━━━━━━━━━━ qBittorrent 设置 ━━━━━━━━━━━━━━━${N}"
    read -rp "  WebUI 地址 [http://127.0.0.1:8080]: " h; h=${h:-"http://127.0.0.1:8080"}
    read -rp "  用户名 [admin]: " u; u=${u:-"admin"}
    read -rsp "  密码: " p; echo ""
    [[ -z "$p" ]] && { err "密码不能为空"; return 1; }
    
    # 写入初始配置
    cat > "$CONFIG_FILE" <<EOF
{
  "host": "$h", "username": "$u", "password": "$(json_escape "$p")",
  "target_speed_kib": 51200, "safety_margin": 0.98, "log_level": "INFO",
  "telegram_bot_token": "", "telegram_chat_id": "", "u2_cookie": "",
  "flexget_enabled": false, "flexget_interval_sec": 120,
  "autoremove_enabled": false, "autoremove_interval_sec": 1800
}
EOF
    chmod 600 "$CONFIG_FILE"
}

create_service_file() {
    cat > "$SERVICE_FILE" << EOF
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
    systemctl enable qbit-smart-limit &>/dev/null || true
}

do_install() {
    show_banner
    echo -e "  ${W}>>> 安装 qBit Smart Limit PRO <<<${N}"; echo ""
    install_deps; mkdir -p "$INSTALL_DIR"
    
    download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py" || return 1
    install_source_files || return 1
    
    get_input; create_service_file; ensure_env
    systemctl start qbit-smart-limit && ok "服务已启动"
    
    download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "管理脚本" || true
    chmod +x "$SCRIPT_PATH"
    echo ""; echo -e "  ${G}安装完成! 运行 qsl 打开菜单${N}"
}

do_update() {
    echo ""; echo -e "  ${W}>>> 检查更新 <<<${N}"
    local rv; rv=$(get_remote_ver)
    if [[ -z "$rv" ]]; then err "获取版本失败 (网络错误?)"; return; fi
    echo -e "  远程版本: ${C}$rv${N}"; echo -e "  本地版本: ${W}$(get_local_ver)${N}"
    
    read -rp "  确认更新? [y/N]: " c
    if [[ "$c" =~ ^[Yy] ]]; then
        download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py"
        install_source_files
        download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "管理脚本"
        chmod +x "$SCRIPT_PATH"
        
        # 智能修复服务
        if [[ ! -f "$SERVICE_FILE" ]]; then create_service_file; fi
        
        systemctl restart qbit-smart-limit && ok "更新完成" || err "服务启动失败"
    fi
}

do_uninstall() {
    echo ""; read -rp "  确认卸载? [y/N]: " confirm
    [[ ! "$confirm" =~ ^[Yy] ]] && return
    systemctl disable --now qbit-smart-limit 2>/dev/null
    rm -f "$SERVICE_FILE" "$SCRIPT_PATH"
    systemctl daemon-reload
    read -rp "  删除配置文件? [y/N]: " d
    [[ "$d" =~ ^[Yy] ]] && rm -rf "$INSTALL_DIR"
    ok "卸载完成"
}

# ════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════
main() {
    if [[ $EUID -ne 0 ]]; then echo -e "${R}请使用 root 运行${N}"; exit 1; fi
    ensure_env
    while true; do
        show_banner; show_status; show_menu
        read -rp "  请选择: " choice
        case "$choice" in
            1) do_install ;;
            2) nano "$CONFIG_FILE" && systemctl restart qbit-smart-limit && ok "重启生效" ;;
            3) systemctl restart qbit-smart-limit && ok "已重启" ;;
            4) systemctl stop qbit-smart-limit && warn "已停止" ;;
            5) journalctl -u qbit-smart-limit -f ;;
            6) do_update ;;
            10) flexget_menu ;;
            11) autorm_menu ;;
            99) do_uninstall ;;
            0) exit 0 ;;
            *) echo "无效选择" ;;
        esac
        echo ""; read -rp "  按回车继续..."
    done
}

main "$@"
