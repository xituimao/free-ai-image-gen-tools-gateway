"""HuggingFace Spaces adapter (Gradio protocol, cloud-free, no local deployment needed).

Supports two Gradio protocol generations, auto-selects:
* Gradio 5 (queue protocol, current mainstream):
    GET  /config                                 -> find api_name's fn_index
    POST /gradio_api/queue/join                  -> enqueue
    GET  /gradio_api/queue/data?session_hash=..  -> SSE, wait for process_completed
* Legacy (call protocol):
    POST /call/<api> -> event_id; GET /call/<api>/<event_id>/events (SSE)

Image items in results are FileData (containing url/path), downloaded and returned as binary.
"""
import json
import os
import random
import string

from .base import BaseProvider, ProviderError

# Built-in Space presets: param_order is the interface parameter order
BUILTIN_SPACES = {
    "flux_schnell": {
        "space": "black-forest-labs/FLUX.1-schnell",
        "api_name": "/infer",
        "param_order": ["prompt", "seed", "randomize_seed", "width", "height",
                        "num_inference_steps"],
        "defaults": {"num_inference_steps": 4, "randomize_seed": False},
        "result_index": 0,
    },
    "sd35_large": {
        "space": "stabilityai/stable-diffusion-3.5-large",
        "api_name": "/infer",
        "param_order": ["prompt", "negative_prompt", "seed", "randomize_seed",
                        "width", "height", "guidance_scale", "num_inference_steps"],
        "defaults": {"guidance_scale": 4.5, "num_inference_steps": 28,
                     "randomize_seed": False},
        "result_index": 0,
    },
}


def _rand_hash(n=10):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


class HFSpaceProvider(BaseProvider):
    kind = "free"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._spaces = dict(BUILTIN_SPACES)
        for c in self.conf.get("custom_spaces") or []:
            if c.get("name"):
                self._spaces[c["name"]] = c
        self._fn_cache = {}   # space -> {api_name: fn_index, prefix}

    def _headers(self):
        # ZeroGPU Space with HF token gets more free daily quota
        token = self.conf.get("hf_token") or os.environ.get("HF_TOKEN")
        return {"Authorization": "Bearer " + token} if token else {}

    def available(self):
        return bool(self.conf.get("enabled", True))

    def list_models(self):
        return list(self._spaces.keys())

    def _space_name(self, req):
        return req.model or self.conf.get("default_space") or "flux_schnell"

    # ---------- Probe space structure ----------

    async def _probe(self, client, host, sp):
        sp_id = sp["space"]
        if sp_id in self._fn_cache:
            return self._fn_cache[sp_id]
        # config at /config (Gradio5)
        r = await client.get(host + "/config", headers=self._headers())
        info = {"fn_index": None, "prefix": "/gradio_api", "api_name": sp["api_name"]}
        if r.status_code == 200:
            cfg = r.json()
            api_prefix = cfg.get("api_prefix") or "/gradio_api"
            info["prefix"] = api_prefix
            for i, dep in enumerate(cfg.get("dependencies", [])):
                if dep.get("api_name") == sp["api_name"]:
                    info["fn_index"] = i
                    break
        else:
            # legacy version has no /config, fall back to call protocol
            info["prefix"] = ""
            info["fn_index"] = None
        self._fn_cache[sp_id] = info
        return info

    # ---------- Main flow ----------

    async def _generate_once(self, client, req):
        sp_name = self._space_name(req)
        sp = self._spaces.get(sp_name)
        if not sp:
            raise ProviderError("unknown hf_space preset: %s (options: %s)" % (
                sp_name, list(self._spaces.keys())))
        host = "https://%s.hf.space" % sp["space"]
        seed = req.seed if req.seed is not None else random.randint(0, 2 ** 31 - 1)

        values = {
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt or "",
            "seed": seed,
            "width": req.width,
            "height": req.height,
        }
        values.update(sp.get("defaults") or {})
        data = [values[k] for k in sp["param_order"]]

        # internal retry on ZeroGPU quota/proxy transient errors
        last_err = None
        for attempt in range(2):
            try:
                probe = await self._probe(client, host, sp)
                if probe["fn_index"] is not None:
                    result_arr = await self._queue_protocol(client, host, probe, data)
                else:
                    result_arr = await self._call_protocol(client, host, probe, sp, data)
                idx = sp.get("result_index", 0)
                item = result_arr[idx] if idx < len(result_arr) else result_arr
                return await self._download_images(client, host, item)
            except ProviderError as e:
                last_err = e
                msg = str(e)
                # quota errors are not worth retrying; raise directly
                if "quota" in msg.lower():
                    raise
                # clear structure cache before retrying; Space update allows re-probing
                self._fn_cache.pop(sp["space"], None)
        raise last_err

    # ---------- Gradio 5 queue ----------

    async def _queue_protocol(self, client, host, probe, data):
        sh = _rand_hash()
        body = {
            "data": data, "event_data": None,
            "fn_index": probe["fn_index"],
            "trigger_id": None, "session_hash": sh,
        }
        jr = await client.post(host + probe["prefix"] + "/queue/join",
                               json=body, headers=self._headers())
        if jr.status_code != 200:
            raise ProviderError("queue/join failed HTTP %s %s" % (
                jr.status_code, jr.text[:200]), status=jr.status_code)

        async with client.stream(
                "GET", host + probe["prefix"] + "/queue/data",
                params={"session_hash": sh}, headers=self._headers()) as resp:
            async for ev, payload in self._iter_sse(resp):
                if not payload:
                    continue
                try:
                    msg = json.loads(payload)
                except ValueError:
                    continue   # G8: tolerate non-JSON lines
                if msg.get("msg") == "process_completed":
                    if not msg.get("success"):
                        raise ProviderError("Space processing failed: %s" % json.dumps(
                            msg.get("output", {}), ensure_ascii=False)[:200])
                    return msg["output"].get("data", [])
        raise ProviderError("queue did not return process_completed (Space may be sleeping)")

    async def _iter_sse(self, resp):
        """Generic SSE parser: data may accumulate over multiple lines, blank lines separate events, comment heartbeats skipped."""
        data_lines, event = [], None
        async for line in resp.aiter_lines():
            if line == "":
                if data_lines:
                    yield event, "\n".join(data_lines)
                data_lines, event = [], None
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            yield event, "\n".join(data_lines)

    # ---------- Legacy call ----------

    async def _call_protocol(self, client, host, probe, sp, data):
        prefixes = ["/gradio_api", ""]
        r, used = None, ""
        for pref in prefixes:
            rr = await client.post(host + pref + "/call" + sp["api_name"],
                                   json={"data": data}, headers=self._headers())
            if rr.status_code == 200:
                r, used = rr, pref
                break
            if rr.status_code != 404:
                r, used = rr, pref
                break
        if r is None or r.status_code != 200:
            raise ProviderError("call failed HTTP %s" % (r.status_code if r else "?"))
        event_id = r.json().get("event_id")
        async with client.stream(
                "GET", "%s%s/call%s/%s/events" % (host, used, sp["api_name"], event_id)
        ) as resp:
            async for ev, payload in self._iter_sse(resp):
                if ev == "complete" and payload:
                    try:
                        return json.loads(payload)
                    except ValueError:
                        continue
        raise ProviderError("call did not receive complete")

    # ---------- Download result images ----------

    async def _download_images(self, client, host, item):
        candidates = item if isinstance(item, list) else [item]
        out = []
        for c in candidates:
            if not isinstance(c, dict):
                continue
            loc = c.get("url") or c.get("path") or c.get("name")
            if not loc:
                continue
            if loc.startswith("http"):
                img_url = loc
            elif loc.startswith("/"):
                img_url = host + loc
            else:
                img_url = host + "/gradio_api/file=" + loc
            ir = await client.get(img_url, headers=self._headers())
            if ir.status_code == 200:
                out.append(ir.content)
        if not out:
            raise ProviderError("no image found in result: %s" % str(item)[:200])
        return out
