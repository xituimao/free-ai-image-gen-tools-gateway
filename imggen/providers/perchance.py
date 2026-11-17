"""Perchance reverse adapter (free, no key needed, best-effort channel).

Perchance has no official API; here implemented per its historical frontend call flow, may fail as the official site changes:
1. /api/verifyUser to get anonymous userKey
2. /api/generate to get imageId
3. cdn.image-generation.perchance.org/download to download image
"""
import random
import time

from .base import BaseProvider, ProviderError

API_HOST = "https://image-generation.perchance.org"
CDN_HOST = "https://cdn.image-generation.perchance.org"


class PerchanceProvider(BaseProvider):
    kind = "free"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._user_key = None

    def available(self):
        return bool(self.conf.get("enabled", True))

    async def _ensure_key(self, client):
        if self._user_key:
            return self._user_key
        r = await client.get(API_HOST + "/api/verifyUser",
                             params={"__cacheBust": str(int(time.time() * 1000))})
        if r.status_code != 200:
            raise ProviderError("perchance verifyUser failed HTTP %s" % r.status_code)
        self._user_key = r.json().get("userKey")
        if not self._user_key:
            raise ProviderError("perchance returned no userKey (possibly blocked by Cloudflare)")
        return self._user_key

    async def _generate_once(self, client, req):
        key = await self._ensure_key(client)
        request_id = "req_%d" % random.randint(10 ** 6, 10 ** 7)
        # map resolution to perchance supported tiers
        long_side = max(req.width, req.height)
        if long_side <= 512:
            res = "512x512"
        elif long_side <= 768:
            res = "768x768"
        else:
            res = "1024x1024"
        params = {
            "prompt": req.prompt,
            "negativePrompt": req.negative_prompt or "",
            "userKey": key,
            "seed": req.seed if req.seed is not None else -1,
            "resolution": res,
            "guidanceScale": 7,
            "channel": "ai-text-to-image-generator",
            "requestId": request_id,
            "__cacheBust": str(int(time.time() * 1000)),
        }
        r = await client.get(API_HOST + "/api/generate", params=params)
        if r.status_code != 200:
            self._user_key = None
            raise ProviderError("perchance generate failed HTTP %s" % r.status_code)
        j = r.json()
        image_id = j.get("imageId")
        if not image_id:
            self._user_key = None
            raise ProviderError("perchance returned no imageId: %s" % str(j)[:200])
        dr = await client.get(CDN_HOST + "/download",
                              params={"imageId": image_id, "requestId": request_id})
        if dr.status_code != 200 or "image" not in dr.headers.get("content-type", ""):
            raise ProviderError("perchance download failed HTTP %s" % dr.status_code)
        return [dr.content]
