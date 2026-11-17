"""OpenAI-compatible protocol adapter.

Any channel providing POST /images/generations returning {data:[{b64_json|url}]}
can be integrated via it: OpenAI official, SiliconFlow, and various third-party proxies.
One channel corresponds to one instance (expanded by registry per config).
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
        # negative prompt and other extra params pass-through (some compatible channels support)
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
            raise ProviderError("%s image generation failed: HTTP %s %s" % (
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
            raise ProviderError("%s returned no image" % self.name)
        return out
