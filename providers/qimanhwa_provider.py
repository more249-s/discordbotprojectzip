import re
import json
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
from urllib.parse import urljoin, urlparse


class QimanhwaProvider(BaseProvider):
    """مزود Qimanhwa (Qi Manhwa) - Angular-based"""

    def __init__(self):
        super().__init__()
        self.base_url = "https://qimanhwa.com"
        self.headers['Referer'] = self.base_url + '/'

    async def get_images(self, url: str):
        try:
            html = self.fetch_html(url, {'Referer': self.base_url + '/'})
            if not html:
                return []

            soup = BeautifulSoup(html, 'html.parser')
            images = []

            # الصور في img tags (Angular يضعها مباشرة في src)
            for img in soup.find_all('img'):
                src = (img.get('src') or img.get('data-src') or '').strip()
                if not src.startswith('http'):
                    continue
                if any(x in src.lower() for x in ['logo', 'icon', 'avatar', 'discord']):
                    continue
                # صور الفصول في media.qimanhwa.com مع مسار upload/series
                if ('qimanhwa.com' in src or 'qiscans' in src) and 'upload/series' in src:
                    if src not in images:
                        images.append(src)

            if images:
                return images

            # Fallback: أي صورة من نطاقات الـ CDN المعروفة
            for img in soup.find_all('img'):
                src = (img.get('src') or '').strip()
                if src.startswith('http') and src not in images:
                    if not any(x in src.lower() for x in ['logo', 'icon', 'avatar', 'discord', 'banner']):
                        images.append(src)

            return images
        except Exception as e:
            print(f"[Qimanhwa] get_images error: {e}")
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

            # محاولة استخراج من JSON-LD
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or '{}')
                    if isinstance(data, list):
                        for item in data:
                            if item.get('@type') == 'ComicIssue':
                                num_str = item.get('issueNumber', '')
                                link = item.get('url', '')
                                if num_str and link:
                                    chapters[float(num_str)] = link
                    elif data.get('@type') == 'ComicIssue':
                        num_str = data.get('issueNumber', '')
                        link = data.get('url', '')
                        if num_str and link:
                            chapters[float(num_str)] = link
                except Exception:
                    pass

            if chapters:
                return chapters

            # من الروابط
            for a in soup.find_all('a', href=True):
                href = a['href']
                if not href.startswith('http'):
                    href = urljoin(base, href)
                m = re.search(r'chapter[-/](\d+(?:\.\d+)?)', href, re.I)
                if m and 'qimanhwa' in href:
                    num = float(m.group(1))
                    if num not in chapters:
                        chapters[num] = href

            return chapters
        except Exception as e:
            print(f"[Qimanhwa] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        import asyncio
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(result.keys()) if result else None
