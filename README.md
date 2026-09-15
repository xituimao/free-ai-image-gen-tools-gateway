# Free AI Image Gen Tools Gateway 统一生图网关

把多个**免费 / 低价**的在线生图渠道集成到**一个本地入口**：

- 对 AI Agent / 程序：暴露 **OpenAI 兼容的本地 API**，像调普通生图接口一样用，底层自动在各渠道间切换、故障转移。
- 对人：提供**网页控制台**，手动选渠道、多渠道并排对比。
- 另提供 **CLI** 命令行。
- **会话化存档**：生成/上传的图片统一保存在一个资源目录、按会话分子目录；历史记录可按提示词搜索、多维度排序、一键用原参数重生成。
- **本机与云服务器都能部署**（直跑 / Docker / Nginx 反代 / systemd 常驻）。
- **不需要本地部署任何大模型**，全部调用在线服务。

---

## 1. 快速开始

```bash
cd free-ai-image-gen-tools-gateway
pip install -r requirements.txt
cp config.example.yaml config.yaml      # 按需填入各渠道 key（不填也有免费通道）
python -m imggen.server                 # 或 ./run.sh
```

打开：

- 网页控制台： http://127.0.0.1:8799/
- 接口文档： http://127.0.0.1:8799/docs

> 开箱即用的免费通道是 **pollinations**（无需 key）。其余渠道在 `config.yaml` 填 key 后启用，改完配置执行 `POST /admin/reload` 热加载，无需重启。
>
> 管理接口安全：`/admin/reload` 若配置了 `server.admin_token`（或环境变量 `ADMIN_TOKEN`），需带请求头 `X-Admin-Token`；未配置时仅允许本机回环调用。所有图片统一归档到 `server.storage_dir`，按会话分子目录（见第 3 节）。

---

## 2. 给其他 AI Agent 调用（核心）

端点对齐 OpenAI Images API（`/v1/images/generations`、`/v1/models`，请求/响应字段一致），把 base_url 指向本地即可。另在响应里附带 `provider`、`chain_order`、`tried_before` 等便于排障的扩展字段。

### curl

```bash
# 自动链：按 config 里 default_chain 顺序，免费渠道优先，失败自动换
curl -X POST http://127.0.0.1:8799/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"prompt":"一只穿西装的柯基","size":"1024x1024"}'

# 指定渠道
-d '{"prompt":"...","model":"gemini"}'

# 自定义故障转移顺序（逐个尝试直到成功）
-d '{"prompt":"...","model":["pollinations","gemini","siliconflow/black-forest-labs/FLUX.2-flex"]}'
```

### Python（openai SDK，只改 base_url）

```python
from openai import OpenAI
c = OpenAI(base_url="http://127.0.0.1:8799", api_key="not-needed")
r = c.images.generate(model="auto", prompt="your prompt", size="1024x1024")
# r.data[0].b64_json
```

### 请求参数

| 字段 | 说明 |
|---|---|
| `prompt` | 提示词（必填） |
| `model` | `"auto"`（默认链）/ `"provider"` / `"provider/sub-model"` / 数组（自定义链） |
| `n` | 出图数量 |
| `size` | `"WxH"`，也兼容百炼的 `"W*H"` |
| `response_format` | `b64_json`（默认）或 `url`（返回会话图片的绝对地址） |
| `negative_prompt` | 负向提示词 |
| `seed` | 随机种子（固定 seed 且 n>1 时自动逐张偏移，避免重复图） |
| `session_id` | 归档到哪个会话，也可用请求头 `X-Session-Id`；不传走 `default` |

> `n` 单次最多 8；未知模型等 4xx 语义会返回对应 4xx 状态码，通道侧故障才返回 502。无论 b64/url，图片都会归档进当前会话。

返回（OpenAI 格式 + 扩展字段）：

```json
{ "object": "list", "created": 0, "provider": "pollinations", "model": "pollinations",
  "session_id": "default",
  "data": [ {"b64_json": "...."} ],
  "chain_order": ["pollinations"], "tried_before": [] }
```

### MCP（Model Context Protocol）接入

网关同时暴露 MCP 接口，Claude Desktop、Cursor、Cline、VS Code Copilot、Windsurf 等支持 MCP 的 agent 客户端可直接把生图当工具调用。

**工具列表**：`generate_image`、`list_sessions`、`list_history`、`get_providers`、`configure_provider`、`test_provider`。

两种传输：

1. **Streamable HTTP（推荐，与网关同进程）**：网关启动后即挂载在 `http://127.0.0.1:8799/mcp`，客户端配置 URL 即可。
2. **stdio（本地客户端拉起子进程）**：
   ```bash
   python -m imggen.mcp_server
   ```
   环境变量 `IMGGW_BASE_URL` 指定网关地址（默认 `http://127.0.0.1:8799`），`ADMIN_TOKEN` 用于写配置类工具。

MCP 调用会自动带 `X-Transport: mcp` 和客户端名，统一记入「接入方与日志」。

**客户端配置样例**（Claude Desktop / Cursor / Cline 等的 `mcpServers`）：

```json
{
  "free-ai-image-gen-tools-gateway-http": {
    "url": "http://127.0.0.1:8799/mcp"
  },
  "free-ai-image-gen-tools-gateway-stdio": {
    "command": "python",
    "args": ["-m", "imggen.mcp_server"],
    "env": { "IMGGW_BASE_URL": "http://127.0.0.1:8799" }
  }
}
```

> 二选一即可；HTTP 模式要求网关已在运行，stdio 模式由客户端拉起子进程（网关仍需单独运行）。

---

## 3. CLI

```bash
python -m imggen.cli models                       # 全部渠道及可用状态
python -m imggen.cli "水墨山水"                    # 走默认链
python -m imggen.cli "赛博城市" -p gemini          # 指定渠道
python -m imggen.cli "猫" -p pollinations,gemini   # 顺序 fallback
python -m imggen.cli "猫" --size 768x512 -o c.png  # 指定尺寸/额外复制
python -m imggen.cli "猫" -s myproj                # 归档到指定会话
python -m imggen.cli serve                         # 启动网关
```

---

## 4. 已内置渠道

| provider | 类型 | 凭证 | 说明 |
|---|---|---|---|
| `pollinations` | 免费 | 无 | HTTP 直出，默认保底通道；高频会 429，稍候即可 |
| `gemini` | 免费额度 | AI Studio key | Nano Banana，文字渲染强；https://aistudio.google.com/apikey |
| `siliconflow` | 低价 | 硅基流动 key | FLUX.2 [flex] 约 ¥0.035/张、Z-Image-Turbo ¥0.1/张 |
| `openai` | 付费 | OpenAI key | gpt-image-1 |
| `relay` | 低价 | 自填 | 任意第三方 OpenAI 兼容中转，自行甄别 |
| `bailian` | 低价/送额度 | DashScope key | 通义万相、z-image-turbo；新用户送免费张数 |
| `hf_space` | 免费 | 可选 HF token | 云端跑 FLUX Schnell / SD3.5，ZeroGPU 匿名有每日秒数配额 |
| `perchance` | 免费 | 无 | 逆向通道，尽力而为，可能随官网变化 |
| `bing` | 免费 | cookie `_U` | Bing Image Creator（DALL-E 3） |

key 也可用环境变量提供：`GEMINI_API_KEY`、`DASHSCOPE_API_KEY`、
`SILICONFLOW_API_KEY`、`OPENAI_API_KEY`、`HF_TOKEN`、`BING_COOKIE_U`。

### 渠道总览与在线配置（不必手改 yaml）

- 网页控制台 →「渠道管理」：顶部数字卡汇总「可用 / 未配置 / 冷却 / 总数」，
  每个渠道一张卡，显示状态点、类型（免费/免费额度/低价/付费/中转）、默认模型、
  模型列表、所需凭证；可直接填 key、选默认模型、拨动启用开关，**保存即热加载生效**
  （自动写回 `config.yaml`；凭证框留空表示不修改，不会覆盖已填值）。「自检」按钮
  做不消耗额度的可用性检查。
- API：
  - `GET /v1/providers`：渠道状态汇总（凭证只回「是否已设置」，不回明文）；
  - `POST /v1/providers/config`：在线写回配置，body `{"updates":{"gemini":{"api_key":"...","enabled":true}}}`；
  - `POST /v1/providers/{name}/test`：轻量自检。
- 写配置属于管理操作：配置了 `admin_token` 时需带 `X-Admin-Token` 头；未配置时仅本机回环放行。

历史记录里每条都**显著标注是哪个第三方渠道出的图**（如 `pollinations` / `gemini`），
「生成 / 上传」仅作为次要动作标签。

---

## 5. 自动模式（优先列表，依次尝试直到一个可用）

请求时 `model` 传 `"auto"`（或不传）即进入自动模式。优先列表这样生成：

1. `config.yaml` 的 `server.default_chain` 作为**显式优先骨架**，按你写的顺序排前面；
2. 其余**当前可用**（免费或已填凭证）的通道自动补到后面、免费优先——新配渠道
   不用手动加列表也会被自动模式用到；
3. 不可用（未启用/缺 key）的通道直接剔除，不做无意义尝试；
4. 刚失败的通道进入约 30 秒冷却，自动排到最后。

`config.yaml` 中：

```yaml
server:
  default_chain: [pollinations, gemini, siliconflow, bailian]
```

执行时按列表逐个尝试：某个渠道报错 / 超时 / 限流就自动切下一个，直到一个成功；
全部失败才返回错误并附每个渠道原因。返回带 `chain_order`（本次尝试顺序）和
`tried_before`（成功前试过哪些）。查看当前自动链：`GET /v1/chain`。
**建议把免费渠道排前面、付费渠道兜底。**

---

## 6. 多渠道对比

- 网页控制台「多渠道对比」标签：勾选多个渠道，同一 prompt 并发出图、并排查看下载。
- 接口：`POST /v1/images/compare`，`model` 传数组。对比结果同样归档到当前会话。

---

## 7. 数据与文件保存（图 / 历史存哪）

所有图片统一保存在 `server.storage_dir`（默认项目下 `storage/`，云上建议指向数据盘绝对路径），按会话分子目录：

```
storage/sessions/<session_id>/
├── meta.json                 # 会话标题、创建时间
├── history.jsonl             # 每行一条记录（JSON）
└── images/
    ├── gen_xxxx.jpg          # 生成的图（gen_ 前缀）
    └── up_xxxx.png           # 上传的图（up_ 前缀）
```

`history.jsonl` 每条记录包含：时间戳、来源（generate/upload）、prompt、负向词、尺寸、n、seed、**生成渠道 provider**、文件名列表、字节数。可直接 grep / 用程序解析。

会话与历史相关接口：

| 接口 | 作用 |
|---|---|
| `GET /v1/sessions` | 列出全部会话（标题、图片数、最新时间） |
| `POST /v1/sessions` | 新建会话 `{title}` |
| `POST /v1/sessions/{sid}/rename` | 改名 |
| `GET /v1/sessions/{sid}/history?search=&sort=` | 历史，支持搜索与排序 |
| `POST /v1/sessions/{sid}/upload` | 上传图片（multipart，单张 ≤10MB） |
| `GET /v1/sessions/{sid}/images/{name}` | 取会话图片 |

`sort` 可选：`ts_desc/ts_asc`、`provider_asc/provider_desc`、`size_desc/size_asc`、`n_desc/n_asc`。网页控制台「历史」标签提供搜索框、排序下拉、缩略图预览（点击放大）、下载与「用此参数重生成」。

> 会话内容是你的资产，程序不会自动删除；如需清理，直接删除对应会话目录即可。

---

## 8. 部署到云服务器（本机 / 云一致）

代码本身跨平台，本机与云服务器同一套。云端对外提供按下面任一方式，**上线前对照安全清单**。

**方式 A：直接运行**
```bash
pip install -r requirements.txt
# config.yaml: host 改 0.0.0.0，设置 admin_token；云安全组放行 8799
python -m imggen.server
```

**方式 B：Docker（推荐，数据用卷持久化）**
```bash
docker build -t free-ai-image-gen-tools-gateway .
docker run -d --name imgw -p 8799:8799 \
  -e ADMIN_TOKEN=change-me \
  -v /data/imgw:/data free-ai-image-gen-tools-gateway
```

**方式 C：Nginx + systemd（域名/HTTPS 常驻，生产推荐）**
- `deploy/nginx.conf.example`：反代示例，已处理 `X-Forwarded-*` 与 SSE；
- `deploy/free-ai-image-gen-tools-gateway.service.example`：开机自启、崩溃自动重启。
- 此时 `config.public_base_url` 可填 `https://你的域名`，`forwarded_allow_ips` 按需放开。

**云端安全清单**
1. 务必设置 `admin_token`（或 ADMIN_TOKEN），否则管理接口在对外时不可用/仅本机；
2. 云安全组只放行必要端口，优先用 Nginx + HTTPS 对外、网关本身不直接暴露；
3. 各渠道 key 优先用环境变量注入，不写进会随包带走的 config.yaml；
4. `storage_dir` 指向可持久化/可备份的数据盘，避免容器重建丢图。

---

## 9. 扩展一个新渠道（开发者）

1. 在 `imggen/providers/` 新建文件，继承 `BaseProvider`，实现 `available()`
   与 `_generate_once()`（返回 `list[bytes]`）。
2. 在 `imggen/registry.py` 的 `_build()` 中实例化。
3. 在 `config.example.yaml` 增加对应配置。

OpenAI 兼容的新渠道无需写代码：直接在 `openai_compatible` 下加一个子项，
填 base_url / key / models 即可。

---

## 10. 注意事项

- **免费通道都有速率/配额约束**：限流（429 / ZeroGPU quota）时网关会自动切换或稍后重试；稳定批量生产建议配一个低价 API（硅基流动 / 百炼）。
- **网页逆向通道**（perchance / bing）依赖对方前端结构，可能随官网更新失效，属尽力而为。
- **商用版权**：多数免费生成渠道未明确授予商用版权，对客户交付的关键素材请走有商用授权的付费渠道。
- 本服务默认只监听 `127.0.0.1`；若要让局域网/其他机器调用，把 `server.host` 改为 `0.0.0.0`，并自行做好访问控制。

## 目录结构

```
free-ai-image-gen-tools-gateway/
├── run.sh
├── Dockerfile
├── requirements.txt
├── config.example.yaml
├── imggen/
│   ├── config.py          # 配置加载 + 环境变量 + 热加载
│   ├── registry.py        # 渠道注册与路由
│   ├── storage.py         # 会话化存储 / 历史检索
│   ├── server.py          # FastAPI 网关
│   ├── cli.py             # 命令行
│   └── providers/         # 各渠道适配器
├── web/index.html         # 网页控制台
├── deploy/                # nginx / systemd 部署示例
└── storage/               # 统一资源根（sessions/<会话>/），运行后生成
```
