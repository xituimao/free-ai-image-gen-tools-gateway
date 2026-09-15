#!/usr/bin/env bash
# ============================================================
# free-ai-image-gen-tools-gateway 统一管理脚本
# 用法：./scripts/manage.sh <命令>
# 命令：
#   install    一键安装依赖 + 生成配置（首次使用）
#   configure  交互式配置（部署模式 / admin_token / 各渠道 key）
#   start      一键启动（后台运行，自动检测依赖和配置）
#   stop       停止
#   restart    重启
#   status     状态（运行中/PID/端口/最近日志）
#   logs       实时查看日志（Ctrl+C 退出）
#   health     健康检查
#   reload     热加载配置（不重启，调用 /admin/reload）
#   uninstall  停止并移除 pid/log（不删除图片和配置）
# ============================================================
set -euo pipefail

# 项目根目录（脚本所在目录的上一级）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 运行时文件
PID_FILE="$PROJECT_ROOT/.run/gateway.pid"
LOG_FILE="$PROJECT_ROOT/.run/gateway.log"
mkdir -p "$PROJECT_ROOT/.run"

# Python 解释器
PY=python3
command -v $PY >/dev/null 2>&1 || PY=python

# 颜色
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERR]${NC} $*"; }

# 读取配置中的 host/port（默认 127.0.0.1:8799）
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
  info "安装 Python 依赖..."
  $PY -m pip install -r requirements.txt
  ok "依赖安装完成"
  if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    ok "已生成 config.yaml（从模板复制）"
    warn "请执行 ./scripts/manage.sh configure 填写渠道 key 和 admin_token"
  else
    info "config.yaml 已存在，跳过生成"
  fi
}

cmd_configure() {
  info "交互式配置向导"
  echo ""
  echo "=== 部署模式 ==="
  echo "  1) 本机自用（127.0.0.1，无需 admin_token）"
  echo "  2) 云服务器对外（0.0.0.0，必须设 admin_token）"
  read -p "请选择 [1/2，默认1]: " mode
  mode=${mode:-1}

  if [ "$mode" = "2" ]; then
    HOST="0.0.0.0"
    read -p "设置 admin_token（管理接口鉴权，留空自动生成）: " ADMIN_TOKEN
    if [ -z "$ADMIN_TOKEN" ]; then
      ADMIN_TOKEN=$($PY -c "import secrets; print(secrets.token_hex(16))")
      info "自动生成 admin_token: $ADMIN_TOKEN"
    fi
  else
    HOST="127.0.0.1"
    ADMIN_TOKEN=""
  fi

  echo ""
  echo "=== 渠道配置（留空则不启用/不修改）==="
  # 用临时 JSON 传递用户输入，避免 bash/Python 变量传递问题
  TMP_JSON=$(mktemp)
  echo "{" > "$TMP_JSON"
  FIRST=1
  for ch in gemini siliconflow openai bailian hf_space bing; do
    read -p "$ch API Key（留空跳过）: " val
    if [ -n "$val" ]; then
      [ $FIRST -eq 0 ] && echo "," >> "$TMP_JSON"
      echo "  \"$ch\": \"$val\"" >> "$TMP_JSON"
      FIRST=0
    fi
  done
  echo "" >> "$TMP_JSON"
  echo "}" >> "$TMP_JSON"

  # 用 Python 合并配置（保留已有配置，只更新指定字段）
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
print("配置已写入", path)
PYEOF
  rm -f "$TMP_JSON"

  ok "配置完成"
  if is_running; then
    info "检测到服务正在运行，执行热加载..."
    cmd_reload || warn "热加载失败，请执行 restart"
  else
    info "执行 ./scripts/manage.sh start 启动服务"
  fi
}

cmd_start() {
  if is_running; then
    local pid=$(cat "$PID_FILE")
    warn "服务已在运行（PID=$pid），如需重启请执行 restart"
    return 0
  fi
  # 自动安装依赖
  $PY -c "import fastapi, uvicorn, httpx, yaml, multipart" 2>/dev/null || {
    info "首次运行，安装依赖..."
    $PY -m pip install -r requirements.txt
  }
  # 自动生成配置
  [ -f config.yaml ] || cp config.example.yaml config.yaml

  local HOST=$(get_host); local PORT=$(get_port)
  info "启动 free-ai-image-gen-tools-gateway（$HOST:$PORT）..."
  nohup $PY -m imggen.server >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  # 等待启动（最多15秒）
  for i in $(seq 1 30); do
    sleep 0.5
    if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
      ok "启动成功（PID=$(cat $PID_FILE)）"
      echo "  网页控制台: http://$HOST:$PORT/"
      echo "  API 文档:   http://$HOST:$PORT/docs"
      echo "  MCP 端点:   http://$HOST:$PORT/mcp"
      echo "  日志文件:   $LOG_FILE"
      return 0
    fi
  done
  err "启动超时，请查看日志: $LOG_FILE"
  tail -20 "$LOG_FILE"
  return 1
}

cmd_stop() {
  if ! is_running; then
    warn "服务未运行"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid=$(cat "$PID_FILE")
  info "停止服务（PID=$pid）..."
  kill "$pid" 2>/dev/null || true
  # 等待退出（最多10秒）
  for i in $(seq 1 20); do
    sleep 0.5
    kill -0 "$pid" 2>/dev/null || break
  done
  if kill -0 "$pid" 2>/dev/null; then
    warn "优雅停止超时，强制 kill"
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  ok "已停止"
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

cmd_status() {
  echo "=== free-ai-image-gen-tools-gateway 状态 ==="
  if is_running; then
    local pid=$(cat "$PID_FILE")
    local HOST=$(get_host); local PORT=$(get_port)
    echo -e "  状态:   ${GREEN}运行中${NC}"
    echo "  PID:    $pid"
    echo "  地址:   http://$HOST:$PORT/"
    if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
      echo -e "  健康:   ${GREEN}正常${NC}"
      curl -s "http://127.0.0.1:$PORT/health" | $PY -m json.tool 2>/dev/null | head -5
    else
      echo -e "  健康:   ${RED}异常（端口无响应）${NC}"
    fi
  else
    echo -e "  状态:   ${RED}未运行${NC}"
  fi
  echo "  日志:   $LOG_FILE"
  echo "  配置:   $PROJECT_ROOT/config.yaml"
}

cmd_logs() {
  if [ ! -f "$LOG_FILE" ]; then
    warn "日志文件不存在（服务可能从未启动）"
    return 0
  fi
  info "实时日志（Ctrl+C 退出）..."
  tail -f "$LOG_FILE"
}

cmd_health() {
  local PORT=$(get_port)
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    ok "服务健康"
    curl -s "http://127.0.0.1:$PORT/health"
    echo ""
  else
    err "服务不健康（端口 $PORT 无响应）"
    return 1
  fi
}

cmd_reload() {
  if ! is_running; then
    err "服务未运行，无法热加载"
    return 1
  fi
  local PORT=$(get_port)
  local TOKEN=""
  # 从配置读取 admin_token
  TOKEN=$($PY -c "
import yaml
try:
    with open('config.yaml') as f: c = yaml.safe_load(f) or {}
    print((c.get('server') or {}).get('admin_token', ''))
except Exception: print('')
" 2>/dev/null)
  info "热加载配置..."
  if [ -n "$TOKEN" ]; then
    curl -sf -X POST "http://127.0.0.1:$PORT/admin/reload" -H "X-Admin-Token: $TOKEN" >/dev/null
  else
    curl -sf -X POST "http://127.0.0.1:$PORT/admin/reload" >/dev/null
  fi
  ok "配置已热加载"
}

cmd_uninstall() {
  warn "即将停止服务并移除运行时文件（pid/log），不会删除图片和配置"
  read -p "确认？[y/N]: " confirm
  [ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || { info "已取消"; return 0; }
  cmd_stop
  rm -rf "$PROJECT_ROOT/.run"
  ok "已清理运行时文件"
  info "图片和配置保留在: $PROJECT_ROOT/storage 和 $PROJECT_ROOT/config.yaml"
}

# 主入口
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
    echo "free-ai-image-gen-tools-gateway 管理脚本"
    echo ""
    echo "用法: ./scripts/manage.sh <命令>"
    echo ""
    echo "命令:"
    echo "  install    安装依赖 + 生成配置（首次使用）"
    echo "  configure  交互式配置（部署模式/admin_token/渠道key）"
    echo "  start      启动（后台运行）"
    echo "  stop       停止"
    echo "  restart    重启"
    echo "  status     状态"
    echo "  logs       实时日志"
    echo "  health     健康检查"
    echo "  reload     热加载配置（不重启）"
    echo "  uninstall  停止并清理运行时文件"
    ;;
  *)
    err "未知命令: $1"
    echo "执行 ./scripts/manage.sh help 查看可用命令"
    exit 1
    ;;
esac
