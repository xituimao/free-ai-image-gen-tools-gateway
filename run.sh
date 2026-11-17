#!/usr/bin/env bash
# One-click start for Unified Image Generation Gateway (API + web console)
set -e
cd "$(dirname "$0")"

PY=python3
command -v $PY >/dev/null 2>&1 || PY=python

# Auto install dependencies on first run
$PY -c "import fastapi, uvicorn, httpx, yaml, multipart" 2>/dev/null || \
  $PY -m pip install -r requirements.txt

# Generate config.yaml from template if missing
[ -f config.yaml ] || cp config.example.yaml config.yaml
echo "Web console: http://127.0.0.1:8799/"
exec $PY -m imggen.server
