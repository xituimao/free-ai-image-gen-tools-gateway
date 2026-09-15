"""Perchance 逆向适配器（免费、无需 key，尽力而为通道）。

Perchance 无官方 API，这里按其前端历史调用流程实现，可能随官网调整而失效：
1. /api/verifyUser 拿匿名 userKey
2. /api/generate 拿 imageId
3. cdn.image-generation.perchance.org/download 下载图片
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
            raise ProviderError("perchance verifyUser 失败 HTTP %s" % r.status_code)
        self._user_key = r.json().get("userKey")
        if not self._user_key:
            raise ProviderError("perchance 未返回 userKey（可能被 Cloudflare 拦截）")
        return self._user_key

    async def _generate_once(self, client, req):
        key = await self._ensure_key(client)
        request_id = "req_%d" % random.randint(10 ** 6, 10 ** 7)
        # 分辨率映射到 perchance 支持档位
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
            raise ProviderError("perchance generate 失败 HTTP %s" % r.status_code)
        j = r.json()
        image_id = j.get("imageId")
        if not image_id:
            self._user_key = None
            raise ProviderError("perchance 未返回 imageId: %s" % str(j)[:200])
        dr = await client.get(CDN_HOST + "/download",
                              params={"imageId": image_id, "requestId": request_id})
        if dr.status_code != 200 or "image" not in dr.headers.get("content-type", ""):
            raise ProviderError("perchance 下载失败 HTTP %s" % dr.status_code)
        return [dr.content]
