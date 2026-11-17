"""Bing Image Creator adapter (backend is DALL-E 3, free but requires account cookie).

Usage: log in to www.bing.com in browser, copy _U cookie value into config.
Flow (unofficial, may change with frontend):
1. POST /images/create?q=...  parse batch id from 302 Location
2. GET /images/create/async/results/<id> poll, regex-extract mimg image URLs
3. Download images
"""
import asyncio
import re
from urllib.parse import quote, urlparse, parse_qs

from .base import BaseProvider, ProviderError

IMG_RE = re.compile(r'<img[^>]+class="?mimg"?[^>]*src="([^"]+)"')
# Fallback: any src2 link
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
            raise ProviderError("bing create did not redirect: HTTP %s %s" % (
                r.status_code, r.text[:200]), status=r.status_code)
        location = r.headers.get("location", "")
        # Location looks like /images/create/async/results/<id1>?q=...&id=<id2>
        m = re.search(r'/results/([^?]+)', location)
        if not m:
            # sometimes carries id parameter directly
            qs = parse_qs(urlparse(location).query)
            ids = qs.get("id")
            if not ids:
                raise ProviderError("bing could not parse batch id: %s" % location)
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
            raise ProviderError("bing polling timed out or rate-limited (cookie may be invalid)")

        out = []
        for u in urls[:req.n]:
            ir = await client.get(u.replace("&amp;", "&"), headers=headers)
            if ir.status_code == 200:
                out.append(ir.content)
        if not out:
            raise ProviderError("bing image download failed")
        return out
