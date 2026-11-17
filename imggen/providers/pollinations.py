"""Pollinations — completely free HTTP image-generation channel, no key and no registration required.

Usage: GET https://image.pollinations.ai/prompt/<prompt>?width=&height=&seed=
Returns raw image binary directly. Anonymous free tier's current model is sana.
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
            raise ProviderError("pollinations image generation failed: HTTP %s %s" % (r.status_code, r.text[:200]))
        return [r.content]
