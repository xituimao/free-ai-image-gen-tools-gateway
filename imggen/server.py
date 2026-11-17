"""FastAPI Unified Image Generation Gateway.

Expose OpenAI-compatible API for AI agents; provide web console for humans.
All images (generated/uploaded) are uniformly stored in storage_dir, organized by session subdirectories.
Startup: python -m imggen.server  or  ./run.sh
"""
import asyncio
import base64
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .config import get_config
from .registry import build_registry
from .storage import Storage, StorageError, sniff_ext
from .usage import UsageLogger
from .providers.base import ImageRequest, ProviderError

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_mcp_app = None

MAX_N = 8            # API level: max images per request
MAX_COMPARE = 5      # compare: max concurrent targets
MAX_UPLOAD_MB = 10   # max upload size in MB

_state = {"client": None, "registry": None, "storage": None}


class GenBody(BaseModel):
    prompt: str
    # model: "provider/sub"；"auto" use auto chain；also support ["a","b"] for custom order
    model: str | list[str] | None = "auto"
    n: int | None = 1
    size: str | None = "1024x1024"
    response_format: str | None = "b64_json"   # b64_json | url
    negative_prompt: str | None = ""
    seed: int | None = None
    session_id: str | None = None              # session to archive to；also available via X-Session-Id header
    extra: dict | None = None


@asynccontextmanager
async def lifespan(app):
    cfg = get_config()
    srv = cfg.get("server") or {}
    read_to = srv.get("timeout", 120)
    storage_dir = srv.get("storage_dir") or os.path.join(ROOT, "storage")
    if not os.path.isabs(storage_dir):
        storage_dir = os.path.join(ROOT, storage_dir)
    _state["storage"] = Storage(storage_dir)
    _state["usage"] = UsageLogger(os.path.join(storage_dir, "usage.jsonl"))
    # Separate connection/read timeouts; long-polling channels only constrained by read
    timeout = httpx.Timeout(connect=15, read=read_to, write=30, pool=15)
    _state["client"] = httpx.AsyncClient(timeout=timeout)
    _state["registry"] = build_registry(cfg)
    # MCP session manager needs its own lifespan init task group
    mcp_ctx = None
    if _mcp_app is not None:
        try:
            mcp_ctx = _mcp_app.router.lifespan_context(_mcp_app)
            await mcp_ctx.__aenter__()
        except Exception as e:
            print("[mcp] lifespan init error:", e)
            mcp_ctx = None
    try:
        yield
    finally:
        # shutdown order: close MCP session manager first, then HTTP client
        if mcp_ctx is not None:
            try:
                await mcp_ctx.__aexit__(None, None, None)
            except Exception as e:
                print("[mcp] lifespan shutdown error:", e)
        try:
            await _state["client"].aclose()
        except Exception:
            pass


app = FastAPI(title="Free AI Image Gen Tools Gateway", version="1.4.4", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# MCP (Model Context Protocol) access point: Streamable HTTP, client connects to http://host:port/mcp
# FastMCP's streamable_http_app route is fixed at /mcp, directly merged into main app route table;
# its lifespan (initializing session manager task group) is nested in main lifespan.
try:
    from .mcp_server import get_asgi as _mcp_asgi
    _mcp_app = _mcp_asgi()
    for _r in getattr(_mcp_app, "routes", []):
        app.router.routes.append(_r)
except Exception as _e:
    print("[mcp] mount skipped:", _e)


def _parse_size(size):
    try:
        w, h = str(size).lower().replace("*", "x").split("x")
        return int(w), int(h)
    except Exception:
        return 1024, 1024


def _chain(body: GenBody, registry):
    if not body.model or body.model == "auto":
        return registry.build_auto_chain()
    if isinstance(body.model, list):
        return body.model
    return [body.model]


def _sid_of(body, request):
    return (getattr(body, "session_id", None)
            or request.headers.get("X-Session-Id") or "default")


def _client_info(request: Request):
    """Identify access side: transport comes from X-Transport (web/mpc carries), default api;
    client comes from X-Client-Name, default first 40 chars of User-Agent.
    trusted: web/mcp/cli channel client names injected by server are trustworthy;
             api channel external self-reports X-Client-Name, untrustworthy (can be forged)."""
    transport = (request.headers.get("X-Transport") or "api").lower()
    client = request.headers.get("X-Client-Name")
    if not client:
        ua = request.headers.get("user-agent") or ""
        client = ua[:40] if ua else "anonymous"
    trusted = transport != "api"
    return transport, client, trusted


def _public_base(request: Request):
    """Build absolute address: config takes priority; then X-Forwarded-* reverse proxy detection (cloud); otherwise use request Host."""
    cfg_base = (get_config().get("server") or {}).get("public_base_url")
    if cfg_base:
        return cfg_base.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host", "").split(",")[0].strip()
            or request.headers.get("host"))
    if proto and host:
        return "%s://%s" % (proto, host)
    return str(request.base_url).rstrip("/")


def _image_url(public_base, sid, fn):
    return "%s/v1/sessions/%s/images/%s" % (public_base, sid, fn)


def _error(message, etype="server_error", code=None):
    e = {"message": message, "type": etype}
    if code:
        e["code"] = code
    return e


def _decorate(rec, public_base):
    """Add accessible URL to history records, convenient for frontend to render directly."""
    out = dict(rec)
    sid = out.pop("_sid", "")
    out["file_urls"] = [_image_url(public_base, sid, f)
                        for f in rec.get("files", [])]
    return out


@app.post("/v1/images/generations")
async def generate(request: Request, body: GenBody):
    registry = _state["registry"]
    client = _state["client"]
    storage = _state["storage"]
    public_base = _public_base(request)
    w, h = _parse_size(body.size)
    n = max(1, min(body.n or 1, MAX_N))
    req = ImageRequest(
        prompt=body.prompt, negative_prompt=body.negative_prompt,
        width=w, height=h, n=n, seed=body.seed, extra=body.extra)

    chain = _chain(body, registry)
    sid = _sid_of(body, request)
    t0 = time.time()
    transport, client_name, trusted = _client_info(request)
    ulog = _state["usage"]

    def _record(status, provider=None, error=None):
        try:
            ulog.log(transport, client_name, "generate", trusted=trusted,
                      provider=provider, session_id=sid, status=status,
                      duration_ms=int((time.time() - t0) * 1000),
                      n=n, prompt=body.prompt[:200], error=error)
        except Exception:
            pass

    errors = []
    for target in chain:
        try:
            images = await registry.dispatch(client, target, req)
            registry.mark_success(target)
            prov, model = _split_target(target)
            # Archive uniformly to current session (regardless of b64 or url)
            try:
                rec = storage.archive_generation(sid, images, {
                    "prompt": body.prompt, "negative": body.negative_prompt or "",
                    "width": w, "height": h, "seed": body.seed,
                    "provider": prov, "model": model})
            except StorageError as e:
                _record("fail", error="storage: " + str(e))
                return JSONResponse(status_code=400, content={"error": _error(
                    str(e), "invalid_request_error")})

            data = []
            for i, b in enumerate(images):
                if body.response_format == "url":
                    data.append({"url": _image_url(public_base, sid, rec["files"][i])})
                else:
                    data.append({"b64_json": base64.b64encode(b).decode("ascii")})
            _record("success", provider=prov)
            return {
                "object": "list", "created": int(time.time()),
                "provider": prov, "model": model, "session_id": sid,
                "data": data, "chain_order": chain,
                "tried_before": [e["target"] for e in errors]}
        except ProviderError as e:
            registry.mark_failure(target)
            errors.append({"target": target, "error": str(e), "status": e.status})
        except Exception as e:
            registry.mark_failure(target)
            errors.append({"target": target,
                           "error": "%s: %s" % (type(e).__name__, e),
                           "status": 502})

    if not chain:
        _record("fail", error="no available channel")
        return JSONResponse(status_code=400, content={"error": _error(
            "No available enabled channel (please enable/fill credentials in config.yaml)",
            "invalid_request_error")})
    statuses = [e["status"] for e in errors]
    if statuses and all(400 <= s < 500 for s in statuses):
        out_status, etype = statuses[-1], "invalid_request_error"
    else:
        out_status, etype = 502, "server_error"
    details = [{"target": e["target"], "error": e["error"]} for e in errors]
    _record("fail", error="all channels failed: " + "; ".join(
        e["target"] + "=" + str(e["error"])[:80] for e in errors[:3]))
    return JSONResponse(status_code=out_status, content={
        "error": _error("All channels failed", etype),
        "chain_order": chain, "details": details})


def _split_target(t):
    return (t.split("/", 1)[0], t)


@app.post("/v1/images/compare")
async def compare(request: Request, body: GenBody):
    """Send same prompt concurrently to multiple channels (model is list), results also archived to current session."""
    registry = _state["registry"]
    client = _state["client"]
    storage = _state["storage"]
    public_base = _public_base(request)
    w, h = _parse_size(body.size)
    sid = _sid_of(body, request)
    t0 = time.time()
    transport, client_name, trusted = _client_info(request)
    targets = (body.model if isinstance(body.model, list) else [body.model])[:MAX_COMPARE]

    async def one(target):
        req = ImageRequest(
            prompt=body.prompt, negative_prompt=body.negative_prompt,
            width=w, height=h, n=1, seed=body.seed, extra=body.extra)
        try:
            images = await registry.dispatch(client, target, req)
            registry.mark_success(target)
            prov, model = _split_target(target)
            rec = storage.archive_generation(sid, images[:1], {
                "prompt": body.prompt, "negative": body.negative_prompt or "",
                "width": w, "height": h, "seed": body.seed,
                "provider": prov, "model": model})
            b = images[0]
            return {"target": target, "ok": True, "ext": sniff_ext(b),
                    "url": _image_url(public_base, sid, rec["files"][0]),
                    "b64": base64.b64encode(b).decode("ascii")}
        except Exception as e:
            registry.mark_failure(target)
            return {"target": target, "ok": False, "error": str(e)}

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[one(t) for t in targets]), timeout=90)
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={"error": _error(
            "compare total timeout (90s)", "server_error")})
    except StorageError as e:
        return JSONResponse(status_code=400, content={"error": _error(
            str(e), "invalid_request_error")})
    try:
        ok_n = sum(1 for r in results if r.get("ok"))
        _state["usage"].log(transport, client_name, "compare", trusted=trusted,
                             session_id=sid, status="success" if ok_n else "fail",
                             duration_ms=int((time.time() - t0) * 1000),
                             n=ok_n, prompt=body.prompt[:200],
                             provider=",".join(r["target"] for r in results if r.get("ok"))[:120])
    except Exception:
        pass
    return {"session_id": sid, "results": results}


# ---------------- Session management ----------------

@app.get("/v1/sessions")
async def list_sessions(request: Request):
    bad = _check_admin(request)
    if bad:
        return JSONResponse(status_code=403, content={"error": _error(
            bad, "invalid_request_error", "forbidden")})
    return {"object": "list", "data": _state["storage"].list_sessions()}


class SessionBody(BaseModel):
    title: str | None = None
    session_id: str | None = None


@app.post("/v1/sessions")
async def create_session(body: SessionBody):
    try:
        return _state["storage"].create_session(body.title, body.session_id)
    except StorageError as e:
        return JSONResponse(status_code=400, content={"error": _error(
            str(e), "invalid_request_error")})


class RenameBody(BaseModel):
    title: str


@app.post("/v1/sessions/{sid}/rename")
async def rename_session(sid: str, body: RenameBody):
    try:
        return _state["storage"].rename_session(sid, body.title)
    except StorageError as e:
        return JSONResponse(status_code=400, content={"error": _error(
            str(e), "invalid_request_error")})


@app.get("/v1/sessions/{sid}/history")
async def session_history(request: Request, sid: str,
                          search: str = "", sort: str = "ts_desc",
                          limit: int = 0):
    bad = _check_admin(request)
    if bad:
        return JSONResponse(status_code=403, content={"error": _error(
            bad, "invalid_request_error", "forbidden")})
    public_base = _public_base(request)
    lim = max(0, min(int(limit), 1000)) if limit else None
    try:
        recs = _state["storage"].query_history(sid, search, sort, limit=lim)
    except StorageError as e:
        return JSONResponse(status_code=400, content={"error": _error(
            str(e), "invalid_request_error")})
    return {"session_id": sid, "total": len(recs),
            "data": [_decorate(dict(r, _sid=sid), public_base) for r in recs]}


@app.post("/v1/sessions/{sid}/upload")
async def upload_image(request: Request, sid: str,
                       file: UploadFile = File(...),
                       caption: str = Form("")):
    public_base = _public_base(request)
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        return JSONResponse(status_code=413, content={"error": _error(
            "Image exceeds %dMB" % MAX_UPLOAD_MB, "invalid_request_error")})
    ext = sniff_ext(data)
    try:
        rec = _state["storage"].archive_upload(sid, data, ext, caption)
    except StorageError as e:
        return JSONResponse(status_code=400, content={"error": _error(
            str(e), "invalid_request_error")})
    try:
        transport, client_name, trusted = _client_info(request)
        _state["usage"].log(transport, client_name, "upload", trusted=trusted,
                             session_id=sid, status="success",
                             bytes=len(data), prompt=caption[:200])
    except Exception:
        pass
    return {"ok": True, "session_id": sid,
            "record": _decorate(dict(rec, _sid=sid), public_base)}


@app.get("/v1/sessions/{sid}/images/{name}")
async def session_image(sid: str, name: str):
    try:
        path = _state["storage"].image_path(sid, name)
    except StorageError as e:
        return JSONResponse(status_code=400, content={"error": _error(
            str(e), "invalid_request_error")})
    if not path:
        return JSONResponse(status_code=404, content={"error": _error(
            "not found", "invalid_request_error")})
    return FileResponse(path)


# ---------------- Model/chain/management ----------------

@app.get("/v1/models")
async def models():
    reg = _state["registry"]
    return {"object": "list", "data": [
        {"id": m["id"], "object": "model", "available": m["available"],
         "kind": m["kind"]} for m in reg.list_models()]}


@app.get("/v1/chain")
async def auto_chain():
    reg = _state["registry"]
    return {"chain": reg.build_auto_chain(), "cooling": reg.cooling_info()}


@app.get("/v1/providers")
async def providers():
    """Channel management: summary of all third-party channel statuses."""
    reg = _state["registry"]
    return {"summary": reg.provider_summary(), "data": reg.provider_status()}


class ProviderConfigBody(BaseModel):
    updates: dict


def _rebuild_after_config(cfg):
    old = _state["registry"]
    new_reg = build_registry(cfg, force_reload=True)
    new_reg.cooldown.update(getattr(old, "cooldown", {}))
    _state["registry"] = new_reg
    srv = cfg.get("server") or {}
    storage_dir = srv.get("storage_dir") or os.path.join(ROOT, "storage")
    if not os.path.isabs(storage_dir):
        storage_dir = os.path.join(ROOT, storage_dir)
    from .storage import Storage
    _state["storage"] = Storage(storage_dir)
    _state["usage"] = UsageLogger(os.path.join(storage_dir, "usage.jsonl"))


def build_reg(cfg, force_reload=False):
    return build_registry(cfg, force_reload=force_reload)


@app.post("/v1/providers/config")
async def providers_config(request: Request, body: ProviderConfigBody):
    transport, client_name, trusted = _client_info(request)
    bad = _check_admin(request)
    if bad:
        try:
            _state["usage"].log(transport, client_name, "configure", trusted=trusted,
                                 status="fail", error="forbidden")
        except Exception:
            pass
        return JSONResponse(status_code=403, content={"error": _error(
            bad, "invalid_request_error", "forbidden")})
    import yaml
    from . import config as cfgmod
    cfg = get_config()
    path = cfgmod._CONFIG_PATH
    if not path or path.endswith("config.example.yaml"):
        path = os.path.join(ROOT, "config.yaml")
    prov = cfg.setdefault("providers", {})
    oc = prov.setdefault("openai_compatible", prov.get("openai_compatible") or {})

    for name, vals in (body.updates or {}).items():
        target = oc[name] if name in oc else prov.setdefault(name, {})
        if "enabled" in vals:
            target["enabled"] = bool(vals["enabled"])
        dm = vals.get("default_model")
        if dm:
            target["default_model"] = dm
        for k, v in vals.items():
            if k in ("enabled", "default_model"):
                continue
            if v:
                target[k] = v
    prov["openai_compatible"] = oc
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    from .config import load_config
    new_cfg = load_config(path)
    _rebuild_after_config(new_cfg)
    reg = _state["registry"]
    try:
        _state["usage"].log(transport, client_name, "configure", trusted=trusted,
                             status="success",
                             provider=",".join(list((body.updates or {}).keys())[:5]))
    except Exception:
        pass
    return {"ok": True, "path": path,
            "summary": reg.provider_summary(), "data": reg.provider_status()}


@app.post("/v1/providers/{name}/test")
async def provider_test(request: Request, name: str):
    reg = _state["registry"]
    row = next((r for r in reg.provider_status() if r["name"] == name), None)
    if not row:
        return JSONResponse(status_code=404, content={"error": _error(
            "Unknown channel", "invalid_request_error")})
    missing = [c["label"] for c in row["creds"]
               if not c["set"] and not c["optional"]]
    try:
        transport, client_name, trusted = _client_info(request)
        _state["usage"].log(transport, client_name, "test", trusted=trusted,
                             provider=name, status="success" if row["available"] else "fail")
    except Exception:
        pass
    return {"name": name, "available": row["available"],
            "enabled": row["enabled"], "missing": missing,
            "cooldown_left": row["cooldown_left"]}


@app.get("/v1/clients")
async def clients(request: Request):
    """Summary of all access sides: call count, success rate, last activity, online status.
    Admin interface, protected by admin authentication (configure admin_token or localhost only)."""
    bad = _check_admin(request)
    if bad:
        return JSONResponse(status_code=403, content={"error": _error(
            bad, "invalid_request_error", "forbidden")})
    return {"data": _state["usage"].clients()}


@app.get("/v1/usage")
async def usage(request: Request, client: str = "", transport: str = "",
                action: str = "", search: str = "", sort: str = "ts_desc",
                limit: int = 200, offset: int = 0):
    """Usage log per access side, supports filtering/searching/sorting by client/transport/action.
    Admin interface, protected by admin authentication (configure admin_token or localhost only)."""
    bad = _check_admin(request)
    if bad:
        return JSONResponse(status_code=403, content={"error": _error(
            bad, "invalid_request_error", "forbidden")})
    limit = max(1, min(int(limit), 1000))
    return _state["usage"].query(
        client=client or None, transport=transport or None,
        action=action or None, search=search, sort=sort,
        limit=limit, offset=offset)


@app.get("/v1/heartbeat")
async def heartbeat(request: Request):
    """Lightweight heartbeat: frontend "access sides and logs" page calls regularly to keep web-console online.
    Record one usage log (action=heartbeat), no business data returned.
    Protected by admin authentication (configure admin_token or localhost only)."""
    bad = _check_admin(request)
    if bad:
        return JSONResponse(status_code=403, content={"error": _error(
            bad, "invalid_request_error", "forbidden")})
    try:
        transport, client_name, trusted = _client_info(request)
        _state["usage"].log(transport, client_name, "heartbeat", trusted=trusted,
                             status="success")
    except Exception:
        pass
    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True, "models": len(_state["registry"].list_models())}


def _check_admin(request: Request):
    srv = get_config().get("server") or {}
    token = srv.get("admin_token") or os.environ.get("ADMIN_TOKEN")
    if token:
        if request.headers.get("X-Admin-Token", "") != token:
            return "admin token invalid"
        return None
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1"):
        return "admin_token not configured, management interface only allowed on localhost"
    return None


@app.post("/admin/reload")
async def reload_cfg(request: Request):
    bad = _check_admin(request)
    if bad:
        return JSONResponse(status_code=403, content={"error": _error(
            bad, "invalid_request_error", "forbidden")})
    from .config import load_config
    old = _state["registry"]
    cfg = load_config(None)
    new_reg = build_registry(cfg, force_reload=True)
    new_reg.cooldown.update(getattr(old, "cooldown", {}))
    _state["registry"] = new_reg
    srv = cfg.get("server") or {}
    storage_dir = srv.get("storage_dir") or os.path.join(ROOT, "storage")
    if not os.path.isabs(storage_dir):
        storage_dir = os.path.join(ROOT, storage_dir)
    _state["storage"] = Storage(storage_dir)
    _state["usage"] = UsageLogger(os.path.join(storage_dir, "usage.jsonl"))
    return {"ok": True, "models": len(new_reg.list_models())}


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"error": _error(
        "Request parameter validation failed: %s" % exc.errors(), "invalid_request_error")})


@app.get("/")
async def index():
    return FileResponse(os.path.join(ROOT, "web", "index.html"))


def main():
    import uvicorn
    cfg = get_config()
    srv = cfg.get("server", {})
    uvicorn.run(
        "imggen.server:app",
        host=srv.get("host", "127.0.0.1"),
        port=srv.get("port", 8799),
        # Cloud reverse proxy needs to trust proxy headers to correctly identify protocol/client
        forwarded_allow_ips=srv.get("forwarded_allow_ips", "127.0.0.1"),
        reload=False)


if __name__ == "__main__":
    main()
