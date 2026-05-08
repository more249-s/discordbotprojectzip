import re
import json
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
from urllib.parse import urljoin, urlparse


class KakaoProvider(BaseProvider):
    """
    مزود Kakao Page / Kakao Webtoon — الفصول المجانية والمجدولة.
    يدعم: page.kakao.com, webtoon.kakao.com
    """

    def __init__(self):
        super().__init__()
        self.headers.update({
            "Referer":  "https://page.kakao.com/",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        })

    def _is_webtoon(self, url: str) -> bool:
        return "webtoon.kakao.com" in url

    def _extract_series_id(self, url: str) -> str:
        m = re.search(r'/content/(\d+)', url)
        if not m:
            m = re.search(r'/webtoon/(\d+)', url)
        if not m:
            m = re.search(r'seriesId=(\d+)', url)
        return m.group(1) if m else None

    def _extract_chapter_id(self, url: str) -> str:
        m = re.search(r'/episode/(\d+)', url)
        if not m:
            m = re.search(r'/viewer/(\d+)', url)
        if not m:
            m = re.search(r'episodeId=(\d+)', url)
        return m.group(1) if m else None

    async def get_images(self, url: str):
        try:
            html = self.fetch_html(url)
            if not html:
                return []
            soup = BeautifulSoup(html, "html.parser")

            # طريقة 1: __NEXT_DATA__
            nd = soup.find("script", id="__NEXT_DATA__")
            if nd:
                try:
                    data  = json.loads(nd.string)
                    text  = json.dumps(data)
                    imgs  = re.findall(
                        r'"(https?://[^"]+(?:kakaocdn|kakao)[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
                        text
                    )
                    clean = []
                    for img in imgs:
                        src = img.replace("\\u002F", "/").replace("\\", "")
                        if src not in clean:
                            clean.append(src)
                    if clean:
                        return clean
                except Exception:
                    pass

            # طريقة 2: API داخلي
            ch_id = self._extract_chapter_id(url)
            if ch_id:
                api_urls = [
                    f"https://page.kakao.com/api/viewerData?episodeId={ch_id}",
                    f"https://webtoon.kakao.com/api/viewerData?episodeId={ch_id}",
                ]
                async with aiohttp.ClientSession(headers=self.headers) as session:
                    for api_url in api_urls:
                        try:
                            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                                if r.status == 200:
                                    data = await r.json()
                                    imgs = re.findall(
                                        r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
                                        json.dumps(data)
                                    )
                                    if imgs:
                                        return [i.replace("\\u002F", "/") for i in imgs]
                        except Exception:
                            continue

            # طريقة 3: سكريبتات وصور مباشرة
            images = []
            for img in soup.select("img[src*='kakaocdn'], img[src*='kakao']"):
                src = img.get("src") or img.get("data-src") or ""
                if src.startswith("http") and src not in images:
                    images.append(src)
            return images

        except Exception as e:
            print(f"[Kakao] get_images error: {e}")
            return []

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            series_id = self._extract_series_id(series_url)
            if not series_id:
                return {}

            chapters = {}
            page     = 1

            async with aiohttp.ClientSession(headers=self.headers) as session:
                while True:
                    for api_base in [
                        "https://page.kakao.com/api",
                        "https://webtoon.kakao.com/api",
                    ]:
                        try:
                            ep_url = f"{api_base}/episodeList?seriesId={series_id}&page={page}&size=100"
                            async with session.get(ep_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                                if r.status == 200:
                                    data = await r.json()
                                    eps  = data.get("data", {}).get("episodeList", []) or data.get("episodes", [])
                                    if eps:
                                        for ep in eps:
                                            ep_id  = ep.get("id") or ep.get("episodeId")
                                            ep_num = ep.get("episodeSequence") or ep.get("order") or ep.get("number")
                                            if ep_id and ep_num is not None:
                                                try:
                                                    num = float(ep_num)
                                                    ch_url = f"https://page.kakao.com/content/{series_id}/episode/{ep_id}"
                                                    if num not in chapters:
                                                        chapters[num] = ch_url
                                                except Exception:
                                                    pass
                                        if len(eps) < 100:
                                            break
                                        page += 1
                                        continue
                        except Exception:
                            continue
                    break

            # Fallback: HTML scraping
            if not chapters:
                html = self.fetch_html(series_url)
                if html:
                    soup = BeautifulSoup(html, "html.parser")
                    nd = soup.find("script", id="__NEXT_DATA__")
                    if nd:
                        try:
                            text = json.dumps(json.loads(nd.string))
                            for m in re.finditer(r'"episode(?:Id|Sequence)"\s*:\s*(\d+)', text):
                                pass
                            ep_pairs = re.findall(
                                r'"id"\s*:\s*(\d+).*?"episodeSequence"\s*:\s*(\d+)',
                                text
                            )
                            for ep_id, ep_seq in ep_pairs:
                                try:
                                    num = float(ep_seq)
                                    chapters[num] = f"https://page.kakao.com/content/{series_id}/episode/{ep_id}"
                                except Exception:
                                    pass
                        except Exception:
                            pass

            return chapters
        except Exception as e:
            print(f"[Kakao] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(result.keys()) if result else None
