"""Alibaba Cloud Bailian DashScope adapter (Tongyi Wanxiang / Z-Image).

Bailian text-to-image is an async task:
1. POST /services/aigc/text2image/image-synthesis (X-DashScope-Async: enable)
   to get task_id
2. GET /tasks/<task_id> poll, after SUCCEEDED download from output.results[].url
"""
import asyncio

from .base import BaseProvider, ProviderError


class BailianProvider(BaseProvider):
    kind = "key"
    supports_n = True

    def available(self):
        return bool(self.conf.get("enabled")) and bool(self.conf.get("api_key"))

    def _model(self, req):
        return req.model or self.conf.get("default_model") or "wanx2.1-t2i-turbo"

    async def _generate_once(self, client, req):
        base = (self.conf.get("base_url") or
                "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
        key = self.conf.get("api_key")
        headers = {"Authorization": "Bearer %s" % key, "X-DashScope-Async": "enable"}
        model = self._model(req)
        body = {
            "model": model,
            "input": {
                "prompt": req.prompt,
                "negative_prompt": req.negative_prompt or "",
            },
            "parameters": {
                # Bailian sizes use W*H (asterisk)
                "size": "%d*%d" % (req.width, req.height),
                "n": req.n,
            },
        }
        if req.seed is not None:
            body["parameters"]["seed"] = req.seed

        r = await client.post(
            base + "/services/aigc/text2image/image-synthesis",
            headers=headers, json=body)
        if r.status_code not in (200, 201):
            raise ProviderError("bailian task submission failed: HTTP %s %s" % (
                r.status_code, r.text[:300]), status=r.status_code)
        task_id = r.json().get("output", {}).get("task_id")
        if not task_id:
            raise ProviderError("bailian returned no task_id: %s" % r.text[:200])

        # poll task
        deadline = self.timeout
        waited = 0
        interval = 1.5
        poll_fail = 0
        while waited < deadline:
            await asyncio.sleep(interval)
            waited += interval
            tr = await client.get(base + "/tasks/" + task_id,
                                  headers={"Authorization": "Bearer %s" % key})
            if tr.status_code != 200:
                # count consecutive query failures; exit early after 5 instead of spinning
                poll_fail += 1
                if poll_fail >= 5:
                    raise ProviderError("bailian task query failed consecutively HTTP %s" % tr.status_code)
                continue
            poll_fail = 0
            tj = tr.json()
            status = tj.get("output", {}).get("task_status")
            if status == "SUCCEEDED":
                results = tj["output"].get("results", [])
                out, dl_errors = [], []
                for item in results:
                    ir = await client.get(item["url"])
                    if ir.status_code == 200:
                        out.append(ir.content)
                    else:
                        dl_errors.append("HTTP %s" % ir.status_code)
                if out:
                    return out
                # G5: task succeeded but all image downloads failed; raise real reason immediately instead of timing out
                raise ProviderError("bailian task succeeded but image download failed: %s" %
                                    (", ".join(dl_errors) or "no results"))
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                raise ProviderError("bailian task %s: %s" % (
                    status, tj.get("output", {}).get("message", "")))
        raise ProviderError("bailian task polling timed out")
