import re
import aiohttp
import asyncio
from .base_provider import BaseProvider
from urllib.parse import urlparse


class ComickProvider(BaseProvider):
    """
    مزود Comick.fun — يستخدم API رسمي مفتوح.
    يدعم: comick.fun, comick.io, comick.cc
    """

    API = "https://api.comick.fun"

    def __init__(self):
        super().__init__()

    def _extract_slug(self, url: str) -> str:
        m = re.search(r'/comic/([^/?#]+)', url)
        return m.group(1) if m else None

    def _extract_chapter_hid(self, url: str) -> str:
        m = re.search(r'/chapter/([^/?#]+)', url)
        return m.group(1) if m else None

    async def get_images(self, url: str):
        try:
            hid = self._extract_chapter_hid(url)
            if not hid:
                return []
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.API}/chapter/{hid}",
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as r:
                    if r.status != 200:
                        return []
                    data = await r.json()
            chapter = data.get("chapter", {})
            md_images = chapter.get("md_images", [])
            images = []
            for img in md_images:
                b2key = img.get("b2key", "")
                if b2key:
                    images.append(f"https://meo.comick.pictures/{b2key}")
            return images
        except Exception as e:
            print(f"[Comick] get_images error: {e}")
            return []

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            slug = self._extract_slug(series_url)
            if not slug:
                return {}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.API}/comic/{slug}",
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as r:
                    if r.status != 200:
                        return {}
                    comic_data = await r.json()

            hid = comic_data.get("comic", {}).get("hid")
            if not hid:
                return {}

            chapters = {}
            page = 1
            async with aiohttp.ClientSession() as session:
                while True:
                    params = {
                        "lang": "en,ar",
                        "page": page,
                        "limit": 300,
                        "order": "asc",
                    }
                    async with session.get(
                        f"{self.API}/comic/{hid}/chapters",
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as r:
                        if r.status != 200:
                            break
                        data = await r.json()
                    chs = data.get("chapters", [])
                    if not chs:
                        break
                    for ch in chs:
                        ch_num = ch.get("chap")
                        ch_hid = ch.get("hid")
                        if ch_num and ch_hid:
                            try:
                                num = float(ch_num)
                                url_ch = f"https://comick.fun/comic/{slug}/{ch_hid}-chapter-{ch_num}-en"
                                if num not in chapters:
                                    chapters[num] = url_ch
                            except Exception:
                                pass
                    if len(chs) < 300:
                        break
                    page += 1
            return chapters
        except Exception as e:
            print(f"[Comick] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(result.keys()) if result else None
