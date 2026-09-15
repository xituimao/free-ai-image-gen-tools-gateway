"""Google Gemini（Nano Banana）适配器，走 AI Studio REST 接口。

免费 key 在 https://aistudio.google.com/apikey 申请，免费层每天有固定配额。
POST /v1beta/models/<model>:generateContent
返回 candidates[].content.parts[].inlineData.data (base64)。
"""
import base64

from .base import BaseProvider, ProviderError


class GeminiProvider(BaseProvider):
    kind = "key"

    def available(self):
        return bool(self.conf.get("enabled")) and bool(self.conf.get("api_key"))

    def list_models(self):
        return [self.conf.get("model", "gemini-2.5-flash-image")]

    async def _generate_once(self, client, req):
        base = (self.conf.get("base_url") or
                "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        model = req.model or self.conf.get("model", "gemini-2.5-flash-image")
        key = self.conf.get("api_key")
        text = req.prompt
        if req.negative_prompt:
            text += "\nAvoid: " + req.negative_prompt
        payload = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        url = "%s/models/%s:generateContent" % (base, model)
        # G7: key 走请求头，避免出现在 URL/访问日志中
        r = await client.post(url, json=payload,
                              headers={"x-goog-api-key": key})
        if r.status_code != 200:
            raise ProviderError("gemini 出图失败: HTTP %s %s" % (
                r.status_code, r.text[:300]), status=r.status_code)
        out = []
        for cand in r.json().get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    out.append(base64.b64decode(inline["data"]))
        if not out:
            raise ProviderError("gemini 返回中没有图像（可能触发安全过滤或配额用尽）")
        return out
