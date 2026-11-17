#!/usr/bin/env bash
# ============================================================
# free-ai-image-gen-tools-gateway systemd one-click install script
# Installs as a systemd service on Linux server: auto-start on boot, auto-restart on crash
# Usage: sudo ./scripts/deploy-systemd.sh [options]
# Options:
#   --user <run user>    User to run the service (default: current user)
#   --port <port>        Listening port (default: 8799)
#   --host <address>     Listening address (default: 0.0.0.0, for cloud server external access)
#   --uninstall          Uninstall service
#   --help               Show help
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default parameters
RUN_USER="$USER"
PORT=8799
HOST="0.0.0.0"
DO_UNINSTALL=0
SERVICE_NAME="free-ai-image-gen-tools-gateway"

# Parse parameters
while [ $# -gt 0 ]; do
  case "$1" in
    --user) RUN_USER="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --uninstall) DO_UNINSTALL=1; shift ;;
    --help|-h)
      echo "Usage: sudo ./scripts/deploy-systemd.sh [options]"
      echo "  --user <run user>   User to run the service (default: current user)"
      echo "  --port <port>       Listening port (default: 8799)"
      echo "  --host <address>    Listening address (default: 0.0.0.0)"
      echo "  --uninstall         Uninstall service"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Check root
if [ "$EUID" -ne 0 ]; then
  echo "Error: please run this script with sudo"
  exit 1
fi

# Uninstall mode
if [ $DO_UNINSTALL -eq 1 ]; then
  echo "Uninstalling $SERVICE_NAME service..."
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl disable "$SERVICE_NAME" 2>/dev/null || true
  rm -f "/etc/systemd/system/$SERVICE_NAME.service"
  systemctl daemon-reload
  echo "Service uninstalled (project files and data remain in $PROJECT_ROOT)"
  exit 0
fi

echo "============================================"
echo "  free-ai-image-gen-tools-gateway systemd install"
echo "============================================"
echo "  Project:   $PROJECT_ROOT"
echo "  User:      $RUN_USER"
echo "  Address:   $HOST:$PORT"
echo "============================================"

# 1. Install dependencies
echo ""
echo "[1/5] Installing Python dependencies..."
cd "$PROJECT_ROOT"
sudo -u "$RUN_USER" python3 -m pip install -r requirements.txt
echo "  Dependencies installed"

# 2. Generate config (if not exists)
echo ""
echo "[2/5] Checking configuration..."
if [ ! -f "$PROJECT_ROOT/config.yaml" ]; then
  sudo -u "$RUN_USER" cp "$PROJECT_ROOT/config.example.yaml" "$PROJECT_ROOT/config.yaml"
  echo "  config.yaml generated"
else
  echo "  config.yaml already exists"
fi
# Ensure host/port correct; force admin_token when listening publicly (0.0.0.0)
sudo -u "$RUN_USER" python3 -c "
import yaml, secrets
path = '$PROJECT_ROOT/config.yaml'
with open(path) as f: c = yaml.safe_load(f) or {}
srv = c.setdefault('server', {})
srv['host'] = '$HOST'
srv['port'] = $PORT
if '$HOST' == '0.0.0.0' and not srv.get('admin_token'):
    token = secrets.token_hex(16)
    srv['admin_token'] = token
    print('  Public listening, auto-generated admin_token:', token)
    print('  Please enter this token in the admin token input box at the top of the web console')
else:
    print('  Configuration updated host=$HOST port=$PORT')
with open(path, 'w') as f: yaml.safe_dump(c, f, allow_unicode=True, sort_keys=False)
"

# 3. Generate systemd service file
echo ""
echo "[3/5] Generating systemd service file..."
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=free-ai-image-gen-tools-gateway Unified Image Generation Gateway
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_ROOT
ExecStart=/usr/bin/env python3 -m uvicorn imggen.server:app --host $HOST --port $PORT --forwarded-allow-ips '127.0.0.1'
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=STORAGE_DIR=$PROJECT_ROOT/storage

[Install]
WantedBy=multi-user.target
EOF
echo "  Written to $SERVICE_FILE"

# 4. Enable and start
echo ""
echo "[4/5] Enabling and starting service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 2

# 5. Verify
echo ""
echo "[5/5] Verifying service status..."
if systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "  Service running"
  systemctl --no-pager status "$SERVICE_NAME" | head -10
else
  echo "  Service start failed, check logs:"
  journalctl -u "$SERVICE_NAME" --no-pager -n 20
  exit 1
fi

echo ""
echo "============================================"
echo "  Installation complete!"
echo "============================================"
echo "  Web console: http://$HOST:$PORT/"
echo "  API docs:    http://$HOST:$PORT/docs"
echo "  MCP endpoint: http://$HOST:$PORT/mcp"
echo "  Service management:"
echo "    Start:   sudo systemctl start $SERVICE_NAME"
echo "    Stop:    sudo systemctl stop $SERVICE_NAME"
echo "    Restart: sudo systemctl restart $SERVICE_NAME"
echo "    Status:  sudo systemctl status $SERVICE_NAME"
echo "    Logs:    sudo journalctl -u $SERVICE_NAME -f"
echo "  Config file: $PROJECT_ROOT/config.yaml"
echo "  Data dir:    $PROJECT_ROOT/storage"
echo "============================================"
echo ""
echo "Important: for external deployment, be sure to set admin_token in config.yaml,"
echo "           and open port $PORT in the cloud server security group."
