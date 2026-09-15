#!/usr/bin/env bash
# 一键启动统一生图网关（API + 网页控制台）
set -e
cd "$(dirname "$0")"

PY=python3
command -v $PY >/dev/null 2>&1 || PY=python

# 首次运行自动安装依赖
$PY -c "import fastapi, uvicorn, httpx, yaml, multipart" 2>/dev/null || \
  $PY -m pip install -r requirements.txt

# 没有 config.yaml 就从模板生成
[ -f config.yaml ] || cp config.example.yaml config.yaml
echo "网页控制台: http://127.0.0.1:8799/"
exec $PY -m imggen.server
