"""Bing Image Creator 适配器（后端为 DALL-E 3，免费但需账号 cookie）。

用法：浏览器登录 www.bing.com，从 cookie 复制 _U 的值填入 config。
流程（非官方，可能随前端调整）：
1. POST /images/create?q=...  从 302 Location 解析批次 id
2. GET  /images/create/async/results/<id> 轮询，正则提取 mimg 图片地址
3. 下载图片
"""
import asyncio
import re
from urllib.parse import quote, urlparse, parse_qs

from .base import BaseProvider, ProviderError

IMG_RE = re.compile(r'<img[^>]+class="?mimg"?[^>]*src="([^"]+)"')
# 兜底：任何 src2 链接
SRC2_RE = re.compile(r'src2="([^"]+)"')


class BingProvider(BaseProvider):
    kind = "key"

    def available(self):
        return bool(self.conf.get("enabled")) and bool(self.conf.get("cookie_u"))

    async def _generate_once(self, client, req):
        cookie_u = self.conf.get("cookie_u")
        cookies = {"_U": cookie_u}
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0 Safari/537.36"),
            "Referer": "https://www.bing.com/images/create",
        }
        q = quote(req.prompt)
        create_url = "https://www.bing.com/images/create?q=%s&rtver=4&FORM=GENCRE" % q
        r = await client.post(create_url, cookies=cookies, headers=headers,
                              follow_redirects=False)
        if r.status_code not in (301, 302):
            raise ProviderError("bing create 未重定向: HTTP %s %s" % (
                r.status_code, r.text[:200]), status=r.status_code)
        location = r.headers.get("location", "")
        # Location 形如 /images/create/async/results/<id1>?q=...&id=<id2>
        m = re.search(r'/results/([^?]+)', location)
        if not m:
            # 有时直接带 id 参数
            qs = parse_qs(urlparse(location).query)
            ids = qs.get("id")
            if not ids:
                raise ProviderError("bing 无法解析批次 id: %s" % location)
            batch_id = ids[0]
        else:
            batch_id = m.group(1)

        results_url = "https://www.bing.com/images/create/async/results/%s" % batch_id
        waited = 0
        urls = []
        while waited < self.timeout:
            rr = await client.get(results_url, params={"q": req.prompt},
                                  cookies=cookies, headers=headers)
            html = rr.text
            urls = IMG_RE.findall(html)
            if not urls:
                urls = SRC2_RE.findall(html)
            urls = [u for u in urls if u.startswith("http")]
            if urls:
                break
            await asyncio.sleep(2)
            waited += 2
        if not urls:
            raise ProviderError("bing 轮询超时或被风控（cookie 可能失效）")

        out = []
        for u in urls[:req.n]:
            ir = await client.get(u.replace("&amp;", "&"), headers=headers)
            if ir.status_code == 200:
                out.append(ir.content)
        if not out:
            raise ProviderError("bing 图片下载失败")
        return out
