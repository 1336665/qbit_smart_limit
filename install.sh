#!/bin/bash
#
# qBit Smart Limit 管理脚本 v11.3.3 FINAL (Panel Interface)
# 适配: 通过 main.py --task 接口调用功能
#

# =========================================================
# ⚠️ 请修改此处为你的 GitHub 仓库地址 (RAW 链接)
GITHUB_RAW="https://raw.githubusercontent.com/1336665/qbit_smart_limit/main"
# =========================================================

# 基础路径配置
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
AUTORM_LOG="/var/log/qsl-autoremove.log"

# UI 颜色
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; C='\033[0;36m'; W='\033[1;37m'; D='\033[0;90m'; N='\033[0m'

# 0. 自检
if [[ ! -t 0 ]]; then
    echo ""; echo -e "  ${C}安装脚本...${N}"
    curl -sL "${GITHUB_RAW}/install.sh" -o "$SCRIPT_PATH" || wget -qO "$SCRIPT_PATH" "${GITHUB_RAW}/install.sh"
    chmod +x "$SCRIPT_PATH"
    echo -e "  ${G}✓${N} 安装成功，运行: ${G}qsl${N}"; echo ""; exit 0
fi

# 1. 基础函数
ok()   { echo -e "  ${G}✓${N} $1"; }
err()  { echo -e "  ${R}✗${N} $1"; }
warn() { echo -e "  ${Y}!${N} $1"; }
info() { echo -e "  ${C}i${N} $1"; }

ensure_env() {
    mkdir -p "$FLEXGET_DIR" "$AUTORM_DIR" "${INSTALL_DIR}/src" "/var/log" >/dev/null 2>&1 || true
    [[ -f "$FLEXGET_SUBS" ]] || echo '{"tasks":[]}' > "$FLEXGET_SUBS"
    [[ -f "$AUTORM_RULES" ]] || echo '[]' > "$AUTORM_RULES"
    [[ -f "$FLEXGET_CFG" ]] || touch "$FLEXGET_CFG"
}

get_bool() { jq -r ".$1 // false" "$CONFIG_FILE" 2>/dev/null; }
get_val() { jq -r ".$1 // \"$2\"" "$CONFIG_FILE" 2>/dev/null; }
set_kv() {
    local k="$1" v="$2"; tmp=$(mktemp)
    if [[ "$v" == "true" || "$v" == "false" ]]; then jq ".$k = $v" "$CONFIG_FILE" > "$tmp"; elif [[ "$v" =~ ^[0-9]+$ ]]; then jq ".$k = $v" "$CONFIG_FILE" > "$tmp"; else jq --arg val "$v" ".$k = \$val" "$CONFIG_FILE" > "$tmp"; fi
    mv "$tmp" "$CONFIG_FILE" && chmod 600 "$CONFIG_FILE"
}

get_remote_ver() { curl -sL --connect-timeout 5 "${GITHUB_RAW}/src/consts.py" 2>/dev/null | grep -oP 'VERSION = "\K[^"]+' | head -1; }
get_local_ver() { [[ -f "${INSTALL_DIR}/src/consts.py" ]] && grep -oP 'VERSION = "\K[^"]+' "${INSTALL_DIR}/src/consts.py" 2>/dev/null | head -1 || echo "-"; }

download() {
    local url="$1" dest="$2" name="$3" tmp="/tmp/qsl_dl_$$.tmp"
    echo -ne "  ${C}↓${N} 下载 ${name}..."
    local http_code
    if command -v curl >/dev/null; then http_code=$(curl -sL --connect-timeout 15 -w "%{http_code}" "$url" -o "$tmp" 2>/dev/null); else wget -qO "$tmp" "$url" && http_code="200" || http_code="000"; fi
    if [[ "$http_code" == "200" && -s "$tmp" ]]; then mv "$tmp" "$dest"; chmod +x "$dest" 2>/dev/null; echo -e "\r  ${G}✓${N} 下载 ${name}              "; return 0; fi
    rm -f "$tmp" 2>/dev/null; echo -e "\r  ${R}✗${N} 下载 ${name} (HTTP $http_code)   "; return 1
}

# 2. 界面
show_banner() {
    clear; echo ""; echo -e "${C}  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${N}"
    echo -e "${C}  ┃${N}         ${Y}qBit Smart Limit v11.3.3 PRO${N}                  ${C}┃${N}"
    echo -e "${C}  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${N}"; echo ""
}

show_status() {
    if systemctl is-active --quiet qbit-smart-limit; then serv_st="${G}● 运行中${N}"; else serv_st="${R}○ 已停止${N}"; fi
    if [[ -f "$CONFIG_FILE" ]]; then
        [[ $(get_bool "flexget_enabled") == "true" ]] && flex_st="${G}● 启用${N}" || flex_st="${R}○ 禁用${N}"
        [[ $(get_bool "autoremove_enabled") == "true" ]] && ar_st="${G}● 启用${N}" || ar_st="${R}○ 禁用${N}"
    else flex_st="${D}?${N}"; ar_st="${D}?${N}"; fi
    echo -e "  ${D}┌────────────────────────────────────────────────────────────────┐${N}"
    echo -e "  ${D}│${N}  ${W}服务状态${N}  $serv_st        ${W}FlexGet${N}   $flex_st               ${D}│${N}"
    echo -e "  ${D}│${N}  ${W}AutoRm${N}    $ar_st        ${W}配置${N}      ${G}config.json${N}          ${D}│${N}"
    echo -e "  ${D}└────────────────────────────────────────────────────────────────┘${N}"; echo ""
}

show_menu() {
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━━ 主菜单 ━━━━━━━━━━━━━━━━━━━━${N}"
    echo -e "     ${G}1${N}. 全新安装              ${G}2${N}. 修改配置"
    echo -e "     ${G}3${N}. 启动/重启             ${G}4${N}. 停止服务"
    echo -e "     ${G}5${N}. 查看日志              ${G}6${N}. 检查更新"
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━ 自动化模块 ━━━━━━━━━━━━━━━━━━${N}"
    echo -e "     ${Y}10${N}. FlexGet 自动抓种       ${Y}11${N}. AutoRemove 自动删种"
    echo -e "  ${C}━━━━━━━━━━━━━━━━━━━ 其他 ━━━━━━━━━━━━━━━━━━━━━━${N}"
    echo -e "     ${R}99${N}. 卸载程序             ${D}0${N}. 退出"; echo ""
}

# 3. FlexGet
flexget_regen_config() { python3 "$MAIN_PY" --task flexget_regen >/dev/null 2>&1; } # 留空，通过主程序或内联脚本生成
flexget_gen_inline() {
    python3 - <<'PY' >/dev/null 2>&1
import json,os; from pathlib import Path
CFG=Path("/opt/qbit-smart-limit/config.json"); SUBS=Path("/opt/qbit-smart-limit/flexget/subscriptions.json"); YML=Path("/opt/qbit-smart-limit/flexget/config.yml")
try: cfg=json.loads(CFG.read_text()); subs=json.loads(SUBS.read_text()).get("tasks",[])
except: subs=[]
tasks=[]
for t in subs:
    tasks.append(f"  {t['name']}:\n    rss: \"{t['rss']}\"\n    accept_all: yes\n    seen: local\n    qbittorrent:\n      host: \"{cfg.get('host','')}\"\n      username: \"{cfg.get('username','')}\"\n      password: \"{cfg.get('password','')}\"\n      category: \"{t.get('category','u2')}\"\n")
YML.write_text("tasks: {}\n" if not tasks else "tasks:\n"+"".join(tasks), encoding="utf-8")
PY
}

flexget_run_now() {
    echo ""; info "调用主程序运行 FlexGet..."
    # 核心修改：调用 main.py
    python3 "$MAIN_PY" --task flexget
    read -rp "按回车继续..."
}

flexget_add_sub() {
    echo ""; read -rp "  名称: " name; read -rp "  RSS: " rss; read -rp "  分类[u2]: " cat; cat=${cat:-u2}
    tmp=$(mktemp); jq --arg n "$name" --arg r "$rss" --arg c "$cat" '.tasks += [{"name":$n,"rss":$r,"category":$c,"tags":[]}]' "$FLEXGET_SUBS" > "$tmp" && mv "$tmp" "$FLEXGET_SUBS" && flexget_gen_inline && ok "已添加" || err "失败"
}

flexget_del_sub() {
    jq -r 'to_entries[]|"\(.key+1). \(.value.name)"' <(jq '.tasks' "$FLEXGET_SUBS"); read -rp "  序号: " n
    tmp=$(mktemp); jq " .tasks |= (del(.[$((n-1))])) " "$FLEXGET_SUBS" > "$tmp" && mv "$tmp" "$FLEXGET_SUBS" && flexget_gen_inline && ok "已删除" || err "失败"
}

flexget_menu() {
    ensure_env; flexget_gen_inline
    while true; do
        show_banner; show_status
        echo -e "  ${C}FlexGet 菜单${N}"
        echo -e "     1. 一键配置    2. 开关模块"
        echo -e "     3. 添加订阅    4. 删除订阅"
        echo -e "     5. 查看订阅    6. 修改间隔"
        echo -e "     7. 手动运行    8. 查看日志"
        echo -e "     0. 返回"
        echo ""; read -rp "  选择: " c
        case "$c" in
            1) set_kv "flexget_enabled" "true"; set_kv "flexget_interval_sec" "120"; flexget_add_sub; systemctl restart qbit-smart-limit; ok "已配置并重启" ;;
            2) cur=$(get_bool "flexget_enabled"); [[ "$cur" == "true" ]] && set_kv "flexget_enabled" "false" || set_kv "flexget_enabled" "true"; systemctl restart qbit-smart-limit; ok "切换成功" ;;
            3) flexget_add_sub ;;
            4) flexget_del_sub ;;
            5) echo ""; jq -r '.tasks[]|"  - \(.name) [\(.category)]"' "$FLEXGET_SUBS"; read -rp "..." ;;
            6) read -rp "  新间隔(s): " v; set_kv "flexget_interval_sec" "$v"; ok "已保存" ;;
            7) flexget_run_now ;;
            8) tail -n 20 "$FLEXGET_LOG"; read -rp "..." ;;
            0) return ;;
        esac
    done
}

# 4. AutoRemove
autorm_preview() {
    echo ""; info "调用主程序生成预览..."
    python3 "$MAIN_PY" --task autoremove_preview
    read -rp "按回车继续..."
}

autorm_menu() {
    ensure_env
    while true; do
        show_banner; show_status
        echo -e "  ${C}AutoRemove 菜单${N}"
        echo -e "     1. 一键配置    2. 开关模块"
        echo -e "     3. 查看策略    4. 添加策略"
        echo -e "     5. 删除策略    6. 修改间隔"
        echo -e "     7. 模拟预览    8. 查看日志"
        echo -e "     0. 返回"
        echo ""; read -rp "  选择: " c
        case "$c" in
            1) set_kv "autoremove_enabled" "true"; set_kv "autoremove_interval_sec" "1800"; 
               echo '[{"name":"<5G","min_free_gb":5,"max_up_bps":5242880,"min_low_sec":60,"require_complete":false},{"name":"<10G","min_free_gb":10,"max_up_bps":1048576,"min_low_sec":60,"require_complete":false},{"name":"<20G(Done)","min_free_gb":20,"max_up_bps":524288,"min_low_sec":60,"require_complete":true}]' > "$AUTORM_RULES";
               systemctl restart qbit-smart-limit; ok "已配置并重启" ;;
            2) cur=$(get_bool "autoremove_enabled"); [[ "$cur" == "true" ]] && set_kv "autoremove_enabled" "false" || set_kv "autoremove_enabled" "true"; systemctl restart qbit-smart-limit; ok "切换成功" ;;
            3) jq -r 'to_entries[]|"\(.key+1). \(.value.name)"' "$AUTORM_RULES"; read -rp "..." ;;
            4) read -rp "Name: " n; read -rp "Free(GB): " f; read -rp "Up(B/s): " u; tmp=$(mktemp); jq --arg n "$n" --arg f "$f" --arg u "$u" '.+=[{"name":$n,"min_free_gb":($f|tonumber),"max_up_bps":($u|tonumber),"min_low_sec":60,"require_complete":false}]' "$AUTORM_RULES" > "$tmp" && mv "$tmp" "$AUTORM_RULES" && ok "添加成功" ;;
            5) jq -r 'to_entries[]|"\(.key+1). \(.value.name)"' "$AUTORM_RULES"; read -rp "序号: " n; tmp=$(mktemp); jq "del(.[$((n-1))])" "$AUTORM_RULES" > "$tmp" && mv "$tmp" "$AUTORM_RULES" && ok "删除成功" ;;
            6) read -rp "  新间隔(s): " v; set_kv "autoremove_interval_sec" "$v"; ok "已保存" ;;
            7) autorm_preview ;;
            8) tail -n 20 "$AUTORM_LOG"; read -rp "..." ;;
            0) return ;;
        esac
    done
}

# 5. Core
install_deps() {
    echo ""; info "安装依赖..."
    if command -v apt-get &>/dev/null; then apt-get update -qq && apt-get install -y python3 python3-pip jq curl &>/dev/null; fi
    pip3 install --break-system-packages -q qbittorrent-api flexget requests beautifulsoup4 lxml || pip3 install -q qbittorrent-api flexget requests beautifulsoup4 lxml
}

install_source_files() {
    mkdir -p "${INSTALL_DIR}/src"
    local base="${GITHUB_RAW}/src"
    local files=("__init__.py" "consts.py" "utils.py" "config.py" "database.py" "model.py" "algorithms.py" "logic.py" "helper_web.py" "helper_bot.py" "workers.py" "controller.py")
    for f in "${files[@]}"; do download "${base}/${f}" "${INSTALL_DIR}/src/${f}" "src/${f}"; done
}

do_install() {
    install_deps; mkdir -p "$INSTALL_DIR"
    download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py"; install_source_files
    echo ""; read -rp "  WebUI: " h; read -rp "  User: " u; read -rsp "  Pass: " p; echo ""
    cat > "$CONFIG_FILE" <<EOF
{"host":"${h:-http://127.0.0.1:8080}","username":"${u:-admin}","password":"$(json_escape "$p")","target_speed_kib":51200,"safety_margin":0.98,"log_level":"INFO","flexget_enabled":false,"autoremove_enabled":false}
EOF
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
    download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "管理脚本" && chmod +x "$SCRIPT_PATH"
    ok "安装完成"
}

do_update() {
    download "${GITHUB_RAW}/main.py" "$MAIN_PY" "main.py"; install_source_files
    download "${GITHUB_RAW}/install.sh" "$SCRIPT_PATH" "管理脚本" && chmod +x "$SCRIPT_PATH"
    systemctl restart qbit-smart-limit && ok "更新完成"
}

main() {
    ensure_env
    while true; do
        show_banner; show_status; show_menu
        read -rp "  请选择: " choice
        case "$choice" in
            1) do_install ;;
            2) nano "$CONFIG_FILE" && systemctl restart qbit-smart-limit ;;
            3) systemctl restart qbit-smart-limit && ok "已重启" ;;
            4) systemctl stop qbit-smart-limit && warn "已停止" ;;
            5) journalctl -u qbit-smart-limit -f ;;
            6) do_update ;;
            10) flexget_menu ;;
            11) autorm_menu ;;
            99) systemctl disable --now qbit-smart-limit; rm -rf "$INSTALL_DIR" "$SERVICE_FILE" "$SCRIPT_PATH"; ok "卸载完成"; exit ;;
            0) exit 0 ;;
        esac
    done
}

main "$@"
