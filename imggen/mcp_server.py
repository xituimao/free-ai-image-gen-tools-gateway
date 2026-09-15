"""MCP（Model Context Protocol）接入面。

把统一生图网关暴露为 MCP 工具，供 Claude Desktop、Cursor、Cline、
VS Code Copilot、Windsurf 等支持 MCP 的 agent 客户端直接调用。

实现方式：薄客户端，内部通过 HTTP 调用本地网关（默认 http://127.0.0.1:8799），
复用全部生成/归档/自动链/渠道管理逻辑；调用时带 X-Transport: mcp 和
X-Client-Name，网关侧统一记入使用日志。

两种传输：
- stdio：`python -m imggen.mcp_server`（本地 agent 客户端拉起）
- Streamable HTTP：已由 server.py 挂载到 /mcp（远程 agent 连 http://host:port/mcp）

环境变量：
- IMGGW_BASE_URL：网关地址，默认 http://127.0.0.1:8799
- ADMIN_TOKEN：写配置类工具需要（与网关 admin_token 一致）
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("free-ai-image-gen-tools-gateway")


def _default_base_url():
    """从环境变量（PORT/HOST）和 config.yaml 推断网关地址，默认 127.0.0.1:8799。
    IMGGW_BASE_URL 环境变量优先级最高（在调用方覆盖）。"""
    # 环境变量优先（与 config.py _apply_env 一致）
    port = os.environ.get("PORT")
    host = os.environ.get("HOST", "127.0.0.1")
    if port:
        return f"http://{host}:{port}"
    # 从 config.yaml 读取
    try:
        import yaml
        from .config import find_config
        path = find_config()
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            srv = cfg.get("server") or {}
            p = srv.get("port", 8799)
            h = srv.get("host", "127.0.0.1")
            # 0.0.0.0 监听时，本地回连用 127.0.0.1
            if h == "0.0.0.0":
                h = "127.0.0.1"
            return f"http://{h}:{p}"
    except Exception:
        pass
    return "http://127.0.0.1:8799"


BASE_URL = os.environ.get("IMGGW_BASE_URL", _default_base_url()).rstrip("/")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def _headers(ctx: Context):
    h = {"Content-Type": "application/json", "X-Transport": "mcp"}
    try:
        name = ctx.session.client_params.clientInfo.name
        if name:
            h["X-Client-Name"] = str(name)[:60]
    except Exception:
        pass
    if ADMIN_TOKEN:
        h["X-Admin-Token"] = ADMIN_TOKEN
    return h


def _client_name(ctx):
    try:
        return ctx.session.client_params.clientInfo.name or "mcp-client"
    except Exception:
        return "mcp-client"


@mcp.tool()
async def generate_image(
    ctx: Context,
    prompt: str,
    model: str = "auto",
    session_id: str = "default",
    size: str = "1024x1024",
    n: int = 1,
    seed: int = 0,
    negative_prompt: str = "",
) -> str:
    """生成图片。model=auto 走自动故障转移链；也可指定 pollinations/gemini/siliconflow 等渠道，
    或传列表如 [\"pollinations\",\"gemini\"] 自定义顺序。图片自动归档到 session_id 会话。
    返回实际出图渠道、图片本地路径和会话。"""
    body = {"prompt": prompt, "model": model, "session_id": session_id,
            "size": size, "n": max(1, min(int(n), 8)),
            "response_format": "url", "negative_prompt": negative_prompt}
    if seed:
        body["seed"] = int(seed)
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(BASE_URL + "/v1/images/generations",
                         json=body, headers=_headers(ctx))
        j = r.json()
        if r.status_code != 200:
            return "生成失败(%d): %s" % (r.status_code, (j.get("error") or {}).get("message", j))
        urls = [d.get("url") for d in j.get("data", [])]
        return ("生成成功\n渠道: %s\n会话: %s\n尝试过: %s\n图片:\n%s"
                % (j.get("provider"), j.get("session_id"),
                   ", ".join(j.get("tried_before") or []) or "(无)",
                   "\n".join(urls)))


@mcp.tool()
async def list_sessions(ctx: Context) -> str:
    """列出所有会话（含每个会话的图片数）。"""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(BASE_URL + "/v1/sessions", headers=_headers(ctx))
        j = r.json()
        lines = ["%s · %d图 · %s" % (s["id"], s.get("images", 0), s.get("title") or "")
                 for s in j.get("data", [])]
        return "会话列表:\n" + ("\n".join(lines) if lines else "(空)")


@mcp.tool()
async def list_history(ctx: Context, session_id: str = "default",
                        search: str = "", sort: str = "ts_desc",
                        limit: int = 50) -> str:
    """查询某会话的历史记录，可按提示词/渠道搜索，按时间/渠道/尺寸排序。
    每条含第三方渠道名、prompt、参数、图片地址。"""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(BASE_URL + "/v1/sessions/%s/history" % session_id,
                        params={"search": search, "sort": sort, "limit": limit},
                        headers=_headers(ctx))
        j = r.json()
        out = ["共 %d 条（会话 %s）" % (j.get("total", 0), session_id)]
        for rec in j.get("data", []):
            out.append("- [%s] %s | %dx%d n=%d | %s"
                       % (rec.get("provider") or rec.get("source"),
                          (rec.get("prompt") or "")[:80],
                          rec.get("width") or 0, rec.get("height") or 0,
                          rec.get("n") or 0,
                          ", ".join(rec.get("file_urls") or [])))
        return "\n".join(out)


@mcp.tool()
async def get_providers(ctx: Context) -> str:
    """所有第三方生图渠道的状态汇总：可用/未配置/冷却、类型、默认模型、所需凭证。"""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(BASE_URL + "/v1/providers", headers=_headers(ctx))
        j = r.json()
        s = j.get("summary", {})
        out = ["汇总: 可用%d / 未配置%d / 冷却%d / 总数%d"
               % (s.get("available", 0), s.get("unconfigured", 0),
                  s.get("cooling", 0), s.get("total", 0))]
        for p in j.get("data", []):
            st = "可用" if p["available"] else ("冷却%ds" % p["cooldown_left"] if p["cooldown_left"] else "未配置")
            out.append("- %s [%s] %s | 默认模型=%s"
                       % (p["label"], p["type_label"], st, p.get("default_model") or "-"))
        return "\n".join(out)


@mcp.tool()
async def configure_provider(ctx: Context, name: str, enabled: bool = True,
                              api_key: str = "", default_model: str = "") -> str:
    """在线配置某个第三方渠道：填 key、设默认模型、启用/禁用。保存即热加载生效。
    api_key 留空表示不修改已有值。需要网关配置了 admin_token（通过 ADMIN_TOKEN 环境变量传入）。"""
    updates = {"enabled": bool(enabled)}
    if api_key:
        updates["api_key"] = api_key
    if default_model:
        updates["default_model"] = default_model
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(BASE_URL + "/v1/providers/config",
                         json={"updates": {name: updates}}, headers=_headers(ctx))
        j = r.json()
        if r.status_code != 200:
            return "配置失败(%d): %s" % (r.status_code, (j.get("error") or {}).get("message", j))
        return "已保存并热加载: %s（写入 %s）" % (name, j.get("path"))


@mcp.tool()
async def test_provider(ctx: Context, name: str) -> str:
    """对某个渠道做轻量自检（不真实出图、不消耗额度），返回可用/缺凭证/冷却状态。"""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(BASE_URL + "/v1/providers/%s/test" % name, headers=_headers(ctx))
        j = r.json()
        if r.status_code != 200:
            return "自检失败(%d): %s" % (r.status_code, j)
        return ("渠道 %s: 可用=%s 启用=%s 缺凭证=%s 冷却=%ds"
                % (name, j.get("available"), j.get("enabled"),
                   ",".join(j.get("missing") or []) or "无",
                   j.get("cooldown_left", 0)))


def get_asgi():
    """供 server.py 挂载为 Streamable HTTP（/mcp）。"""
    return mcp.streamable_http_app()


if __name__ == "__main__":
    mcp.run(transport="stdio")
