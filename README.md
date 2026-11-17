# Free AI Image Gen Tools Gateway Unified Image Generation Gateway

Integrate multiple **free/low-cost** online image generation channels into **one local entry point**:

- For AI Agents / programs: expose **OpenAI-compatible local API**, use it like a regular image generation API, with automatic channel switching and failover underneath.
- For humans: provide a **web console**, manually select channels, compare multiple channels side by side.
- Also provides a **CLI** command line.
- **Session-based archiving**: generated/uploaded images are uniformly stored in a resource directory, organized by session subdirectories; history records can be searched by prompt, multi-dimensional sorted, and one-click regenerated with original parameters.
- **Can be deployed on local machines and cloud servers** (direct run / Docker / Nginx reverse proxy / systemd daemon).
- **No need to deploy any large models locally**; all calls are to online services.

---

## 1. Quick Start

```bash
cd free-ai-image-gen-tools-gateway
pip install -r requirements.txt
cp config.example.yaml config.yaml      # Fill in channel keys as needed (free channels available without keys)
python -m imggen.server                 # or ./run.sh
```

Open:

- Web console: http://127.0.0.1:8799/
- API documentation: http://127.0.0.1:8799/docs

> The out-of-the-box free channel is **pollinations** (no key required). Other channels are enabled by filling in keys in `config.yaml`; after modifying the configuration, execute `POST /admin/reload` to hot reload, no restart needed.
>
> Management interface security: if `server.admin_token` is configured (or environment variable `ADMIN_TOKEN`), requests must include the header `X-Admin-Token`; if not configured, only local loopback calls are allowed. All images are uniformly archived to `server.storage_dir`, organized by session subdirectories (see Section 3).

---

## 2. Calling from Other AI Agents (Core)

Endpoints align with OpenAI Images API (`/v1/images/generations`, `/v1/models`, request/response fields consistent); simply point `base_url` to localhost. Additionally, the response includes extended fields such as `provider`, `chain_order`, `tried_before` for easier troubleshooting.

### curl

```bash
# Automatic chain: follow the order in config's default_chain, prioritize free channels, automatically switch on failure
curl -X POST http://127.0.0.1:8799/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a corgi wearing a suit","size":"1024x1024"}'

# Specify channel
-d '{"prompt":"...","model":"gemini"}'

# Custom failover order (try each until success)
-d '{"prompt":"...","model":["pollinations","gemini","siliconflow/black-forest-labs/FLUX.2-flex"]}'
```

### Python (OpenAI SDK, just change base_url)

```python
from openai import OpenAI
c = OpenAI(base_url="http://127.0.0.1:8799", api_key="not-needed")
r = c.images.generate(model="auto", prompt="your prompt", size="1024x1024")
# r.data[0].b64_json
```

### Request Parameters

| Field | Description |
|---|---|
| `prompt` | Prompt (required) |
| `model` | `"auto"` (default chain) / `"provider"` / `"provider/sub-model"` / array (custom chain) |
| `n` | Number of images |
| `size` | `"WxH"`, also compatible with Bailian's `"W*H"` |
| `response_format` | `b64_json` (default) or `url` (returns the absolute URL of the session image) |
| `negative_prompt` | Negative prompt |
| `seed` | Random seed (fixed seed with n>1 automatically offsets per image to avoid duplicates) |
| `session_id` | Session to archive to, also available via request header `X-Session-Id`; defaults to `default` if not specified |

> `n` is limited to 8 per call; unknown model 4xx errors return corresponding 4xx status codes, while channel failures return 502. Whether b64/url, images are archived into the current session.

Response (OpenAI format + extended fields):

```json
{ "object": "list", "created": 0, "provider": "pollinations", "model": "pollinations",
  "session_id": "default",
  "data": [ {"b64_json": "...."} ],
  "chain_order": ["pollinations"], "tried_before": [] }
```

### MCP (Model Context Protocol) Access

The gateway also exposes an MCP interface, allowing MCP-supported agent clients such as Claude Desktop, Cursor, Cline, VS Code Copilot, Windsurf, etc., to directly use image generation as a tool.

**Tool list**: `generate_image`, `list_sessions`, `list_history`, `get_providers`, `configure_provider`, `test_provider`.

Two transport methods:

1. **Streamable HTTP (recommended, same process as gateway)**: After gateway startup, it is mounted at `http://127.0.0.1:8799/mcp`; clients just need to configure the URL.
2. **stdio (local client launches a subprocess)**:
   ```bash
   python -m imggen.mcp_server
   ```
   Environment variable `IMGGW_BASE_URL` specifies the gateway address (default `http://127.0.0.1:8799`); `ADMIN_TOKEN` is used for write-configuration tools.

MCP calls automatically include `X-Transport: mcp` and the client name, uniformly logged under "Access Method and Logs".

**Client configuration example** (for Claude Desktop / Cursor / Cline, etc.'s `mcpServers`):

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

> Either method works; HTTP mode requires the gateway to be running, while stdio mode launches a subprocess via the client (the gateway still needs to run separately).

---

## 3. CLI

```bash
python -m imggen.cli models                       # List all channels and their status
python -m imggen.cli "watercolor mountain water"   # Use default chain (translated prompt)
python -m imggen.cli "cyber city" -p gemini        # Specify channel
python -m imggen.cli "cat" -p pollinations,gemini   # Fallback chain
python -m imggen.cli "cat" --size 768x512 -o c.png  # Specify size/extra copy
python -m imggen.cli "cat" -s myproj                # Archive to specified session
python -m imggen.cli serve                          # Start gateway
```

---

## 4. Built-in Channels

| provider | Type | Credentials | Description |
|---|---|---|---|
| `pollinations` | Free | None | HTTP direct output, default fallback channel; may encounter 429 under high frequency, just wait a moment |
| `gemini` | Free quota | AI Studio key | Nano Banana, strong text rendering; https://aistudio.google.com/apikey |
| `siliconflow` | Low price | SiliconFlow key | FLUX.2 [flex] approx ¥0.035/image, Z-Image-Turbo ¥0.1/image |
| `openai` | Paid | OpenAI key | gpt-image-1 |
| `relay` | Low price | Self-filled | Any third-party OpenAI-compatible forwarder, use discernment |
| `bailian` | Low price/quota | DashScope key | Tongyi Wanxiang, z-image-turbo; new users get free trial amounts |
| `hf_space` | Free | Optional HF token | Run FLUX Schnell / SD3.5 in the cloud, ZeroGPU anonymous has daily second quotas |
| `perchance` | Free | None | Reverse channel, best effort, may change with official website |
| `bing` | Free | Cookie `_U` | Bing Image Creator (DALL-E 3) |

Keys can also be provided via environment variables: `GEMINI_API_KEY`, `DASHSCOPE_API_KEY`, `SILICONFLOW_API_KEY`, `OPENAI_API_KEY`, `HF_TOKEN`, `BING_COOKIE_U`.

### Channel Overview and Online Configuration (no need to manually edit yaml)

- Web console → "Channel Management": top-number cards summarize "Available / Unconfigured / Cooldown / Total"; each channel has a card showing status dot, type (free/free quota/low price/paid/forwarder), default model, model list, required credentials; you can directly fill in keys, select default model, toggle enable switch, and saving takes effect immediately via hot reload (automatically writes back to `config.yaml`; leaving the credential field blank means no modification, won't overwrite existing values). The "Self-check" button performs availability checks without consuming quota.
- API:
  - `GET /v1/providers`: Channel status summary (credentials only return "whether set", not plaintext);
  - `POST /v1/providers/config`: Online write-back configuration, body `{"updates":{"gemini":{"api_key":"...","enabled":true}}}`;
  - `POST /v1/providers/{name}/test`: Lightweight self-check.
- Writing configuration is a management operation: if `admin_token` is configured, requests must include `X-Admin-Token` header; if not configured, only local loopback is allowed.

In history records, each entry prominently labels which third-party channel generated the image (e.g., `pollinations` / `gemini`); "generation/upload" is only a secondary action tag.

---

## 5. Automatic Mode (Priority List, Try Until One Succeeds)

When requesting with `model` set to `"auto"` (or omitted), automatic mode is engaged. The priority list is generated as follows:

1. The `server.default_chain` in `config.yaml` serves as the **explicit priority skeleton**, ordered as written;
2. The remaining **currently available** (free or with filled credentials) channels are automatically appended after, with free channels prioritized—newly configured channels are automatically used by automatic mode without manually adding to the list;
3. Unavailable channels (not enabled/missing keys) are removed outright, avoiding meaningless attempts;
4. Recently failed channels enter a ~30-second cooldown and are automatically moved to the end.

In `config.yaml`:

```yaml
server:
  default_chain: [pollinations, gemini, siliconflow, bailian]
```

Execution proceeds by trying channels in list order: if a channel errors, times out, or is rate-limited, automatically switch to the next until one succeeds; if all fail, return an error with the reason for each channel. The response includes `chain_order` (this attempt's order) and `tried_before` (channels tried before success). View current automatic chain via `GET /v1/chain`.
**Recommendation: Put free channels at the front, paid channels as fallback.**

---

## 6. Multi-Channel Comparison

- Web console "Multi-Channel Comparison" tab: select multiple channels, simultaneously send images for the same prompt, and view/download side by side.
- Interface: `POST /v1/images/compare`, pass `model` as an array. Comparison results are also archived into the current session.

---

## 7. Data and File Storage (Where Images/History Are Saved)

All images are uniformly saved in `server.storage_dir` (default project `storage/`; on cloud servers, recommend pointing to an absolute path on a data disk), organized by session subdirectories:

```
storage/sessions/<session_id>/
├── meta.json                 # Session title, creation time
├── history.jsonl             # Each line is one record (JSON)
└── images/
    ├── gen_xxxx.jpg          # Generated image (gen_ prefix)
    └── up_xxxx.png           # Uploaded image (up_ prefix)
```

Each record in `history.jsonl` contains: timestamp, source (generate/upload), prompt, negative prompt, dimensions, n, seed, **generation channel provider**, filename list, byte count; can be directly grepped or parsed by programs.

Session and history-related interfaces:

| Interface | Purpose |
|---|---|
| `GET /v1/sessions` | List all sessions (title, image count, latest time) |
| `POST /v1/sessions` | Create a new session `{title}` |
| `POST /v1/sessions/{sid}/rename` | Rename |
| `GET /v1/sessions/{sid}/history?search=&sort=` | History, supports search and sorting |
| `POST /v1/sessions/{sid}/upload` | Upload image (multipart, single ≤10MB) |
| `GET /v1/sessions/{sid}/images/{name}` | Retrieve session image |

`sort` options: `ts_desc/ts_asc`, `provider_asc/provider_desc`, `size_desc/size_asc`, `n_desc/n_asc`. The web console "History" tab provides a search box, sort dropdown, thumbnail preview (click to enlarge), download, and "Regenerate with these parameters".

> Session content is your assets; the program does not auto-delete; to clean up, simply delete the corresponding session directory.

---

## 8. Deployment to Cloud Servers (Local / Cloud Consistent)

The code itself is cross-platform; local machines and cloud servers use the same set. Cloud servers provide external access via any of the following methods; **refer to the security checklist before going live**.

**Method A: Direct Run**
```bash
pip install -r requirements.txt
# config.yaml: set host to 0.0.0.0, set admin_token; open port 8799 in cloud security group
python -m imggen.server
```

**Method B: Docker (Recommended, data persisted via volumes)**
```bash
docker build -t free-ai-image-gen-tools-gateway .
docker run -d --name imgw -p 8799:8799 \
  -e ADMIN_TOKEN=change-me \
  -v /data/imgw:/data free-ai-image-gen-tools-gateway
```

**Method C: Nginx + systemd (Domain/HTTPS persistent, production recommended)**
- `deploy/nginx.conf.example`: reverse proxy example, already handles `X-Forwarded-*` and SSE;
- `deploy/free-ai-image-gen-tools-gateway.service.example`: startup on boot, automatic restart on crash.
- At this point, `config.public_base_url` can be set to `https://your domain`, and `forwarded_allow_ips` adjusted as needed.

**Cloud Server Security Checklist**
1. **Must** set `admin_token` (or `ADMIN_TOKEN`); otherwise, the management interface is unavailable/restricted to local loopback when exposed externally;
2. Cloud security group only opens necessary ports; prioritize using Nginx + HTTPS for external exposure, with the gateway itself not directly exposed;
3. Channel keys preferably injected via environment variables, not written into the config.yaml that comes with the package;
4. `storage_dir` should point to a persistently backsplashable/data disk to avoid losing images on container rebuild.

---

## 9. Extending a New Channel (Developer)

1. Create a new file in `imggen/providers/`, inheriting from `BaseProvider`, implement `available()` and `_generate_once()` (returning `list[bytes]`).
2. Instantiate it in `_build()` within `imggen/registry.py`.
3. Add corresponding configuration in `config.example.yaml`.

OpenAI-compatible new channels require no code: simply add a sub-item under `openai_compatible`, filling in base_url, key, and models.

---

## 10. Notes

- **Free channels have rate/quota limits**: When rate-limited (429 / ZeroGPU quota), the gateway will automatically switch channels or retry later; for stable batch production, configure a low-price API (SiliconFlow / Bailian) as fallback.
- **Web reverse channels** (perchance / bing) rely on the opponent's frontend structure and may fail after official website updates; best effort.
- **Commercial use rights**: Most free generation channels do not explicitly grant commercial use rights; for key materials delivered to customers, use channels with commercial authorization.
- This service defaults to listening on `127.0.0.1`; to allow LAN/other machines to call, set `server.host` to `0.0.0.0` and implement your own access control.

## Directory Structure

```text
free-ai-image-gen-tools-gateway/
├── run.sh
├── Dockerfile
├── requirements.txt
├── config.example.yaml
├── imggen/
│   ├── config.py          # Configuration loading + environment variables + hot reload
│   ├── registry.py        # Channel registration and routing
│   ├── storage.py         # Session-based storage / history query
│   ├── server.py          # FastAPI gateway
│   ├── cli.py             # Command line
│   └── providers/         # Channel adapters
├── web/index.html         # Web console
├── deploy/                # nginx / systemd deployment examples
└── storage/               # Unified resource root (sessions/<session>/), generated at runtime
```
