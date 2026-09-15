# free-ai-image-gen-tools-gateway 部署指南

> 一键脚本 + 完整指南，覆盖本机自用、云服务器部署、Docker、systemd 常驻。

---

## 目录

1. [快速开始（3 步启动）](#1-快速开始3-步启动)
2. [本机部署（个人自用）](#2-本机部署个人自用)
3. [云服务器部署](#3-云服务器部署)
   - [方式 A：Docker（推荐）](#方式-adocker推荐)
   - [方式 B：systemd + Nginx（生产推荐）](#方式-bsystemd--nginx生产推荐)
   - [方式 C：直接运行（最简单）](#方式-c直接运行最简单)
4. [配置指南](#4-配置指南)
5. [管理命令参考](#5-管理命令参考)
6. [给其他 AI Agent 接入](#6-给其他-ai-agent-接入)
7. [常见问题](#7-常见问题)

---

## 1. 快速开始（3 步启动）

```bash
# 1. 解压并进入项目
unzip free-ai-image-gen-tools-gateway.zip && cd free-ai-image-gen-tools-gateway

# 2. 一键安装依赖 + 生成配置
./scripts/install.sh

# 3. 一键启动
./scripts/start.sh
```

启动后访问：
- 网页控制台：http://127.0.0.1:8799/
- API 文档（Swagger）：http://127.0.0.1:8799/docs
- MCP 端点：http://127.0.0.1:8799/mcp

开箱即用的免费通道是 **pollinations**（无需 key）。其余渠道在「渠道管理」页填 key 后启用。

---

## 2. 本机部署（个人自用）

### 交互式配置（推荐）

```bash
./scripts/configure.sh
```

按提示选择：
- 部署模式：选 `1`（本机自用）
- 各渠道 API Key：按需填写，留空跳过

### 手动启动/停止

```bash
./scripts/start.sh      # 后台启动
./scripts/stop.sh       # 停止
./scripts/restart.sh    # 重启
./scripts/status.sh     # 查看状态
./scripts/logs.sh       # 实时日志
./scripts/health.sh     # 健康检查
```

### 前台运行（调试用）

```bash
./run.sh
# 或
python3 -m imggen.server
```

---

## 3. 云服务器部署

### 前置准备

1. 一台 Linux 云服务器（Ubuntu 20.04+ / Debian 11+ / CentOS 7+）
2. 开放安全组端口：`8799`（或你自定义的端口）
3. （可选）域名 + SSL 证书，用于 Nginx 反代 HTTPS

### 方式 A：Docker（推荐）

```bash
# 一键构建 + 部署
./scripts/deploy-docker.sh

# 自定义参数
./scripts/deploy-docker.sh --name imgw --port 8080 --data /data/imgw
```

部署完成后：
- 网页控制台：http://服务器IP:8799/
- 数据持久化在 `./data/` 目录（容器重启不丢失）
- 容器自动重启（`--restart unless-stopped`）

**Docker 管理命令：**
```bash
docker logs -f free-ai-image-gen-tools-gateway    # 查看日志
docker restart free-ai-image-gen-tools-gateway     # 重启
docker stop free-ai-image-gen-tools-gateway        # 停止
docker start free-ai-image-gen-tools-gateway       # 启动
```

**设置 admin_token（对外部署必须）：**
```bash
docker run -d --name free-ai-image-gen-tools-gateway \
  -p 8799:8799 \
  -v ./data:/data \
  -e ADMIN_TOKEN=你的密钥 \
  free-ai-image-gen-tools-gateway:latest
```

### 方式 B：systemd + Nginx（生产推荐）

```bash
# 一键安装 systemd 服务（开机自启、崩溃自动重启）
sudo ./scripts/deploy-systemd.sh

# 自定义参数
sudo ./scripts/deploy-systemd.sh --user www-data --port 8799 --host 0.0.0.0
```

**配置 Nginx 反代（域名 + HTTPS）：**
```bash
# 复制示例配置
sudo cp deploy/nginx.conf.example /etc/nginx/conf.d/imgw.conf

# 编辑：修改 server_name 和证书路径
sudo vim /etc/nginx/conf.d/imgw.conf

# 测试并重载
sudo nginx -t && nginx -s reload
```

**systemd 管理命令：**
```bash
sudo systemctl start free-ai-image-gen-tools-gateway      # 启动
sudo systemctl stop free-ai-image-gen-tools-gateway       # 停止
sudo systemctl restart free-ai-image-gen-tools-gateway    # 重启
sudo systemctl status free-ai-image-gen-tools-gateway     # 状态
sudo journalctl -u free-ai-image-gen-tools-gateway -f     # 实时日志
sudo systemctl enable free-ai-image-gen-tools-gateway      # 开机自启
sudo systemctl disable free-ai-image-gen-tools-gateway     # 取消开机自启
```

**卸载：**
```bash
sudo ./scripts/deploy-systemd.sh --uninstall
```

### 方式 C：直接运行（最简单）

```bash
# 安装依赖
pip3 install -r requirements.txt

# 生成配置
cp config.example.yaml config.yaml

# 修改 config.yaml：host 改为 0.0.0.0，设置 admin_token

# 后台运行
nohup python3 -m imggen.server > gateway.log 2>&1 &
```

---

## 4. 配置指南

### 配置文件位置

`config.yaml`（项目根目录）。首次运行自动从 `config.example.yaml` 复制生成。

也可以用环境变量覆盖（优先级高于配置文件）：

| 环境变量 | 对应配置 | 说明 |
|---------|---------|------|
| `GEMINI_API_KEY` | providers.gemini.api_key | Google Gemini |
| `DASHSCOPE_API_KEY` | providers.bailian.api_key | 阿里百炼 |
| `SILICONFLOW_API_KEY` | providers.openai_compatible.siliconflow.api_key | 硅基流动 |
| `OPENAI_API_KEY` | providers.openai_compatible.openai.api_key | OpenAI |
| `HF_TOKEN` | providers.hf_space.hf_token | HuggingFace（可选） |
| `BING_COOKIE_U` | providers.bing.cookie_u | Bing Image Creator |
| `ADMIN_TOKEN` | server.admin_token | 管理接口鉴权 |
| `IMGGW_BASE_URL` | — | MCP stdio 模式的网关地址 |

### 核心配置项

```yaml
server:
  host: 127.0.0.1        # 本机自用；云服务器改为 0.0.0.0
  port: 8799              # 监听端口
  admin_token: ""         # 管理接口鉴权（对外部署必须设置）
  storage_dir: storage    # 图片/历史/日志存储目录
  timeout: 120            # 单通道读取超时（秒）
  default_chain:          # 自动模式默认优先列表
    - pollinations
    - gemini
    - siliconflow
    - bailian
```

### 在线配置（不必手改 yaml）

启动后在网页控制台「渠道管理」页：
- 查看 9 个渠道的状态（可用/缺 key/禁用/冷却中）
- 填写 API Key、默认模型、启用/禁用
- 点击「保存」自动热加载，无需重启
- 点击「自检」测试渠道连通性

---

## 5. 管理命令参考

所有命令都是独立脚本，`ls scripts/` 即可看到全部能力，无需记参数：

| 命令 | 说明 |
|------|------|
| `./scripts/install.sh` | 安装依赖 + 生成配置（首次使用） |
| `./scripts/configure.sh` | 交互式配置向导 |
| `./scripts/start.sh` | 后台启动 |
| `./scripts/stop.sh` | 停止 |
| `./scripts/restart.sh` | 重启 |
| `./scripts/status.sh` | 状态（PID/端口/健康检查） |
| `./scripts/logs.sh` | 实时日志 |
| `./scripts/health.sh` | 健康检查 |
| `./scripts/reload.sh` | 热加载配置（不重启） |
| `./scripts/uninstall.sh` | 停止并清理运行时文件 |
| `./scripts/deploy-docker.sh` | Docker 一键部署 |
| `./scripts/deploy-systemd.sh` | systemd 一键安装 |

> 以上脚本内部均委托给 `scripts/manage.sh`，如需传参可直接用 `./scripts/manage.sh <命令> [参数]`。

### 热加载配置

修改 `config.yaml` 后，无需重启：
```bash
./scripts/reload.sh
# 或
curl -X POST http://127.0.0.1:8799/admin/reload \
  -H "X-Admin-Token: 你的token"   # 设了 admin_token 时需要
```

---

## 6. 给其他 AI Agent 接入

### OpenAI 兼容 API

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8799", api_key="x")
client.images.generate(model="auto", prompt="一只柯基",
                        extra_body={"session_id": "myproj"})
```

### MCP（推荐）

**Streamable HTTP（与网关同进程）：**
- URL：`http://127.0.0.1:8799/mcp`
- 在 Claude Desktop / Cursor / Cline 等客户端的 mcpServers 配置中填入 URL

**stdio（客户端拉起子进程）：**
```json
{
  "free-ai-image-gen-tools-gateway": {
    "command": "python",
    "args": ["-m", "imggen.mcp_server"],
    "env": { "IMGGW_BASE_URL": "http://127.0.0.1:8799" }
  }
}
```

MCP 提供 6 个工具：`generate_image`、`list_sessions`、`list_history`、`get_providers`、`configure_provider`、`test_provider`。

### CLI

```bash
python -m imggen.cli "一只柯基" -s myproj    # 生成图片（默认命令，可省略 gen）
python -m imggen.cli models                    # 列出可用渠道/模型
python -m imggen.cli serve                     # 启动 API + 网页网关
```

---

## 7. 常见问题

### Q: 启动后访问不了？
- 检查端口是否被占用：`lsof -i:8799`
- 云服务器检查安全组是否放行端口
- 查看日志：`./scripts/logs.sh`

### Q: pollinations 经常 429？
- 免费通道有速率限制，稍等几秒重试
- 建议配置其他渠道（gemini/siliconflow 等）作为兜底，自动模式会依次尝试
- 在「渠道管理」页调整默认优先列表

### Q: 图片存在哪里？
- 统一存储在 `storage/sessions/<会话名>/images/`
- 历史记录在 `storage/sessions/<会话名>/history.jsonl`
- 使用日志在 `storage/usage.jsonl`
- 云服务器建议将 `storage_dir` 指向挂载的数据盘

### Q: 如何备份？
- 直接复制 `storage/` 目录和 `config.yaml`
- Docker 部署：备份挂载的数据目录（如 `./data/`）

### Q: 管理接口（/admin/reload、/v1/usage、/v1/clients）需要鉴权吗？
- 未设置 `admin_token` 时，仅允许本机（127.0.0.1）调用
- 设置 `admin_token` 后，需在请求头带 `X-Admin-Token: 你的token`
- 对外部署务必设置 admin_token

### Q: MCP 连接失败？
- 确认网关已启动：`./scripts/status.sh`
- HTTP 模式：URL 必须是 `http://host:port/mcp`（不能少 /mcp）
- stdio 模式：确认 `python -m imggen.mcp_server` 能正常运行，且 `IMGGW_BASE_URL` 指向正确的网关地址

---

## 项目结构

```
free-ai-image-gen-tools-gateway/
├── imggen/                  # 后端代码
│   ├── server.py            # FastAPI 网关（OpenAI 兼容 + MCP + 管理接口）
│   ├── mcp_server.py        # MCP 服务（6 个工具）
│   ├── registry.py          # 渠道注册与自动链
│   ├── storage.py           # 会话化存储
│   ├── usage.py             # 使用日志
│   ├── catalog.py           # 渠道元数据
│   ├── cli.py               # CLI
│   ├── config.py            # 配置加载
│   └── providers/           # 9 个渠道适配器
├── web/
│   └── index.html           # 单文件网页控制台
├── scripts/
│   ├── manage.sh            # 统一管理脚本（被各独立脚本委托）
│   ├── install.sh configure.sh start.sh stop.sh restart.sh
│   ├── status.sh logs.sh health.sh reload.sh uninstall.sh
│   ├── deploy-docker.sh deploy-systemd.sh
│   ├── deploy-docker.sh     # Docker 一键部署
│   └── deploy-systemd.sh    # systemd 一键安装
├── deploy/
│   ├── nginx.conf.example   # Nginx 反代示例
│   └── free-ai-image-gen-tools-gateway.service.example  # systemd service 示例
├── Dockerfile
├── config.example.yaml      # 配置模板
├── requirements.txt
├── run.sh                   # 简单启动脚本（前台）
├── README.md                # 功能说明
└── DEPLOY.md                # 本文件（部署指南）
```
