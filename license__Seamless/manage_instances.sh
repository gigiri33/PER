#!/bin/bash
set -Eeuo pipefail

# ═══════════════════════════════════════════════════════════════
# Seamless License Bot — Instance Manager
# Manages all bot instances deployed by the license bot
# ═══════════════════════════════════════════════════════════════

BASE_DIR="/opt/license-bots"
LICENSE_DIR="/opt/seamless-license"
LICENSE_SERVICE="seamless-license"
LICENSE_REPO="https://github.com/gigiri33/PER.git"
LICENSE_BRANCH="main"
LICENSE_SUBDIR="license__Seamless"

R='\033[31m'; G='\033[32m'; Y='\033[33m'; C='\033[36m'; M='\033[35m'; B='\033[1m'; W='\033[97m'; N='\033[0m'

err()  { echo -e "${R}✗ $*${N}" >&2; }
ok()   { echo -e "${G}✓ $*${N}"; }
info() { echo -e "${Y}➜ $*${N}"; }

ensure_safe_cwd() { cd / 2>/dev/null || true; }

install_prereqs() {
  info "Installing prerequisites..."
  apt-get update -y
  apt-get install -y git python3 python3-venv python3-pip curl sqlite3
}

check_root() {
  [[ $EUID -eq 0 ]] || { err "Please run with sudo or as root"; exit 1; }
}

header() {
  clear 2>/dev/null || true
  echo ""
  echo -e "${C}╔══════════════════════════════════════════════════════════════════════════╗${N}"
  echo -e "${C}║${N}          ${W}${B}🖥 Seamless Instance Manager${N}                                   ${C}║${N}"
  echo -e "${C}╚══════════════════════════════════════════════════════════════════════════╝${N}"
  echo ""
}

# ── List all instances ────────────────────────────────────────────────────────

list_instances() {
  local found=0
  echo -e "${C}┌────┬──────────────┬────────────────────────┬────────────┬───────────────────────────────────────┐${N}"
  echo -e "${C}│${N} ${B}# ${N} ${C}│${N} ${B}Project${N}      ${C}│${N} ${B}Bot Username${N}            ${C}│${N} ${B}Status${N}     ${C}│${N} ${B}Directory${N}                             ${C}│${N}"
  echo -e "${C}├────┼──────────────┼────────────────────────┼────────────┼───────────────────────────────────────┤${N}"

  local idx=0
  for d in "$BASE_DIR"/*/; do
    [[ -d "$d" ]] || continue
    local name; name="$(basename "$d")"
    [[ "$name" == ".repos" ]] && continue

    idx=$((idx + 1))
    local parts; IFS='_' read -r project bot_id <<< "$name"
    local token="" username=""

    if [[ -f "$d/.env" ]]; then
      token=$(grep "^BOT_TOKEN=" "$d/.env" 2>/dev/null | cut -d= -f2- || true)
    fi

    # Try to get bot username from .bot_name or directory name
    username="$name"

    local svc="licbot-${project}-${bot_id}"
    local status_str
    if systemctl is-active "$svc" >/dev/null 2>&1; then
      status_str="${G}🟢 Online ${N}"
    else
      status_str="${R}🔴 Offline${N}"
    fi

    printf "${C}│${N} %-2s ${C}│${N} %-12s ${C}│${N} %-22s ${C}│${N} " "$idx" "$project" "$name"
    echo -ne "$status_str"
    printf " ${C}│${N} %-37s ${C}│${N}\n" "$d"
    found=1
  done

  if [[ $found -eq 0 ]]; then
    echo -e "${C}│${N}              ${Y}No instances deployed${N}                                                            ${C}│${N}"
  fi
  echo -e "${C}└────┴──────────────┴────────────────────────┴────────────┴───────────────────────────────────────┘${N}"
  echo ""
}

# ── Get instance info by index ────────────────────────────────────────────────

get_instance_by_idx() {
  local target_idx="$1"
  local idx=0
  for d in "$BASE_DIR"/*/; do
    [[ -d "$d" ]] || continue
    local name; name="$(basename "$d")"
    [[ "$name" == ".repos" ]] && continue
    idx=$((idx + 1))
    if [[ $idx -eq $target_idx ]]; then
      echo "$d"
      return 0
    fi
  done
  return 1
}

get_svc_from_dir() {
  local d="$1"
  local name; name="$(basename "$d")"
  local parts; IFS='_' read -r project bot_id <<< "$name"
  echo "licbot-${project}-${bot_id}"
}

# ── Actions ───────────────────────────────────────────────────────────────────

do_start() {
  local d="$1"
  local svc; svc="$(get_svc_from_dir "$d")"
  systemctl start "$svc" 2>/dev/null && ok "Started: $(basename "$d")" || err "Failed to start: $(basename "$d")"
}

do_stop() {
  local d="$1"
  local svc; svc="$(get_svc_from_dir "$d")"
  systemctl stop "$svc" 2>/dev/null && ok "Stopped: $(basename "$d")" || err "Failed to stop: $(basename "$d")"
}

do_restart() {
  local d="$1"
  local svc; svc="$(get_svc_from_dir "$d")"
  systemctl restart "$svc" 2>/dev/null && ok "Restarted: $(basename "$d")" || err "Failed to restart: $(basename "$d")"
}

do_status() {
  local d="$1"
  local svc; svc="$(get_svc_from_dir "$d")"
  systemctl status "$svc" --no-pager -l || true
}

do_log() {
  local d="$1"
  local svc; svc="$(get_svc_from_dir "$d")"
  echo -e "${Y}Press Ctrl+C to exit log${N}"
  sleep 1
  journalctl -u "$svc" -f
}

do_edit_env() {
  local d="$1"
  [[ -f "$d/.env" ]] || { err "No .env file found in $d"; return; }
  nano "$d/.env"
  local svc; svc="$(get_svc_from_dir "$d")"
  systemctl restart "$svc" 2>/dev/null
  ok "Configuration saved and instance restarted."
}

do_update() {
  local d="$1"
  local name; name="$(basename "$d")"
  local parts; IFS='_' read -r project bot_id <<< "$name"

  info "Updating $name..."

  # Update repo cache
  local cache_dir="$BASE_DIR/.repos/$project"
  local repo_url
  if [[ "$project" == "seamless" ]]; then
    repo_url="https://github.com/gigiri33/PER.git"
  else
    repo_url="https://github.com/Emadhabibnia1385/ConfigFlow.git"
  fi

  if [[ -d "$cache_dir/.git" ]]; then
    cd "$cache_dir"
    git fetch --all --prune 2>/dev/null
    git reset --hard origin/main 2>/dev/null
  else
    rm -rf "$cache_dir"
    mkdir -p "$cache_dir"
    git clone --depth 1 "$repo_url" "$cache_dir"
  fi

  # Backup .env
  local env_backup=""
  [[ -f "$d/.env" ]] && env_backup="$(cat "$d/.env")"

  # Remove old code, keep venv/.db/.env
  for item in "$d"/*; do
    local bn; bn="$(basename "$item")"
    [[ "$bn" == "venv" ]] && continue
    [[ "$bn" == *.db ]] && continue
    [[ "$bn" == ".env" ]] && continue
    rm -rf "$item"
  done

  # Copy new code
  for item in "$cache_dir"/*; do
    local bn; bn="$(basename "$item")"
    [[ "$bn" == ".git" ]] && continue
    [[ "$bn" == "venv" ]] && continue
    [[ "$bn" == "license__Seamless" ]] && continue
    [[ "$bn" == "install.sh" ]] && continue
    [[ "$bn" == "README.md" ]] && continue
    [[ "$bn" == "LICENSE" ]] && continue
    cp -r "$item" "$d/"
  done

  # Restore .env
  [[ -n "$env_backup" ]] && echo "$env_backup" > "$d/.env"

  # Update pip deps
  "$d/venv/bin/pip" install -r "$d/requirements.txt" -q 2>/dev/null

  # Restart
  local svc; svc="$(get_svc_from_dir "$d")"
  systemctl restart "$svc" 2>/dev/null
  ok "$name updated and restarted!"
}

do_remove() {
  local d="$1"
  local name; name="$(basename "$d")"
  local svc; svc="$(get_svc_from_dir "$d")"

  read -r -p "Are you sure you want to remove $name? (yes/no): " confirm
  [[ "$confirm" == "yes" ]] || { info "Cancelled"; return; }

  systemctl stop "$svc" 2>/dev/null || true
  systemctl disable "$svc" 2>/dev/null || true
  rm -f "/etc/systemd/system/${svc}.service"
  systemctl daemon-reload
  rm -rf "$d"
  ok "$name completely removed."
}

do_delete_license() {
  local d="$1"
  local name; name="$(basename "$d")"

  # Read bot token from instance .env
  local token=""
  [[ -f "$d/.env" ]] && token=$(grep "^BOT_TOKEN=" "$d/.env" 2>/dev/null | cut -d= -f2- || true)
  if [[ -z "$token" ]]; then
    err "Cannot read BOT_TOKEN from $d/.env"
    return 1
  fi

  # Find license DB path
  local db_name="license.db"
  [[ -f "$LICENSE_DIR/.env" ]] && {
    local n; n=$(grep "^DB_NAME=" "$LICENSE_DIR/.env" 2>/dev/null | cut -d= -f2- || true)
    [[ -n "$n" ]] && db_name="$n"
  }
  local db_path="$LICENSE_DIR/$db_name"

  if ! command -v sqlite3 >/dev/null 2>&1; then
    err "sqlite3 not found. Run: apt-get install -y sqlite3"
    return 1
  fi

  if [[ ! -f "$db_path" ]]; then
    err "License database not found: $db_path"
    return 1
  fi

  echo -e "${Y}This will delete the license record for ${B}$name${N}${Y} from ${db_path}${N}"
  read -r -p "Are you sure? (yes/no): " confirm
  [[ "$confirm" == "yes" ]] || { info "Cancelled"; return; }

  local escaped_token; escaped_token=$(printf '%s' "$token" | sed "s/'/''/g")
  sqlite3 "$db_path" <<EOF
DELETE FROM instances WHERE bot_token='${escaped_token}';
DELETE FROM licenses  WHERE bot_token='${escaped_token}';
EOF
  ok "License for $name deleted from database."
}

# ── Bulk operations ───────────────────────────────────────────────────────────

bulk_start_all() {
  for d in "$BASE_DIR"/*/; do
    [[ -d "$d" ]] || continue
    [[ "$(basename "$d")" == ".repos" ]] && continue
    do_start "$d"
  done
}

bulk_stop_all() {
  for d in "$BASE_DIR"/*/; do
    [[ -d "$d" ]] || continue
    [[ "$(basename "$d")" == ".repos" ]] && continue
    do_stop "$d"
  done
}

bulk_restart_all() {
  for d in "$BASE_DIR"/*/; do
    [[ -d "$d" ]] || continue
    [[ "$(basename "$d")" == ".repos" ]] && continue
    do_restart "$d"
  done
}

bulk_update_all() {
  for d in "$BASE_DIR"/*/; do
    [[ -d "$d" ]] || continue
    [[ "$(basename "$d")" == ".repos" ]] && continue
    do_update "$d"
  done
}

bulk_remove_all() {
  echo -e "${R}⚠️  This will remove ALL deployed bot instances!${N}"
  read -r -p "Type DELETE ALL to confirm: " confirm
  [[ "$confirm" == "DELETE ALL" ]] || { info "Cancelled"; return; }
  for d in "$BASE_DIR"/*/; do
    [[ -d "$d" ]] || continue
    local name; name="$(basename "$d")"
    [[ "$name" == ".repos" ]] && continue
    local svc; svc="$(get_svc_from_dir "$d")"
    systemctl stop "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
    rm -f "/etc/systemd/system/${svc}.service"
    rm -rf "$d"
    ok "$name removed"
  done
  systemctl daemon-reload
}

# ── Instance sub-menu ─────────────────────────────────────────────────────────

instance_menu() {
  local d="$1"
  local name; name="$(basename "$d")"

  while true; do
    header
    local svc; svc="$(get_svc_from_dir "$d")"
    local status_str
    if systemctl is-active "$svc" >/dev/null 2>&1; then
      status_str="${G}🟢 Online${N}"
    else
      status_str="${R}🔴 Offline${N}"
    fi

    echo -e "${C}╔══════════════════════════════════════════════════════════════════════════╗${N}"
    echo -e "${C}║${N}  🤖 ${B}${W}${name}${N}  —  Status: $status_str"
    echo -e "${C}╚══════════════════════════════════════════════════════════════════════════╝${N}"
    echo ""
    echo -e "${C}┌──────────────────────────────────────┐${N}"
    echo -e "${C}│${N}  ${B}${G}1)${N} ▶️  Start                          ${C}│${N}"
    echo -e "${C}│${N}  ${B}${G}2)${N} ⏹️  Stop                           ${C}│${N}"
    echo -e "${C}│${N}  ${B}${G}3)${N} 🔁 Restart                         ${C}│${N}"
    echo -e "${C}│${N}  ${B}${G}4)${N} 📊 Status                          ${C}│${N}"
    echo -e "${C}│${N}  ${B}${G}5)${N} 📜 Live log                        ${C}│${N}"
    echo -e "${C}│${N}  ${B}${G}6)${N} ✏️  Edit .env                      ${C}│${N}"
    echo -e "${C}│${N}  ${B}${Y}7)${N} 🔄 Update from GitHub              ${C}│${N}"
    echo -e "${C}│${N}  ${B}${R}8)${N} 🗑️  Remove                         ${C}│${N}"
    echo -e "${C}│${N}  ${B}${M}d)${N} 🔑 Delete license from DB          ${C}│${N}"
    echo -e "${C}│${N}  ${B}${R}b)${N} 🔙 Back                            ${C}│${N}"
    echo -e "${C}└──────────────────────────────────────┘${N}"
    echo ""

    read -r -p "$(echo -e "${C}${name}${N} ${B}➜${N} option ${W}[1-8/d/b]${N}: ")" choice
    case "${choice:-}" in
      1) do_start "$d"; read -r -p "Enter...";;
      2) do_stop "$d"; read -r -p "Enter...";;
      3) do_restart "$d"; read -r -p "Enter...";;
      4) do_status "$d"; read -r -p "Enter...";;
      5) do_log "$d";;
      6) do_edit_env "$d"; read -r -p "Enter...";;
      7) do_update "$d"; read -r -p "Enter...";;
      8) do_remove "$d"; read -r -p "Enter..."; return;;
      d) do_delete_license "$d"; read -r -p "Enter...";;
      b) return;;
      *) echo -e "${R}Invalid option${N}"; sleep 1;;
    esac
  done
}

# ── License Bot Management ───────────────────────────────────────────────────

license_get_status() {
  if systemctl is-active "$LICENSE_SERVICE" >/dev/null 2>&1; then
    echo -e "${G}🟢 Online${N}"
  else
    echo -e "${R}🔴 Offline${N}"
  fi
}

license_configure_env() {
  echo ""
  echo -e "${C}╔══════════════════════════════════════════════════════════════════════════╗${N}"
  echo -e "${C}║${N}              ${B}${W}⚙️  License Bot Configuration${N}"
  echo -e "${C}╚══════════════════════════════════════════════════════════════════════════╝${N}"
  echo ""

  read -r -p "$(echo -e "${B}🔑 License Bot Token (from @BotFather): ${N}")" LIC_TOKEN
  LIC_TOKEN="${LIC_TOKEN// /}"
  [[ -n "$LIC_TOKEN" ]] || { err "Token cannot be empty"; return 1; }
  [[ "$LIC_TOKEN" =~ ^[0-9]+:.+$ ]] || { err "Invalid token format"; return 1; }

  read -r -p "$(echo -e "${B}👤 Admin Chat ID (numeric): ${N}")" LIC_ADMIN
  LIC_ADMIN="${LIC_ADMIN// /}"
  [[ "$LIC_ADMIN" =~ ^-?[0-9]+$ ]] || { err "Admin ID must be numeric"; return 1; }

  read -r -p "$(echo -e "${B}🌐 License API Port [8585]: ${N}")" LIC_PORT
  LIC_PORT="${LIC_PORT:-8585}"

  read -r -p "$(echo -e "${B}📂 Database name [license.db]: ${N}")" LIC_DB
  LIC_DB="${LIC_DB:-license.db}"

  cat > "$LICENSE_DIR/.env" << ENVEOF
BOT_TOKEN=${LIC_TOKEN}
ADMIN_IDS=${LIC_ADMIN}
DB_NAME=${LIC_DB}
LICENSE_API_PORT=${LIC_PORT}
ENVEOF
  chmod 600 "$LICENSE_DIR/.env"
  ok "License Bot configuration saved."

  echo ""
  echo -e "${Y}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
  echo -e "${B}${W}   📌 Use this URL in your Seamless bots' .env:${N}"
  local server_ip
  server_ip=$(curl -s4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
  echo -e "   ${B}${G}LICENSE_API_URL=http://${server_ip}:${LIC_PORT}${N}"
  echo -e "${Y}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
  echo ""
}

license_install() {
  ensure_safe_cwd
  install_prereqs
  info "Downloading License Bot..."
  local tmpdir="/tmp/seamless-license-clone"
  rm -rf "$tmpdir"
  git clone --depth 1 -b "$LICENSE_BRANCH" "$LICENSE_REPO" "$tmpdir"

  rm -rf "$LICENSE_DIR"
  mkdir -p "$LICENSE_DIR"
  cp -r "$tmpdir/$LICENSE_SUBDIR/"* "$LICENSE_DIR/"
  rm -rf "$tmpdir"

  [[ -f "$LICENSE_DIR/main.py" ]] || { err "main.py not found in license bot."; return 1; }

  info "Setting up Python environment..."
  [[ -d "$LICENSE_DIR/venv" ]] || python3 -m venv "$LICENSE_DIR/venv"
  "$LICENSE_DIR/venv/bin/pip" install --upgrade pip wheel
  "$LICENSE_DIR/venv/bin/pip" install -r "$LICENSE_DIR/requirements.txt"

  license_configure_env

  info "Creating systemd service..."
  cat > "/etc/systemd/system/${LICENSE_SERVICE}.service" << EOF
[Unit]
Description=Seamless License Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=${LICENSE_DIR}
EnvironmentFile=${LICENSE_DIR}/.env
ExecStart=${LICENSE_DIR}/venv/bin/python ${LICENSE_DIR}/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$LICENSE_SERVICE" >/dev/null 2>&1 || true
  systemctl restart "$LICENSE_SERVICE"

  echo ""
  echo -e "${G}╔══════════════════════════════════════════════════════════════════════════╗${N}"
  echo -e "${G}║${N}        ${B}${G}✅  License Bot installed and started!${N}                          ${G}║${N}"
  echo -e "${G}╚══════════════════════════════════════════════════════════════════════════╝${N}"
  echo ""
  systemctl status "$LICENSE_SERVICE" --no-pager -l || true
}

license_update() {
  ensure_safe_cwd
  [[ -d "$LICENSE_DIR" ]] || { err "License bot not installed."; return 1; }
  info "Updating License Bot from GitHub..."
  local tmpdir="/tmp/seamless-license-clone"
  rm -rf "$tmpdir"
  git clone --depth 1 -b "$LICENSE_BRANCH" "$LICENSE_REPO" "$tmpdir"

  # Preserve .env and database
  local env_backup=""
  [[ -f "$LICENSE_DIR/.env" ]] && env_backup="$(cat "$LICENSE_DIR/.env")"

  rm -rf "$LICENSE_DIR/bot" "$LICENSE_DIR/main.py" "$LICENSE_DIR/license_api.py" "$LICENSE_DIR/requirements.txt"
  cp -r "$tmpdir/$LICENSE_SUBDIR/"* "$LICENSE_DIR/"
  rm -rf "$tmpdir"

  [[ -n "$env_backup" ]] && echo "$env_backup" > "$LICENSE_DIR/.env"

  "$LICENSE_DIR/venv/bin/pip" install -r "$LICENSE_DIR/requirements.txt" -q
  systemctl restart "$LICENSE_SERVICE"
  ok "License Bot updated and restarted!"
}

license_rewrite_env() {
  ensure_safe_cwd
  [[ -d "$LICENSE_DIR" ]] || { err "License bot not installed."; return 1; }
  license_configure_env
  systemctl restart "$LICENSE_SERVICE"
  ok "License Bot configuration updated and restarted!"
}

license_remove() {
  ensure_safe_cwd
  read -r -p "Are you sure you want to remove the License Bot? (yes/no): " confirm
  [[ "$confirm" == "yes" ]] || { info "Cancelled"; return; }
  systemctl stop    "$LICENSE_SERVICE" 2>/dev/null || true
  systemctl disable "$LICENSE_SERVICE" 2>/dev/null || true
  rm -f "/etc/systemd/system/${LICENSE_SERVICE}.service"
  systemctl daemon-reload
  rm -rf "$LICENSE_DIR"
  ok "License Bot completely removed."
}

show_license_menu() {
  local status; status="$(license_get_status)"
  echo -e "${C}╔══════════════════════════════════════════════════════════════════════════╗${N}"
  echo -e "${C}║${N}  🔑 ${B}${W}Seamless License Bot${N}   Status: $status                           ${C}║${N}"
  echo -e "${C}╚══════════════════════════════════════════════════════════════════════════╝${N}"
  echo ""
  echo -e "${C}┌──────────────────────────────────────┐${N}"
  echo -e "${C}│${N}  ${B}${G}1)${N} 📦 Install                         ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}2)${N} 🔄 Update from GitHub              ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}3)${N} ✏️  Rewrite .env                   ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}4)${N} ▶️  Start                          ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}5)${N} ⏹️  Stop                           ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}6)${N} 🔁 Restart                         ${C}│${N}"
  echo -e "${C}│${N}  ${B}${R}7)${N} 🗑️  Remove                         ${C}│${N}"
  echo -e "${C}│${N}  ${B}${Y}8)${N} 📜 Live log                        ${C}│${N}"
  echo -e "${C}│${N}  ${B}${R}b)${N} 🔙 Back                            ${C}│${N}"
  echo -e "${C}└──────────────────────────────────────┘${N}"
  echo ""
}

license_loop() {
  while true; do
    header
    show_license_menu
    read -r -p "$(echo -e "${C}License Bot${N} ${B}➜${N} option ${W}[1-8/b]${N}: ")" choice
    case "${choice:-}" in
      1) license_install; read -r -p "Enter...";;
      2) license_update; read -r -p "Enter...";;
      3) license_rewrite_env; read -r -p "Enter...";;
      4) systemctl start  "$LICENSE_SERVICE" 2>/dev/null && ok "License Bot started"; read -r -p "Enter...";;
      5) systemctl stop   "$LICENSE_SERVICE" 2>/dev/null && ok "License Bot stopped"; read -r -p "Enter...";;
      6) systemctl restart "$LICENSE_SERVICE" 2>/dev/null && ok "License Bot restarted"; read -r -p "Enter...";;
      7) license_remove; read -r -p "Enter..."; return;;
      8) echo -e "${Y}Press Ctrl+C to exit log${N}"; sleep 1; journalctl -u "$LICENSE_SERVICE" -f;;
      b) return;;
      *) echo -e "${R}Invalid option${N}"; sleep 1;;
    esac
  done
}

# ── Main menu ─────────────────────────────────────────────────────────────────

show_menu() {
  echo -e "${C}┌──────────────────────────────────────────┐${N}"
  echo -e "${C}│${N}  ${B}${G}m)${N} 🤖 Manage an instance (by number)  ${C}│${N}"
  echo -e "${C}│${N}  ${B}${M}L)${N} 🔑 License Bot Management          ${C}│${N}"
  echo -e "${C}├──────────────────────────────────────────┤${N}"
  echo -e "${C}│${N}  ${B}${Y}1)${N} ▶️  Start all                       ${C}│${N}"
  echo -e "${C}│${N}  ${B}${Y}2)${N} ⏹️  Stop all                        ${C}│${N}"
  echo -e "${C}│${N}  ${B}${Y}3)${N} 🔁 Restart all                      ${C}│${N}"
  echo -e "${C}│${N}  ${B}${Y}4)${N} 🔄 Update all from GitHub           ${C}│${N}"
  echo -e "${C}│${N}  ${B}${R}5)${N} 🗑️  Remove all                      ${C}│${N}"
  echo -e "${C}├──────────────────────────────────────────┤${N}"
  echo -e "${C}│${N}  ${B}${R}0)${N} 🚪 Exit                             ${C}│${N}"
  echo -e "${C}└──────────────────────────────────────────┘${N}"
  echo ""
}

main() {
  [[ -t 0 ]] || exec < /dev/tty
  check_root

  while true; do
    header
    list_instances
    show_menu

    read -r -p "$(echo -e "${C}Instances${N} ${B}➜${N} option ${W}[m/L/1-5/0]${N}: ")" choice

    case "${choice:-}" in
      m)
        echo ""
        read -r -p "$(echo -e "${B}🔢 Instance number: ${N}")" idx
        [[ "$idx" =~ ^[0-9]+$ ]] || { err "Invalid number"; sleep 1; continue; }
        local d; d="$(get_instance_by_idx "$idx")" || { err "Instance #$idx not found"; sleep 1; continue; }
        instance_menu "$d"
        ;;
      1) header; bulk_start_all; read -r -p "Enter...";;
      2) header; bulk_stop_all; read -r -p "Enter...";;
      3) header; bulk_restart_all; read -r -p "Enter...";;
      4) header; bulk_update_all; read -r -p "Enter...";;
      5) header; bulk_remove_all; read -r -p "Enter...";;
      L|l) license_loop;;
      0) echo "Goodbye!"; exit 0;;
      *) echo -e "${R}Invalid option${N}"; sleep 1;;
    esac
  done
}

main "$@"
