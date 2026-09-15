#!/usr/bin/env bash
# ============================================================
# free-ai-image-gen-tools-gateway systemd 一键安装脚本
# 在 Linux 服务器上安装为 systemd 服务，开机自启、崩溃自动重启
# 用法：sudo ./scripts/deploy-systemd.sh [选项]
# 选项：
#   --user <运行用户>   运行服务的用户（默认当前用户）
#   --port <端口>       监听端口（默认 8799）
#   --host <地址>       监听地址（默认 0.0.0.0，云服务器对外）
#   --uninstall         卸载服务
#   --help              显示帮助
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 默认参数
RUN_USER="$USER"
PORT=8799
HOST="0.0.0.0"
DO_UNINSTALL=0
SERVICE_NAME="free-ai-image-gen-tools-gateway"

# 解析参数
while [ $# -gt 0 ]; do
  case "$1" in
    --user) RUN_USER="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --uninstall) DO_UNINSTALL=1; shift ;;
    --help|-h)
      echo "用法: sudo ./scripts/deploy-systemd.sh [选项]"
      echo "  --user <运行用户>   运行服务的用户（默认当前用户）"
      echo "  --port <端口>       监听端口（默认 8799）"
      echo "  --host <地址>       监听地址（默认 0.0.0.0）"
      echo "  --uninstall         卸载服务"
      exit 0 ;;
    *) echo "未知选项: $1"; exit 1 ;;
  esac
done

# 检查 root
if [ "$EUID" -ne 0 ]; then
  echo "错误：请使用 sudo 运行此脚本"
  exit 1
fi

# 卸载模式
if [ $DO_UNINSTALL -eq 1 ]; then
  echo "卸载 $SERVICE_NAME 服务..."
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl disable "$SERVICE_NAME" 2>/dev/null || true
  rm -f "/etc/systemd/system/$SERVICE_NAME.service"
  systemctl daemon-reload
  echo "服务已卸载（项目文件和数据保留在 $PROJECT_ROOT）"
  exit 0
fi

echo "============================================"
echo "  free-ai-image-gen-tools-gateway systemd 安装"
echo "============================================"
echo "  项目:   $PROJECT_ROOT"
echo "  用户:   $RUN_USER"
echo "  地址:   $HOST:$PORT"
echo "============================================"

# 1. 安装依赖
echo ""
echo "[1/5] 安装 Python 依赖..."
cd "$PROJECT_ROOT"
sudo -u "$RUN_USER" python3 -m pip install -r requirements.txt
echo "  依赖安装完成"

# 2. 生成配置（如果不存在）
echo ""
echo "[2/5] 检查配置..."
if [ ! -f "$PROJECT_ROOT/config.yaml" ]; then
  sudo -u "$RUN_USER" cp "$PROJECT_ROOT/config.example.yaml" "$PROJECT_ROOT/config.yaml"
  echo "  已生成 config.yaml"
else
  echo "  config.yaml 已存在"
fi
# 确保 host/port 正确；公网监听（0.0.0.0）时强制设置 admin_token
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
    print('  公网监听，自动生成 admin_token:', token)
    print('  请在网页控制台顶栏 admin token 输入框填入此 token')
else:
    print('  配置已更新 host=$HOST port=$PORT')
with open(path, 'w') as f: yaml.safe_dump(c, f, allow_unicode=True, sort_keys=False)
"

# 3. 生成 systemd service 文件
echo ""
echo "[3/5] 生成 systemd service 文件..."
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=free-ai-image-gen-tools-gateway 统一生图网关
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
echo "  已写入 $SERVICE_FILE"

# 4. 启用并启动
echo ""
echo "[4/5] 启用并启动服务..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 2

# 5. 验证
echo ""
echo "[5/5] 验证服务状态..."
if systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "  服务运行中"
  systemctl --no-pager status "$SERVICE_NAME" | head -10
else
  echo "  服务启动失败，查看日志："
  journalctl -u "$SERVICE_NAME" --no-pager -n 20
  exit 1
fi

echo ""
echo "============================================"
echo "  安装完成！"
echo "============================================"
echo "  网页控制台: http://$HOST:$PORT/"
echo "  API 文档:   http://$HOST:$PORT/docs"
echo "  MCP 端点:   http://$HOST:$PORT/mcp"
echo "  服务管理:"
echo "    启动:   sudo systemctl start $SERVICE_NAME"
echo "    停止:   sudo systemctl stop $SERVICE_NAME"
echo "    重启:   sudo systemctl restart $SERVICE_NAME"
echo "    状态:   sudo systemctl status $SERVICE_NAME"
echo "    日志:   sudo journalctl -u $SERVICE_NAME -f"
echo "  配置文件: $PROJECT_ROOT/config.yaml"
echo "  数据目录: $PROJECT_ROOT/storage"
echo "============================================"
echo ""
echo "重要：对外部署请务必在 config.yaml 中设置 admin_token，"
echo "      并在云服务器安全组放行 $PORT 端口。"
