import re
import aiohttp
import asyncio
from .base_provider import BaseProvider
from urllib.parse import urlparse


class MangaDexProvider(BaseProvider):
    """مزود MangaDex - يستخدم API رسمي مجاني"""

    API = "https://api.mangadex.org"

    def __init__(self):
        super().__init__()

    def _extract_id(self, url: str) -> str:
        """استخراج UUID من رابط MangaDex"""
        m = re.search(r'/(?:manga|chapter|title)/([0-9a-f-]{36})', url)
        return m.group(1) if m else None

    async def get_images(self, url: str):
        try:
            chapter_id = self._extract_id(url)
            if not chapter_id:
                return []

            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.API}/at-home/server/{chapter_id}", timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status != 200:
                        return []
                    data = await r.json()

            base = data['baseUrl']
            chapter = data['chapter']
            quality = 'data'  # أعلى جودة

            images = [
                f"{base}/{quality}/{chapter['hash']}/{filename}"
                for filename in chapter[quality]
            ]
            return images
        except Exception as e:
            print(f"[MangaDex] get_images error: {e}")
            return []

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            manga_id = self._extract_id(series_url)
            if not manga_id:
                return {}

            chapters = {}
            offset = 0
            limit = 100

            async with aiohttp.ClientSession() as session:
                while True:
                    params = {
                        'manga': manga_id,
                        'limit': limit,
                        'offset': offset,
                        'translatedLanguage[]': ['en', 'ar'],
                        'order[chapter]': 'asc',
                        'contentRating[]': ['safe', 'suggestive', 'erotica', 'pornographic'],
                    }
                    async with session.get(f"{self.API}/chapter", params=params,
                                           timeout=aiohttp.ClientTimeout(total=15)) as r:
                        if r.status != 200:
                            break
                        data = await r.json()

                    for ch in data.get('data', []):
                        ch_num_str = ch['attributes'].get('chapter')
                        ch_id = ch['id']
                        if ch_num_str:
                            try:
                                ch_num = float(ch_num_str)
                                ch_url = f"https://mangadex.org/chapter/{ch_id}"
                                if ch_num not in chapters:
                                    chapters[ch_num] = ch_url
                            except Exception:
                                pass

                    total = data.get('total', 0)
                    offset += limit
                    if offset >= total:
                        break

            return chapters
        except Exception as e:
            print(f"[MangaDex] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(result.keys()) if result else None
