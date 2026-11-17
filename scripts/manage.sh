#!/usr/bin/env bash
# ============================================================
# free-ai-image-gen-tools-gateway unified management script
# Usage: ./scripts/manage.sh <command>
# Commands:
#   install    One-click install dependencies + generate config (first time use)
#   configure  Interactive configuration (deployment mode / admin_token / channel keys)
#   start      One-click start (run in background, auto detect deps and config)
#   stop       Stop
#   restart    Restart
#   status     Status (running/PID/port/recent logs)
#   logs       View logs in real time (Ctrl+C to exit)
#   health     Health check
#   reload     Hot reload config (no restart, calls /admin/reload)
#   uninstall  Stop and remove pid/log (does not delete images and config)
# ============================================================
set -euo pipefail

# Project root directory (one level above script directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Runtime files
PID_FILE="$PROJECT_ROOT/.run/gateway.pid"
LOG_FILE="$PROJECT_ROOT/.run/gateway.log"
mkdir -p "$PROJECT_ROOT/.run"

# Python interpreter
PY=python3
command -v $PY >/dev/null 2>&1 || PY=python

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERR]${NC} $*"; }

# Read host/port from config (default 127.0.0.1:8799)
get_host() { $PY -c "
import yaml, os
try:
    with open('config.yaml') as f: c = yaml.safe_load(f) or {}
    print((c.get('server') or {}).get('host', '127.0.0.1'))
except Exception:
    print('127.0.0.1')
" 2>/dev/null || echo "127.0.0.1"; }
get_port() { $PY -c "
import yaml
try:
    with open('config.yaml') as f: c = yaml.safe_load(f) or {}
    print((c.get('server') or {}).get('port', 8799))
except Exception:
    print(8799)
" 2>/dev/null || echo "8799"; }

is_running() {
  [ -f "$PID_FILE" ] || return 1
  local pid=$(cat "$PID_FILE" 2>/dev/null)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

cmd_install() {
  info "Installing Python dependencies..."
  $PY -m pip install -r requirements.txt
  ok "Dependencies installed"
  if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    ok "config.yaml generated (copied from template)"
    warn "Please run ./scripts/manage.sh configure to fill in channel keys and admin_token"
  else
    info "config.yaml already exists, skipping generation"
  fi
}

cmd_configure() {
  info "Interactive configuration wizard"
  echo ""
  echo "=== Deployment mode ==="
  echo "  1) Local personal use (127.0.0.1, no admin_token needed)"
  echo "  2) Cloud server external (0.0.0.0, admin_token required)"
  read -p "Please select [1/2, default 1]: " mode
  mode=${mode:-1}

  if [ "$mode" = "2" ]; then
    HOST="0.0.0.0"
    read -p "Set admin_token (management interface auth, leave blank to auto-generate): " ADMIN_TOKEN
    if [ -z "$ADMIN_TOKEN" ]; then
      ADMIN_TOKEN=$($PY -c "import secrets; print(secrets.token_hex(16))")
        info "Auto-generated admin_token: $ADMIN_TOKEN"
    fi
  else
    HOST="127.0.0.1"
    ADMIN_TOKEN=""
  fi

  echo ""
  echo "=== Channel configuration (leave blank to not enable/modify) ==="
  # Use temporary JSON to pass user input, avoiding bash/Python variable passing issues
  TMP_JSON=$(mktemp)
  echo "{" > "$TMP_JSON"
  FIRST=1
  for ch in gemini siliconflow openai bailian hf_space bing; do
    read -p "$ch API Key (leave blank to skip): " val
    if [ -n "$val" ]; then
      [ $FIRST -eq 0 ] && echo "," >> "$TMP_JSON"
      echo "  \"$ch\": \"$val\"" >> "$TMP_JSON"
      FIRST=0
    fi
  done
  echo "" >> "$TMP_JSON"
  echo "}" >> "$TMP_JSON"

  # Merge config with Python (preserve existing config, update specified fields only)
  $PY <<PYEOF
import yaml, os, json
path = "config.yaml"
cfg = {}
if os.path.exists(path):
    with open(path) as f: cfg = yaml.safe_load(f) or {}
srv = cfg.setdefault("server", {})
srv["host"] = "$HOST"
srv["port"] = 8799
if "$ADMIN_TOKEN":
    srv["admin_token"] = "$ADMIN_TOKEN"
prov = cfg.setdefault("providers", {})
keymap = {
    "gemini": ("gemini", "api_key"),
    "siliconflow": ("openai_compatible", "siliconflow", "api_key"),
    "openai": ("openai_compatible", "openai", "api_key"),
    "bailian": ("bailian", "api_key"),
    "hf_space": ("hf_space", "hf_token"),
    "bing": ("bing", "cookie_u"),
}
with open("$TMP_JSON") as f:
    user_keys = json.load(f)
for ch, val in user_keys.items():
    if ch not in keymap: continue
    path_keys = keymap[ch]
    d = prov
    for pk in path_keys[:-1]:
        d = d.setdefault(pk, {})
    d[path_keys[-1]] = val
with open(path, "w") as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
print("Configuration written to", path)
PYEOF
  rm -f "$TMP_JSON"

  ok "Configuration complete"
  if is_running; then
    info "Service detected running, performing hot reload..."
    cmd_reload || warn "Hot reload failed, please run restart"
  else
    info "Run ./scripts/manage.sh start to start service"
  fi
}

cmd_start() {
  if is_running; then
    local pid=$(cat "$PID_FILE")
    warn "Service already running (PID=$pid), run restart if restart needed"
    return 0
  fi
  # Auto install dependencies
  $PY -c "import fastapi, uvicorn, httpx, yaml, multipart" 2>/dev/null || {
    info "First run, installing dependencies..."
    $PY -m pip install -r requirements.txt
  }
  # Auto generate config
  [ -f config.yaml ] || cp config.example.yaml config.yaml

  local HOST=$(get_host); local PORT=$(get_port)
  info "Starting free-ai-image-gen-tools-gateway ($HOST:$PORT)..."
  nohup $PY -m imggen.server >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  # Wait for startup (max 15 seconds)
  for i in $(seq 1 30); do
    sleep 0.5
    if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
      ok "Start successful (PID=$(cat $PID_FILE))"
        echo "  Web console: http://$HOST:$PORT/"
        echo "  API docs:    http://$HOST:$PORT/docs"
        echo "  MCP endpoint: http://$HOST:$PORT/mcp"
        echo "  Log file:    $LOG_FILE"
      return 0
    fi
  done
  err "Start timed out, check logs: $LOG_FILE"
  tail -20 "$LOG_FILE"
  return 1
}

cmd_stop() {
  if ! is_running; then
    warn "Service not running"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid=$(cat "$PID_FILE")
  info "Stopping service (PID=$pid)..."
  kill "$pid" 2>/dev/null || true
  # Wait for exit (max 10 seconds)
  for i in $(seq 1 20); do
    sleep 0.5
    kill -0 "$pid" 2>/dev/null || break
  done
  if kill -0 "$pid" 2>/dev/null; then
    warn "Graceful stop timed out, force kill"
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  ok "Stopped"
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

cmd_status() {
  echo "=== free-ai-image-gen-tools-gateway status ==="
  if is_running; then
    local pid=$(cat "$PID_FILE")
    local HOST=$(get_host); local PORT=$(get_port)
    echo -e "  Status:   ${GREEN}Running${NC}"
    echo "  PID:    $pid"
    echo "  Address:   http://$HOST:$PORT/"
    if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
      echo -e "  Health:   ${GREEN}Normal${NC}"
      curl -s "http://127.0.0.1:$PORT/health" | $PY -m json.tool 2>/dev/null | head -5
    else
      echo -e "  Health:   ${RED}Abnormal (port no response)${NC}"
    fi
  else
    echo -e "  Status:   ${RED}Not running${NC}"
  fi
  echo "  Log:      $LOG_FILE"
  echo "  Config:   $PROJECT_ROOT/config.yaml"
}

cmd_logs() {
  if [ ! -f "$LOG_FILE" ]; then
    warn "Log file does not exist (service may never have started)"
    return 0
  fi
  info "Real-time logs (Ctrl+C to exit)..."
  tail -f "$LOG_FILE"
}

cmd_health() {
  local PORT=$(get_port)
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    ok "Service healthy"
    curl -s "http://127.0.0.1:$PORT/health"
    echo ""
  else
    err "Service unhealthy (port $PORT no response)"
    return 1
  fi
}

cmd_reload() {
  if ! is_running; then
    err "Service not running, cannot hot reload"
    return 1
  fi
  local PORT=$(get_port)
  local TOKEN=""
  # Read admin_token from config
  TOKEN=$($PY -c "
import yaml
try:
    with open('config.yaml') as f: c = yaml.safe_load(f) or {}
    print((c.get('server') or {}).get('admin_token', ''))
except Exception: print('')
" 2>/dev/null)
  info "Hot reloading config..."
  if [ -n "$TOKEN" ]; then
    curl -sf -X POST "http://127.0.0.1:$PORT/admin/reload" -H "X-Admin-Token: $TOKEN" >/dev/null
  else
    curl -sf -X POST "http://127.0.0.1:$PORT/admin/reload" >/dev/null
  fi
  ok "Config hot reloaded"
}

cmd_uninstall() {
  warn "About to stop service and remove runtime files (pid/log), will not delete images and config"
  read -p "Confirm? [y/N]: " confirm
  [ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || { info "Cancelled"; return 0; }
  cmd_stop
  rm -rf "$PROJECT_ROOT/.run"
  ok "Runtime files cleaned"
  info "Images and config retained in: $PROJECT_ROOT/storage and $PROJECT_ROOT/config.yaml"
}

# Main entry
case "${1:-help}" in
  install)   cmd_install ;;
  configure) cmd_configure ;;
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  restart)   cmd_restart ;;
  status)    cmd_status ;;
  logs)      cmd_logs ;;
  health)    cmd_health ;;
  reload)    cmd_reload ;;
  uninstall) cmd_uninstall ;;
  help|--help|-h)
    echo "free-ai-image-gen-tools-gateway management script"
    echo ""
    echo "Usage: ./scripts/manage.sh <command>"
    echo ""
    echo "Commands:"
    echo "  install    Install dependencies + generate config (first time use)"
    echo "  configure  Interactive configuration (deployment mode/admin_token/channel key)"
    echo "  start      Start (run in background)"
    echo "  stop       Stop"
    echo "  restart    Restart"
    echo "  status     Status"
    echo "  logs       Real-time logs"
    echo "  health     Health check"
    echo "  reload     Hot reload config (no restart)"
    echo "  uninstall  Stop and clean up runtime files"
    ;;
  *)
    err "Unknown command: $1"
    echo "Run ./scripts/manage.sh help to see available commands"
    exit 1
    ;;
esac
