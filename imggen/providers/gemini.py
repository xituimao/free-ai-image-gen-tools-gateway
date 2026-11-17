"""Google Gemini (Nano Banana) adapter, using AI Studio REST interface.

Get a free key at https://aistudio.google.com/apikey; free tier has a fixed daily quota.
POST /v1beta/models/<model>:generateContent
Returns candidates[].content.parts[].inlineData.data (base64).
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
        # G7: key goes in request header to avoid appearing in URL/access logs
        r = await client.post(url, json=payload,
                              headers={"x-goog-api-key": key})
        if r.status_code != 200:
            raise ProviderError("gemini image generation failed: HTTP %s %s" % (
                r.status_code, r.text[:300]), status=r.status_code)
        out = []
        for cand in r.json().get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    out.append(base64.b64decode(inline["data"]))
        if not out:
            raise ProviderError("gemini returned no image (possibly safety filter triggered or quota exhausted)")
        return out
