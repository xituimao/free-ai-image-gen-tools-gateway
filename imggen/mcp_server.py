"""MCP (Model Context Protocol) access point.

Expose the unified image generation gateway as MCP tools for Claude Desktop, Cursor, Cline,
VS Code Copilot, Windsurf and other MCP-supporting agent clients to call directly.

Implementation: thin client, internally calls local gateway via HTTP (default http://127.0.0.1:8799),
reusing all generation/archive/auto-chain/channel management logic; calls carry X-Transport: mcp and
X-Client-Name, gateway side uniformly records into usage log.

Two transports:
- stdio: `python -m imggen.mcp_server` (local agent client launches)
- Streamable HTTP: mounted by server.py at /mcp (remote agent connects to http://host:port/mcp)

Environment variables:
- IMGGW_BASE_URL: gateway address, default http://127.0.0.1:8799
- ADMIN_TOKEN: needed for write-config tools (consistent with gateway admin_token)
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("free-ai-image-gen-tools-gateway")


def _default_base_url():
    """Infer gateway address from environment variables (PORT/HOST) and config.yaml, default 127.0.0.1:8799.
    IMGGW_BASE_URL environment variable has highest priority (overridden by caller)."""
    # Environment variable first (consistent with config.py _apply_env)
    port = os.environ.get("PORT")
    host = os.environ.get("HOST", "127.0.0.1")
    if port:
        return f"http://{host}:{port}"
    # Read from config.yaml
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
            # When listening on 0.0.0.0, local loopback uses 127.0.0.1
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
    """Generate image. model=auto uses auto failover chain; can also specify pollinations/gemini/siliconflow etc channels,
    or pass a list like ["pollinations","gemini"] for custom order. Images are automatically archived to session_id session.
    Returns actual image channel, image local path and session."""
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
            return "Generation failed(%d): %s" % (r.status_code, (j.get("error") or {}).get("message", j))
        urls = [d.get("url") for d in j.get("data", [])]
        return ("Generation succeeded\nChannel: %s\nSession: %s\nTried: %s\nImages:\n%s"
                % (j.get("provider"), j.get("session_id"),
                   ", ".join(j.get("tried_before") or []) or "(none)",
                   "\n".join(urls)))


@mcp.tool()
async def list_sessions(ctx: Context) -> str:
    """List all sessions (including each session's image count)."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(BASE_URL + "/v1/sessions", headers=_headers(ctx))
        j = r.json()
        lines = ["%s · %d images · %s" % (s["id"], s.get("images", 0), s.get("title") or "")
                 for s in j.get("data", [])]
        return "Session list:\n" + ("\n".join(lines) if lines else "(empty)")


@mcp.tool()
async def list_history(ctx: Context, session_id: str = "default",
                        search: str = "", sort: str = "ts_desc",
                        limit: int = 50) -> str:
    """Query history of a session, searchable by prompt/channel, sortable by time/channel/size.
    Each entry includes third-party channel name, prompt, parameters, image address."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(BASE_URL + "/v1/sessions/%s/history" % session_id,
                        params={"search": search, "sort": sort, "limit": limit},
                        headers=_headers(ctx))
        j = r.json()
        out = ["Total %d items (session %s)" % (j.get("total", 0), session_id)]
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
    """Status summary of all third-party image generation channels: available/unconfigured/cooling, type, default model, required credentials."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(BASE_URL + "/v1/providers", headers=_headers(ctx))
        j = r.json()
        s = j.get("summary", {})
        out = ["Summary: available %d / unconfigured %d / cooling %d / total %d"
               % (s.get("available", 0), s.get("unconfigured", 0),
                  s.get("cooling", 0), s.get("total", 0))]
        for p in j.get("data", []):
            st = "available" if p["available"] else ("cooling %ds" % p["cooldown_left"] if p["cooldown_left"] else "unconfigured")
            out.append("- %s [%s] %s | default model=%s"
                       % (p["label"], p["type_label"], st, p.get("default_model") or "-"))
        return "\n".join(out)


@mcp.tool()
async def configure_provider(ctx: Context, name: str, enabled: bool = True,
                              api_key: str = "", default_model: str = "") -> str:
    """Online configure a third-party channel: fill key, set default model, enable/disable. Saving takes effect via hot reload.
    api_key left empty means do not modify existing value. Gateway needs admin_token configured (passed via ADMIN_TOKEN env var)."""
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
            return "Configuration failed(%d): %s" % (r.status_code, (j.get("error") or {}).get("message", j))
        return "Saved and hot reloaded: %s (written to %s)" % (name, j.get("path"))


@mcp.tool()
async def test_provider(ctx: Context, name: str) -> str:
    """Lightweight self-check on a channel (no real image generation, no quota consumption), returns available/missing credentials/cooling status."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(BASE_URL + "/v1/providers/%s/test" % name, headers=_headers(ctx))
        j = r.json()
        if r.status_code != 200:
            return "Self-check failed(%d): %s" % (r.status_code, j)
        return ("Channel %s: available=%s enabled=%s missing credentials=%s cooling=%ds"
                % (name, j.get("available"), j.get("enabled"),
                   ",".join(j.get("missing") or []) or "none",
                   j.get("cooldown_left", 0)))


def get_asgi():
    """For server.py to mount as Streamable HTTP (/mcp)."""
    return mcp.streamable_http_app()


if __name__ == "__main__":
    mcp.run(transport="stdio")
