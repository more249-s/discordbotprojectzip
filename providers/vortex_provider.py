import re
import json
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
from urllib.parse import urljoin, urlparse


class VortexProvider(BaseProvider):
    """مزود VortexScans"""

    def __init__(self):
        super().__init__()
        self.base_url = "https://vortexscans.org"
        self.headers['Referer'] = self.base_url + '/'

    async def get_images(self, url: str):
        try:
            html = self.fetch_html(url, {'Referer': self.base_url + '/'})
            if not html:
                return []

            soup = BeautifulSoup(html, 'html.parser')
            images = []

            # 1. الصور في img tags مع مسار upload/series (الطريقة الأكيدة)
            for img in soup.find_all('img'):
                src = (img.get('src') or img.get('data-src') or '').strip()
                if 'upload/series' in src and src not in images:
                    # تنظيف wsrv proxy إذا وُجد
                    if 'wsrv.nl' in src:
                        m = re.search(r'url=([^&]+)', src)
                        if m:
                            import urllib.parse
                            src = urllib.parse.unquote(m.group(1))
                    images.append(src)

            if images:
                return images

            # 2. regex على كامل HTML
            patterns = re.findall(
                r'https?://storage\.vortexscans\.org/upload/series/[^"\'\s<>]+?\.(?:webp|jpg|jpeg|png)',
                html, re.IGNORECASE
            )
            for p in patterns:
                if p not in images:
                    images.append(p)

            if images:
                return images

            # 3. أي img tag بـ src يحتوي vortexscans
            for img in soup.find_all('img'):
                src = (img.get('src') or '').strip()
                if 'vortexscans' in src and src not in images:
                    if not any(x in src.lower() for x in ['logo', 'icon', 'avatar']):
                        images.append(src)

            return images
        except Exception as e:
            print(f"[VortexScans] get_images error: {e}")
            return []

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            html = self.fetch_html(series_url)
            if not html:
                return {}

            soup = BeautifulSoup(html, 'html.parser')
            chapters = {}
            parsed = urlparse(series_url)
            base = f"{parsed.scheme}://{parsed.netloc}"

            for a in soup.find_all('a', href=True):
                href = a['href']
                if not href.startswith('http'):
                    href = urljoin(base, href)
                m = re.search(r'/chapter[s]?[-/](\d+(?:\.\d+)?)', href, re.I)
                if m and 'vortexscans' in href:
                    num = float(m.group(1))
                    if num not in chapters:
                        chapters[num] = href

            return chapters
        except Exception as e:
            print(f"[VortexScans] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        import asyncio
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(result.keys()) if result else None
