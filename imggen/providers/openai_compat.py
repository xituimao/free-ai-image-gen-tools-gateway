"""OpenAI 兼容协议适配器。

任何提供 POST /images/generations 且返回 {data:[{b64_json|url}]} 的渠道
都可以用它接入：OpenAI 官方、硅基流动、各类第三方中转。
一个渠道对应一个实例（在 registry 中按配置展开）。
"""
import base64

from .base import BaseProvider, ProviderError


class OpenAICompatProvider(BaseProvider):
    kind = "key"
    supports_n = True

    def available(self):
        return bool(self.conf.get("enabled")) and bool(self.conf.get("api_key"))

    def _model(self, req):
        return req.model or self.conf.get("default_model") or (self.list_models() or [None])[0]

    async def _generate_once(self, client, req):
        base = (self.conf.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        model = self._model(req)
        payload = {
            "model": model,
            "prompt": req.prompt,
            "n": req.n,
            "size": "%dx%d" % (req.width, req.height),
            "response_format": "b64_json",
        }
        # 负向提示等额外参数透传（部分兼容渠道支持）
        if req.negative_prompt:
            payload["negative_prompt"] = req.negative_prompt
        for k, v in (req.extra or {}).items():
            payload.setdefault(k, v)

        r = await client.post(
            base + "/images/generations",
            headers={"Authorization": "Bearer %s" % self.conf.get("api_key")},
            json=payload,
        )
        if r.status_code != 200:
            raise ProviderError("%s 出图失败: HTTP %s %s" % (
                self.name, r.status_code, r.text[:300]), status=r.status_code)
        data = r.json().get("data", [])
        out = []
        for item in data:
            if item.get("b64_json"):
                out.append(base64.b64decode(item["b64_json"]))
            elif item.get("url"):
                ir = await client.get(item["url"])
                if ir.status_code == 200:
                    out.append(ir.content)
        if not out:
            raise ProviderError("%s 返回中没有图像" % self.name)
        return out
