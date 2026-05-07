import re
import json
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
from urllib.parse import urljoin


class MadaraProvider(BaseProvider):
    """
    مزود عام لمواقع عائلة Madara WordPress + Next.js.
    يغطي: utoon, qimanhwa, toonily, flamescans, reaperscans, وغيرها.
    """

    def __init__(self, scraper=None):
        super().__init__(scraper)

    async def get_images(self, url: str):
        try:
            html = self.fetch_html(url, {'Referer': url})
            if not html:
                return []

            soup = BeautifulSoup(html, 'html.parser')
            images = []

            # 1. محاولة __NEXT_DATA__ (لمواقع Next.js)
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    text = json.dumps(data)
                    images = self._extract_images_regex(text)
                    if images:
                        return images
                except Exception:
                    pass

            # 2. سلكتورات Madara الكلاسيكية
            selectors = [
                "div.reading-content img",
                "div.page-break img",
                "div#chapter-images img",
                "div.wp-manga-chapter-img img",
                "img.wp-manga-chapter-img",
                "div[data-reader-page-image] img",
                "div.chapter-images img",
                "div.read-container img",
                "div.viewer-images img",
                "div#reader-images img",
                "img[data-src]",
            ]
            for selector in selectors:
                for img in soup.select(selector):
                    src = (img.get('data-src') or img.get('data-lazy-src') or
                           img.get('data-cfsrc') or img.get('src') or '').strip()
                    if not src:
                        continue
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif not src.startswith('http'):
                        src = urljoin(url, src)
                    if src not in images and not any(x in src.lower() for x in ['logo', 'banner', 'ads', 'icon', 'avatar']):
                        images.append(src)
                if images:
                    return images

            # 3. regex على كل الـ scripts
            for script in soup.find_all('script'):
                content = script.string or ''
                if any(x in content for x in ['.webp', '.jpg', '.jpeg', '.png']):
                    found = self._extract_images_regex(content)
                    for f in found:
                        if f not in images:
                            images.append(f)
                if len(images) > 3:
                    return images

            # 4. regex على كامل HTML
            if not images:
                images = self._extract_images_regex(html)

            return images
        except Exception as e:
            print(f"[Madara] get_images error for {url}: {e}")
            return []

    def _extract_images_regex(self, text: str) -> list:
        images = []
        patterns = [
            r'"src"\s*:\s*"(https?://[^"]+\.(?:webp|jpg|jpeg|png)[^"]*)"',
            r'"url"\s*:\s*"(https?://[^"]+\.(?:webp|jpg|jpeg|png)[^"]*)"',
            r'https?://[a-zA-Z0-9\-_.]+/[^"\'\s<>]+?\.(?:webp|jpg|jpeg|png)(?:\?[^"\'\s<>]*)?',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, text, re.IGNORECASE):
                if isinstance(match, tuple):
                    match = match[0]
                cleaned = match.replace('\\u002F', '/').replace('\\', '').strip().rstrip('"')
                if cleaned.startswith('http') and cleaned not in images:
                    if not any(x in cleaned.lower() for x in ['logo', 'avatar', 'icon', 'banner', 'cover', 'ads']):
                        images.append(cleaned)
        return images

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            html = self.fetch_html(series_url)
            if not html:
                return {}

            soup = BeautifulSoup(html, 'html.parser')

            # محاولة __NEXT_DATA__ أولاً
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    chapters = self._extract_chapters_from_next(data, series_url)
                    if chapters:
                        return chapters
                except Exception:
                    pass

            chapters = self._extract_chapters_from_html(soup, series_url)

            if not chapters:
                chapters = await self._load_ajax_chapters(soup, series_url)

            return chapters
        except Exception as e:
            print(f"[Madara] get_all_chapters error: {e}")
            return {}

    def _extract_chapters_from_next(self, data: dict, series_url: str) -> dict:
        text = json.dumps(data)
        chapters = {}
        from urllib.parse import urlparse
        parsed = urlparse(series_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        for m in re.finditer(r'"((?:https?://[^"]+|/[^"]+)/(?:chapter[s]?|ch)[/-](\d+(?:\.\d+)?)(?:[/"\\]))'
                             , text):
            href = m.group(1).replace('\\u002F', '/').replace('\\', '')
            num = float(m.group(2))
            if not href.startswith('http'):
                href = urljoin(base, href)
            chapters[num] = href
        return chapters

    def _extract_chapters_from_html(self, soup, series_url: str) -> dict:
        chapters = {}
        selectors = [
            "li.wp-manga-chapter a",
            "div#chapterlist li a",
            "ul.main.version-chap li a",
            "div.eph-num a",
            "a[href*='/chapter']",
            "a[href*='chapter-']",
        ]
        for selector in selectors:
            for a in soup.select(selector):
                href = a.get('href', '').strip()
                if not href:
                    continue
                if not href.startswith('http'):
                    href = urljoin(series_url, href)
                text = a.get_text().lower()
                m = re.search(r'chapter\s*([\d.]+)', text) or re.search(r'(?:chapter[s]?|ch)[/-]([\d.]+)', href, re.I)
                if m:
                    try:
                        num = float(m.group(1))
                        chapters[num] = href
                    except Exception:
                        pass
            if chapters:
                break
        return chapters

    async def _load_ajax_chapters(self, soup, series_url: str) -> dict:
        try:
            holder = soup.select_one("#manga-chapters-holder")
            post_id = holder.get("data-id") if holder else None
            if not post_id:
                m = re.search(r'manga_id\s*:\s*(\d+)', str(soup))
                if m:
                    post_id = m.group(1)
            if post_id:
                base_url = "/".join(series_url.split("/")[:3])
                ajax_url = f"{base_url}/wp-admin/admin-ajax.php"
                resp = self.scraper.post(ajax_url, data={"action": "manga_get_chapters", "manga": post_id},
                                         headers=self.headers, timeout=10)
                if resp.status_code == 200:
                    ajax_soup = BeautifulSoup(resp.text, 'html.parser')
                    return self._extract_chapters_from_html(ajax_soup, series_url)
        except Exception:
            pass
        return {}

    def get_latest_chapter(self, url: str):
        import asyncio
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(result.keys()) if result else None
