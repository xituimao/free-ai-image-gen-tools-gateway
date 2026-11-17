#!/usr/bin/env bash
# ============================================================
# free-ai-image-gen-tools-gateway Docker one-click deployment script
# Usage: ./scripts/deploy-docker.sh [options]
# Options:
#   --name <container name>  Container name (default: free-ai-image-gen-tools-gateway)
#   --port <port>            Host port (default: 8799)
#   --data <directory>       Data volume mount directory (default: ./data)
#   --no-build               Skip build, use existing image directly
#   --help                   Show help
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Default parameters
CONTAINER_NAME="free-ai-image-gen-tools-gateway"
HOST_PORT=8799
DATA_DIR="$PROJECT_ROOT/data"
DO_BUILD=1

# Parse parameters
while [ $# -gt 0 ]; do
  case "$1" in
    --name) CONTAINER_NAME="$2"; shift 2 ;;
    --port) HOST_PORT="$2"; shift 2 ;;
    --data) DATA_DIR="$2"; shift 2 ;;
    --no-build) DO_BUILD=0; shift ;;
    --help|-h)
      echo "Usage: ./scripts/deploy-docker.sh [options]"
      echo "  --name <container name>     Container name (default: free-ai-image-gen-tools-gateway)"
      echo "  --port <port>               Host port (default: 8799)"
      echo "  --data <directory>          Data volume mount directory (default: ./data)"
      echo "  --no-build                  Skip build, use existing image directly"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "============================================"
echo "  free-ai-image-gen-tools-gateway Docker deployment"
echo "============================================"
echo "  Container name: $CONTAINER_NAME"
echo "  Port:           $HOST_PORT"
echo "  Data:           $DATA_DIR"
echo "============================================"

# 1. Build image
if [ $DO_BUILD -eq 1 ]; then
  echo ""
  echo "[1/4] Building Docker image..."
  docker build -t free-ai-image-gen-tools-gateway:latest .
  echo "  Image built"
else
  echo ""
  echo "[1/4] Skip build (--no-build)"
fi

# 2. Stop and remove old container
echo ""
echo "[2/4] Cleaning up old container..."
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
  echo "  Old container removed"
else
  echo "  No old container"
fi

# 3. Create data directory
echo ""
echo "[3/4] Preparing data directory..."
mkdir -p "$DATA_DIR"
echo "  Data directory: $DATA_DIR"

# 4. Start container
echo ""
echo "[4/4] Starting container..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p "$HOST_PORT:8799" \
  -v "$DATA_DIR:/data" \
  -e STORAGE_DIR=/data \
  free-ai-image-gen-tools-gateway:latest

echo ""
echo "============================================"
echo "  Deployment complete!"
echo "============================================"
echo "  Web console: http://127.0.0.1:$HOST_PORT/"
echo "  API docs:    http://127.0.0.1:$HOST_PORT/docs"
echo "  MCP endpoint: http://127.0.0.1:$HOST_PORT/mcp"
echo "  Container logs: docker logs -f $CONTAINER_NAME"
echo "  Stop:         docker stop $CONTAINER_NAME"
echo "  Restart:      docker restart $CONTAINER_NAME"
echo "  Data files:   $DATA_DIR"
echo "============================================"
echo ""
echo "Tip: on first use, fill in each channel's API Key on the web console 'Channel Management' page,"
echo "     or edit $DATA_DIR/../config.yaml (requires container restart to take effect)."
echo "     For external deployment, be sure to set admin_token (environment variable ADMIN_TOKEN)."
