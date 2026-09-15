"""Pollinations —— 完全免费、无需 key、无需注册的 HTTP 生图通道。

调用方式: GET https://image.pollinations.ai/prompt/<prompt>?width=&height=&seed=
直接返回图片二进制。匿名免费档当前模型为 sana。
"""
import random
from urllib.parse import quote

from .base import BaseProvider, ProviderError


class PollinationsProvider(BaseProvider):
    kind = "free"

    def available(self):
        return bool(self.conf.get("enabled", True))

    def list_models(self):
        return [self.conf.get("model", "sana")]

    async def _generate_once(self, client, req):
        base = (self.conf.get("base_url") or "https://image.pollinations.ai").rstrip("/")
        model = req.model or self.conf.get("model", "sana")
        seed = req.seed if req.seed is not None else random.randint(0, 2 ** 31 - 1)
        url = "%s/prompt/%s" % (base, quote(req.prompt, safe=""))
        params = {
            "width": req.width,
            "height": req.height,
            "seed": seed,
            "model": model,
            "nologo": "true",
        }
        if req.negative_prompt:
            params["negative_prompt"] = req.negative_prompt
        r = await client.get(url, params=params)
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or "image" not in ctype:
            raise ProviderError("pollinations 出图失败: HTTP %s %s" % (r.status_code, r.text[:200]))
        return [r.content]
