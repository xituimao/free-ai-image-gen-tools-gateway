# free-ai-image-gen-tools-gateway Deployment Guide

> One-click script + complete guide, covering local personal use, cloud server deployment, Docker, systemd daemon.

---


## Table of Contents

1. [Quick Start (3 Steps)](#1-quick-start-3-steps)
2. [Local Deployment (Personal Use)](#2-local-deployment-personal-use)
3. [Cloud Server Deployment](#3-cloud-server-deployment)
   - [Method A: Docker (Recommended)](#method-a-docker-recommended)
   - [Method B: systemd + Nginx (Production Recommended)](#method-b-systemd--nginx-production-recommended)
   - [Method C: Direct Run (Simplest)](#method-c-direct-run-simplest)
4. [Configuration Guide](#4-configuration-guide)
5. [Management Command Reference](#5-management-command-reference)
6. [Integration with Other AI Agents](#6-integration-with-other-ai-agents)
7. [FAQ](#7-faq)

---


## 1. Quick Start (3 Steps)

```bash
# 1. Extract and enter the project
unzip free-ai-image-gen-tools-gateway.zip && cd free-ai-image-gen-tools-gateway

# 2. One-click install dependencies + generate configuration
./scripts/install.sh

# 3. One-click start
./scripts/start.sh
```

After startup, visit:
- Web console: http://127.0.0.1:8799/
- API documentation (Swagger): http://127.0.0.1:8799/docs
- MCP endpoint: http://127.0.0.1:8799/mcp

Out-of-the-box free channel is **pollinations** (no key required). Other channels can be enabled by filling in keys on the "Channel Management" page.

---


## 2. Local Deployment (Personal Use)

### Interactive Configuration (Recommended)

```bash
./scripts/configure.sh
```

Follow the prompts:
- Deployment mode: select `1` (local personal use)
- Various channel API Keys: fill as needed, leave blank to skip

### Manual Start/Stop

```bash
./scripts/start.sh      # Background start
./scripts/stop.sh       # Stop
./scripts/restart.sh    # Restart
./scripts/status.sh     # Check status
./scripts/logs.sh       # Real-time logs
./scripts/health.sh     # Health check
```

### Foreground Run (Debugging)

```bash
./run.sh
# or
python3 -m imggen.server
```

---


## 3. Cloud Server Deployment

### Prerequisites

1. A Linux cloud server (Ubuntu 20.04+/Debian 11+/CentOS 7+)
2. Open security group port: `8799` (or your custom port)
3. (Optional) Domain + SSL certificate for Nginx reverse proxy HTTPS

### Method A: Docker (Recommended)

```bash
# One-click build + deploy
./scripts/deploy-docker.sh

# Custom parameters
./scripts/deploy-docker.sh --name imgw --port 8080 --data /data/imgw
```

After deployment:
- Web console: http://ServerIP:8799/
- Data persistence in `./data/` directory (container restart does not lose data)
- Container auto-restart (`--restart unless-stopped`)

**Docker Management Commands:**
```bash
docker logs -f free-ai-image-gen-tools-gateway    # View logs
docker restart free-ai-image-gen-tools-gateway     # Restart
docker stop free-ai-image-gen-tools-gateway        # Stop
docker start free-ai-image-gen-tools-gateway       # Start
```

**Setting admin_token (required for external deployment):**
```bash
docker run -d --name free-ai-image-gen-tools-gateway \
  -p 8799:8799 \
  -v ./data:/data \
  -e ADMIN_TOKEN=your-key \
  free-ai-image-gen-tools-gateway:latest
```

### Method B: systemd + Nginx (Production Recommended)

```bash
# One-click install systemd service (boot start, auto-restart on crash)
sudo ./scripts/deploy-systemd.sh

# Custom parameters
sudo ./scripts/deploy-systemd.sh --user www-data --port 8799 --host 0.0.0.0
```

**Configure Nginx reverse proxy (domain + HTTPS):**
```bash
# Copy example configuration
sudo cp deploy/nginx.conf.example /etc/nginx/conf.d/imgw.conf

# Edit: modify server_name and certificate path
sudo vim /etc/nginx/conf.d/imgw.conf

# Test and reload
sudo nginx -t && nginx -s reload
```

**systemd Management Commands:**
```bash
sudo systemctl start free-ai-image-gen-tools-gateway      # Start
sudo systemctl stop free-ai-image-gen-tools-gateway       # Stop
sudo systemctl restart free-ai-image-gen-tools-gateway    # Restart
sudo systemctl status free-ai-image-gen-tools-gateway     # Status
sudo journalctl -u free-ai-image-gen-tools-gateway -f     # Real-time logs
sudo systemctl enable free-ai-image-gen-tools-gateway      # Boot start
sudo systemctl disable free-ai-image-gen-tools-gateway     # Disable boot start
```

**Uninstall:**
```bash
sudo ./scripts/deploy-systemd.sh --uninstall
```

### Method C: Direct Run (Simplest)

```bash
# Install dependencies
pip3 install -r requirements.txt

# Generate configuration
cp config.example.yaml config.yaml

# Modify config.yaml: set host to 0.0.0.0, set admin_token

# Background run
nohup python3 -m imggen.server > gateway.log 2>&1 &
```

---


## 4. Configuration Guide

### Configuration File Location

`config.yaml` (project root). First run automatically copies from `config.example.yaml`.

Environment variables can also override (higher priority than config file):

| Environment Variable | Corresponding Config | Description |
|----------------------|----------------------|-------------|
| `GEMINI_API_KEY` | providers.gemini.api_key | Google Gemini |
| `DASHSCOPE_API_KEY` | providers.bailian.api_key | Alibaba BaiLian |
| `SILICONFLOW_API_KEY` | providers.openai_compatible.siliconflow.api_key | SiliconFlow |
| `OPENAI_API_KEY` | providers.openai_compatible.openai.api_key | OpenAI |
| `HF_TOKEN` | providers.hf_space.hf_token | HuggingFace (optional) |
| `BING_COOKIE_U` | providers.bing.cookie_u | Bing Image Creator |
| `ADMIN_TOKEN` | server.admin_token | Management interface authentication |
| `IMGGW_BASE_URL` | — | MCP stdio mode gateway address |

### Core Configuration Items

```yaml
server:
  host: 127.0.0.1        # Local personal use; cloud server change to 0.0.0.0
  port: 8799              # Listening port
  admin_token: ""         # Management interface authentication (must set for external deployment)
  storage_dir: storage    # Image/history/log storage directory
  timeout: 120            # Single channel read timeout (seconds)
  default_chain:          # Default priority list for auto mode
    - pollinations
    - gemini
    - siliconflow
    - bailian
```

### Online Configuration (no need to edit yaml manually)

After startup, in the web console "Channel Management" page:
- View status of 9 channels (available/missing key/disabled/cooldown)
- Fill in API Key, default model, enable/disable
- Click "Save" to hot reload configuration, no restart needed
- Click "Self-check" to test channel connectivity

---


## 5. Management Command Reference

All commands are independent scripts; `ls scripts/` shows all capabilities, no need to memorize parameters:

| Command | Description |
|---------|-------------|
| `./scripts/install.sh` | Install dependencies + generate configuration (first use) |
| `./scripts/configure.sh` | Interactive configuration wizard |
| `./scripts/start.sh` | Background start |
| `./scripts/stop.sh` | Stop |
| `./scripts/restart.sh` | Restart |
| `./scripts/status.sh` | Status (PID/port/health check) |
| `./scripts/logs.sh` | Real-time logs |
| `./scripts/health.sh` | Health check |
| `./scripts/reload.sh` | Hot reload configuration (no restart) |
| `./scripts/uninstall.sh` | Stop and clean runtime files |
| `./scripts/deploy-docker.sh` | Docker one-click deployment |
| `./scripts/deploy-systemd.sh` | systemd one-click installation |

> All scripts internally delegate to `scripts/manage.sh`; to pass arguments, use `./scripts/manage.sh <command> [params]`.

### Hot Reload Configuration

After modifying `config.yaml`, no restart needed:
```bash
./scripts/reload.sh
# or
curl -X POST http://127.0.0.1:8799/admin/reload \
  -H "X-Admin-Token: your-token"   # required if admin_token set
```

---


## 6. Integration with Other AI Agents

### OpenAI-Compatible API

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8799", api_key="x")
client.images.generate(model="auto", prompt="one corgi",
                        extra_body={"session_id": "myproj"})
```

### MCP (Recommended)

**Streamable HTTP (same process as gateway):**
- URL: `http://127.0.0.1:8799/mcp`
- In Claude Desktop / Cursor / Cline etc. clients' mcpServers configuration, fill in URL

**stdio (client launches subprocess):**
```json
{
  "free-ai-image-gen-tools-gateway": {
    "command": "python",
    "args": ["-m", "imggen.mcp_server"],
    "env": { "IMGGW_BASE_URL": "http://127.0.0.1:8799" }
  }
}
```

MCP provides 6 tools: `generate_image`, `list_sessions`, `list_history`, `get_providers`, `configure_provider`, `test_provider`.

### CLI

```bash
python -m imggen.cli "one corgi" -s myproj    # Generate image (default command, can omit gen)
python -m imggen.cli models                    # List available channels/models
python -m imggen.cli serve                     # Start API + web gateway
```

---


## 7. FAQ

### Q: Cannot access after startup?
- Check if port is occupied: `lsof -i:8799`
- Cloud server: verify security group allows the port
- View logs: `./scripts/logs.sh`

### Q: pollinations often returns 429?
- Free channel has rate limits; wait a few seconds and retry
- Recommend configuring other channels (gemini/siliconflow etc.) as fallback; auto mode will try sequentially
- Adjust default priority list in "Channel Management" page

### Q: Where are images stored?
- Unified storage in `storage/sessions/<session-name>/images/`
- History records in `storage/sessions/<session-name>/history.jsonl`
- Usage logs in `storage/usage.jsonl`
- For cloud servers, recommend setting `storage_dir` to a mounted data disk

### Q: How to backup?
- Directly copy `storage/` directory and `config.yaml`
- Docker deployment: backup the mounted data directory (e.g., `./data/`)

### Q: Does management interface (/admin/reload, /v1/usage, /v1/clients) require authentication?
- If `admin_token` not set, only localhost (127.0.0.1) allowed
- If `admin_token` set, request header must include `X-Admin-Token: your-token`
- For external deployment, must set admin_token

### Q: MCP connection fails?
- Confirm gateway is running: `./scripts/status.sh`
- HTTP mode: URL must be `http://host:port/mcp` (cannot omit `/mcp`)
- stdio mode: ensure `python -m imggen.mcp_server` runs normally, and `IMGGW_BASE_URL` points to correct gateway address

---


## Project Structure

```
free-ai-image-gen-tools-gateway/
├── imggen/                  # Backend code
│   ├── server.py            # FastAPI gateway (OpenAI compatible + MCP + management interface)
│   ├── mcp_server.py        # MCP service (6 tools)
│   ├── registry.py          # Channel registration and auto-chain
│   ├── storage.py           # Session-based storage
│   ├── usage.py             # Usage logs
│   ├── catalog.py           # Channel metadata
│   ├── cli.py               # CLI
│   ├── config.py            # Configuration loading
│   └── providers/           # 9 channel adapters
├── web/
│   └── index.html           # Single-file web console
├── scripts/
│   ├── manage.sh            # Unified management script (delegated by independent scripts)
│   ├── install.sh configure.sh start.sh stop.sh restart.sh
│   ├── status.sh logs.sh health.sh reload.sh uninstall.sh
│   ├── deploy-docker.sh deploy-systemd.sh
│   ├── deploy-docker.sh     # Docker one-click deployment
│   └── deploy-systemd.sh    # systemd one-click installation
├── deploy/
│   ├── nginx.conf.example   # Nginx reverse proxy example
│   └── free-ai-image-gen-tools-gateway.service.example  # systemd service example
├── Dockerfile
├── config.example.yaml      # Configuration template
├── requirements.txt
├── run.sh                   # Simple startup script (foreground)
├── README.md                # Feature description
└── DEPLOY.md                # This file (deployment guide)
```
