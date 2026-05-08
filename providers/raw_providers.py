"""
مزودات RAW الأصلية:
- AC.QQ (腾讯漫画 / Tencent Comics)
- Kuaikan (快看漫画)
- LINE Manga (manga.line.me)
- Piccoma (piccoma.com / piccoma.jp)
- Comico (comico.jp / comico.kr)
- iQiyi Manhua (manhua.iqiyi.com)
- Naver (نسخة محسّنة للفصول المجانية)
- Lezhin (lezhin.com — المحتوى المجاني فقط)
- Webtoon (webtoons.com — تحسين المزود الموجود)
"""

import re
import json
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
from urllib.parse import urljoin, urlparse


# ─────────────────────────────────────────────────────────────────
#  AC.QQ — 腾讯漫画 (Tencent Comics)
# ─────────────────────────────────────────────────────────────────
class AcQQProvider(BaseProvider):
    """
    مزود AC.QQ (ac.qq.com) — كوميكس Tencent الصينية.
    """

    BASE = "https://ac.qq.com"

    def __init__(self):
        super().__init__()
        self.headers.update({
            "Referer":       "https://ac.qq.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def _extract_comic_id(self, url: str) -> str:
        m = re.search(r'/Comic(?:Info)?/index/id/(\d+)', url)
        if not m:
            m = re.search(r'comicId=(\d+)', url)
        if not m:
            m = re.search(r'/(\d+)(?:/|$)', url)
        return m.group(1) if m else None

    def _extract_chapter_info(self, url: str):
        m = re.search(r'/ComicView/index/id/(\d+)/cid/(\d+)', url)
        return (m.group(1), m.group(2)) if m else (None, None)

    async def get_images(self, url: str):
        try:
            html = self.fetch_html(url)
            if not html:
                return []
            # بيانات الفصل مشفّرة في متغير JS
            m = re.search(r"var\s+DATA\s*=\s*'([^']+)'", html)
            if not m:
                m = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.+?});', html, re.S)
            if m:
                try:
                    import base64
                    raw     = base64.b64decode(m.group(1)).decode("utf-8")
                    decoded = json.loads(raw)
                    imgs    = decoded.get("picture", [])
                    return [img.get("url", "") for img in imgs if img.get("url")]
                except Exception:
                    pass
            # fallback: regex عام
            images = re.findall(
                r'"url"\s*:\s*"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', html
            )
            return [img.replace("\\u002F", "/") for img in images]
        except Exception as e:
            print(f"[AcQQ] get_images error: {e}")
            return []

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            html = self.fetch_html(series_url)
            if not html:
                return {}
            soup     = BeautifulSoup(html, "html.parser")
            chapters = {}
            base     = self.BASE
            for a in soup.select("a[href*='/ComicView/']"):
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = urljoin(base, href)
                m = re.search(r'/cid/(\d+)', href)
                if m:
                    cid  = m.group(1)
                    txt  = a.get_text(strip=True)
                    nm   = self.extract_chapter_number(txt)
                    num  = nm if nm is not None else float(cid)
                    chapters[num] = href
            return chapters
        except Exception as e:
            print(f"[AcQQ] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        loop = asyncio.new_event_loop()
        r    = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(r.keys()) if r else None


# ─────────────────────────────────────────────────────────────────
#  Kuaikan — 快看漫画
# ─────────────────────────────────────────────────────────────────
class KuaikanProvider(BaseProvider):
    """
    مزود Kuaikan Manga (kuaikan.com / kuaikanmanhua.com).
    """

    API  = "https://www.kuaikanmanhua.com/api/v1"
    BASE = "https://www.kuaikanmanhua.com"

    def __init__(self):
        super().__init__()
        self.headers.update({
            "Referer":       "https://www.kuaikanmanhua.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def _extract_topic_id(self, url: str) -> str:
        m = re.search(r'/web/topic/(\d+)', url)
        if not m:
            m = re.search(r'/topic/(\d+)', url)
        if not m:
            m = re.search(r'/(\d+)(?:/|$)', url)
        return m.group(1) if m else None

    def _extract_comic_id(self, url: str) -> str:
        m = re.search(r'/web/comic/(\d+)', url)
        return m.group(1) if m else None

    async def get_images(self, url: str):
        try:
            comic_id = self._extract_comic_id(url)
            if comic_id:
                async with aiohttp.ClientSession(headers=self.headers) as s:
                    async with s.get(
                        f"{self.API}/comic/{comic_id}",
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as r:
                        if r.status == 200:
                            data   = await r.json()
                            images = data.get("images", [])
                            if images:
                                return [img.get("url", "") for img in images if img.get("url")]

            html = self.fetch_html(url)
            if not html:
                return []
            # NEXT_DATA أو متغيرات JS
            m = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.+?});', html, re.S)
            if m:
                try:
                    data   = json.loads(m.group(1))
                    images = re.findall(
                        r'"url"\s*:\s*"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
                        json.dumps(data)
                    )
                    return images
                except Exception:
                    pass
            return []
        except Exception as e:
            print(f"[Kuaikan] get_images error: {e}")
            return []

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            topic_id = self._extract_topic_id(series_url)
            if not topic_id:
                return {}

            async with aiohttp.ClientSession(headers=self.headers) as s:
                async with s.get(
                    f"{self.API}/topic/{topic_id}/comiclist?page=1&count=500",
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as r:
                    if r.status == 200:
                        data  = await r.json()
                        clist = data.get("comiclist", []) or data.get("comics", [])
                        chapters = {}
                        for i, ch in enumerate(clist):
                            ch_id  = ch.get("id")
                            title  = ch.get("title", "")
                            num    = self.extract_chapter_number(title) or float(i + 1)
                            ch_url = f"{self.BASE}/web/comic/{ch_id}"
                            if ch_id:
                                chapters[num] = ch_url
                        return chapters

            html = self.fetch_html(series_url)
            if not html:
                return {}
            soup     = BeautifulSoup(html, "html.parser")
            chapters = {}
            for a in soup.select("a[href*='/web/comic/']"):
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = urljoin(self.BASE, href)
                m   = re.search(r'/web/comic/(\d+)', href)
                txt = a.get_text(strip=True)
                nm  = self.extract_chapter_number(txt)
                if m and nm is not None:
                    chapters[nm] = href
            return chapters
        except Exception as e:
            print(f"[Kuaikan] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        loop = asyncio.new_event_loop()
        r    = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(r.keys()) if r else None


# ─────────────────────────────────────────────────────────────────
#  LINE Manga — manga.line.me
# ─────────────────────────────────────────────────────────────────
class LineMangaProvider(BaseProvider):
    """
    مزود LINE Manga (manga.line.me) — الفصول المجانية.
    """

    BASE = "https://manga.line.me"
    API  = "https://manga.line.me/a"

    def __init__(self):
        super().__init__()
        self.headers.update({
            "Referer":       "https://manga.line.me/",
            "Accept-Language": "ja-JP,ja;q=0.9",
        })

    def _extract_product_id(self, url: str) -> str:
        m = re.search(r'/product/(\d+)', url)
        return m.group(1) if m else None

    def _extract_chapter_id(self, url: str) -> str:
        m = re.search(r'/viewer/(\d+)', url)
        if not m:
            m = re.search(r'/chapter/(\d+)', url)
        return m.group(1) if m else None

    async def get_images(self, url: str):
        try:
            html = self.fetch_html(url)
            if not html:
                return []
            soup = BeautifulSoup(html, "html.parser")

            # طريقة 1: inline JSON
            for script in soup.find_all("script"):
                content = script.string or ""
                if "contentUrl" in content or "imageUrl" in content:
                    imgs = re.findall(
                        r'"(?:contentUrl|imageUrl|src)"\s*:\s*"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
                        content
                    )
                    if imgs:
                        return [i.replace("\\u002F", "/") for i in imgs]

            # طريقة 2: img مباشر
            images = []
            for img in soup.select("img[src*='manga.line.me'], img[src*='linem.jp']"):
                src = img.get("src") or img.get("data-src") or ""
                if src.startswith("http") and src not in images:
                    images.append(src)
            return images
        except Exception as e:
            print(f"[LINEManga] get_images error: {e}")
            return []

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            product_id = self._extract_product_id(series_url)
            if not product_id:
                return {}

            html = self.fetch_html(series_url)
            if not html:
                return {}
            soup     = BeautifulSoup(html, "html.parser")
            chapters = {}

            for a in soup.select("a[href*='/viewer/'], a[href*='/chapter/']"):
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = urljoin(self.BASE, href)
                txt = a.get_text(strip=True)
                nm  = self.extract_chapter_number(txt)
                m   = re.search(r'/(?:viewer|chapter)/(\d+)', href)
                if m:
                    num = nm if nm is not None else float(m.group(1))
                    chapters[num] = href
            return chapters
        except Exception as e:
            print(f"[LINEManga] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        loop = asyncio.new_event_loop()
        r    = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(r.keys()) if r else None


# ─────────────────────────────────────────────────────────────────
#  Piccoma — piccoma.com / piccoma.jp
# ─────────────────────────────────────────────────────────────────
class PiccomaProvider(BaseProvider):
    """
    مزود Piccoma (piccoma.com / piccoma.jp) — المحتوى المجاني الأسبوعي.
    """

    def __init__(self):
        super().__init__()

    def _base(self, url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    def _extract_ids(self, url: str):
        m = re.search(r'/product/(\d+).*?episode/(\d+)', url)
        if m:
            return m.group(1), m.group(2)
        m = re.search(r'/product/(\d+)', url)
        return (m.group(1), None) if m else (None, None)

    async def get_images(self, url: str):
        try:
            html = self.fetch_html(url)
            if not html:
                return []
            soup = BeautifulSoup(html, "html.parser")

            # طريقة 1: NEXT_DATA
            nd = soup.find("script", id="__NEXT_DATA__")
            if nd:
                try:
                    text = json.dumps(json.loads(nd.string))
                    imgs = re.findall(
                        r'"(https?://[^"]+piccoma[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
                        text
                    )
                    if imgs:
                        return [i.replace("\\u002F", "/") for i in imgs]
                except Exception:
                    pass

            # طريقة 2: JavaScript inline
            for script in soup.find_all("script"):
                content = script.string or ""
                if "pageImageList" in content or "imageUrls" in content:
                    imgs = re.findall(
                        r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', content
                    )
                    clean = [i for i in imgs if "piccoma" in i or "p-cdn" in i]
                    if clean:
                        return clean

            # طريقة 3: img tags
            images = []
            for img in soup.select("img[src*='piccoma'], img[src*='p-cdn']"):
                src = img.get("src") or img.get("data-src") or ""
                if src.startswith("http") and src not in images:
                    images.append(src)
            return images
        except Exception as e:
            print(f"[Piccoma] get_images error: {e}")
            return []

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            html = self.fetch_html(series_url)
            if not html:
                return {}
            soup     = BeautifulSoup(html, "html.parser")
            base     = self._base(series_url)
            chapters = {}

            for a in soup.select("a[href*='/episode/'], a[href*='/viewer/']"):
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = urljoin(base, href)
                txt = a.get_text(strip=True)
                nm  = self.extract_chapter_number(txt)
                m   = re.search(r'/episode/(\d+)', href)
                if m:
                    num = nm if nm is not None else float(m.group(1))
                    chapters[num] = href
            return chapters
        except Exception as e:
            print(f"[Piccoma] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        loop = asyncio.new_event_loop()
        r    = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(r.keys()) if r else None


# ─────────────────────────────────────────────────────────────────
#  iQiyi Manhua — manhua.iqiyi.com
# ─────────────────────────────────────────────────────────────────
class IqiyiProvider(BaseProvider):
    """
    مزود iQiyi Manhua (manhua.iqiyi.com) — كوميكس iQiyi الصينية.
    """

    BASE = "https://manhua.iqiyi.com"

    def __init__(self):
        super().__init__()
        self.headers.update({
            "Referer":       "https://manhua.iqiyi.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    async def get_images(self, url: str):
        try:
            html = self.fetch_html(url)
            if not html:
                return []
            # iQiyi يضع الصور في window.__initData__
            m = re.search(r'window\.__initData__\s*=\s*({.+?});\s*(?:window|var)', html, re.S)
            if m:
                try:
                    data = json.loads(m.group(1))
                    text = json.dumps(data)
                    imgs = re.findall(
                        r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', text
                    )
                    clean = [i for i in imgs if "qpic" in i or "iqiyi" in i]
                    if clean:
                        return clean
                except Exception:
                    pass

            imgs = re.findall(
                r'"(https?://[^"]+(?:qpic|iqiyi)[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', html
            )
            return list(dict.fromkeys(imgs))
        except Exception as e:
            print(f"[iQiyi] get_images error: {e}")
            return []

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            html = self.fetch_html(series_url)
            if not html:
                return {}
            soup     = BeautifulSoup(html, "html.parser")
            chapters = {}
            for a in soup.select("a[href*='/manhua/']"):
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = urljoin(self.BASE, href)
                txt = a.get_text(strip=True)
                nm  = self.extract_chapter_number(txt)
                m   = re.search(r'/(\d+)(?:/|\.html)', href)
                if m and nm is not None:
                    chapters[nm] = href
            return chapters
        except Exception as e:
            print(f"[iQiyi] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        loop = asyncio.new_event_loop()
        r    = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(r.keys()) if r else None
