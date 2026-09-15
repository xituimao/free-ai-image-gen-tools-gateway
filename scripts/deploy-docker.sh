#!/usr/bin/env bash
# ============================================================
# free-ai-image-gen-tools-gateway Docker 一键部署脚本
# 用法：./scripts/deploy-docker.sh [选项]
# 选项：
#   --name <容器名>     容器名（默认 free-ai-image-gen-tools-gateway）
#   --port <端口>       宿主机端口（默认 8799）
#   --data <目录>       数据卷挂载目录（默认 ./data）
#   --no-build          跳过构建，直接用已有镜像
#   --help              显示帮助
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 默认参数
CONTAINER_NAME="free-ai-image-gen-tools-gateway"
HOST_PORT=8799
DATA_DIR="$PROJECT_ROOT/data"
DO_BUILD=1

# 解析参数
while [ $# -gt 0 ]; do
  case "$1" in
    --name) CONTAINER_NAME="$2"; shift 2 ;;
    --port) HOST_PORT="$2"; shift 2 ;;
    --data) DATA_DIR="$2"; shift 2 ;;
    --no-build) DO_BUILD=0; shift ;;
    --help|-h)
      echo "用法: ./scripts/deploy-docker.sh [选项]"
      echo "  --name <容器名>     容器名（默认 free-ai-image-gen-tools-gateway）"
      echo "  --port <端口>       宿主机端口（默认 8799）"
      echo "  --data <目录>       数据卷挂载目录（默认 ./data）"
      echo "  --no-build          跳过构建，直接用已有镜像"
      exit 0 ;;
    *) echo "未知选项: $1"; exit 1 ;;
  esac
done

echo "============================================"
echo "  free-ai-image-gen-tools-gateway Docker 部署"
echo "============================================"
echo "  容器名: $CONTAINER_NAME"
echo "  端口:   $HOST_PORT"
echo "  数据:   $DATA_DIR"
echo "============================================"

# 1. 构建镜像
if [ $DO_BUILD -eq 1 ]; then
  echo ""
  echo "[1/4] 构建 Docker 镜像..."
  docker build -t free-ai-image-gen-tools-gateway:latest .
  echo "  镜像构建完成"
else
  echo ""
  echo "[1/4] 跳过构建（--no-build）"
fi

# 2. 停止并删除旧容器
echo ""
echo "[2/4] 清理旧容器..."
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
  echo "  旧容器已移除"
else
  echo "  无旧容器"
fi

# 3. 创建数据目录
echo ""
echo "[3/4] 准备数据目录..."
mkdir -p "$DATA_DIR"
echo "  数据目录: $DATA_DIR"

# 4. 启动容器
echo ""
echo "[4/4] 启动容器..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p "$HOST_PORT:8799" \
  -v "$DATA_DIR:/data" \
  -e STORAGE_DIR=/data \
  free-ai-image-gen-tools-gateway:latest

echo ""
echo "============================================"
echo "  部署完成！"
echo "============================================"
echo "  网页控制台: http://127.0.0.1:$HOST_PORT/"
echo "  API 文档:   http://127.0.0.1:$HOST_PORT/docs"
echo "  MCP 端点:   http://127.0.0.1:$HOST_PORT/mcp"
echo "  容器日志:   docker logs -f $CONTAINER_NAME"
echo "  停止:       docker stop $CONTAINER_NAME"
echo "  重启:       docker restart $CONTAINER_NAME"
echo "  数据文件:   $DATA_DIR"
echo "============================================"
echo ""
echo "提示：首次使用请在网页控制台「渠道管理」页填写各渠道 API Key，"
echo "      或编辑 $DATA_DIR/../config.yaml（需重启容器生效）。"
echo "      对外部署时务必设置 admin_token（环境变量 ADMIN_TOKEN）。"
