import re
import json
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
from urllib.parse import urljoin, urlparse


class AsuraProvider(BaseProvider):
    """مزود AsuraScans - يستخدم Next.js مع بيانات JSON مضمّنة"""

    DOMAINS = ['asurascans.com', 'asura.gg', 'asuracomics.com', 'asuratoon.com',
               'asuracomic.net', 'asura.nacm.xyz']

    def __init__(self):
        super().__init__()
        self.base_url = "https://asuracomic.net"
        self.headers['Referer'] = self.base_url + '/'

    def _normalize_url(self, url: str) -> str:
        for domain in self.DOMAINS:
            if domain in url:
                return url
        return url

    async def get_images(self, url: str):
        try:
            url = self._normalize_url(url)
            html = self.fetch_html(url, {'Referer': self.base_url + '/'})
            if not html:
                return []

            soup = BeautifulSoup(html, 'html.parser')
            images = []

            # 1. محاولة __NEXT_DATA__
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    images = self._extract_images_from_json(json.dumps(data))
                    if images:
                        return images
                except Exception:
                    pass

            # 2. استخراج من script tags
            for script in soup.find_all('script'):
                content = script.string or ''
                if any(ext in content for ext in ['.webp', '.jpg', '.jpeg', '.png']):
                    found = self._extract_images_from_json(content)
                    if found:
                        images.extend(f for f in found if f not in images)
                    if len(images) > 3:
                        return images

            # 3. استخراج تقليدي
            reader_divs = [
                soup.select_one('#readerarea'),
                soup.select_one('.rdminimal'),
                soup.select_one('[class*="reader"]'),
                soup.select_one('[id*="reader"]'),
                soup.select_one('.chapter-content'),
            ]
            for div in reader_divs:
                if not div:
                    continue
                for img in div.find_all('img'):
                    src = (img.get('data-src') or img.get('src') or '').strip()
                    if src.startswith('http') and src not in images:
                        if not any(x in src.lower() for x in ['logo', 'avatar', 'icon']):
                            images.append(src)
                if images:
                    return images

            # 4. regex على كامل HTML
            if not images:
                images = self._extract_images_from_json(html)

            return images
        except Exception as e:
            print(f"[AsuraScans] get_images error: {e}")
            return []

    def _extract_images_from_json(self, text: str) -> list:
        images = []
        patterns = [
            r'"src"\s*:\s*"(https?://[^"]+\.(?:webp|jpg|jpeg|png)[^"]*)"',
            r'"url"\s*:\s*"(https?://[^"]+\.(?:webp|jpg|jpeg|png)[^"]*)"',
            r'https?://[a-zA-Z0-9\-_.]+/[^"\'\s<>]+?\.(?:webp|jpg|jpeg|png)',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, text, re.IGNORECASE):
                if isinstance(match, tuple):
                    match = match[0]
                cleaned = match.replace('\\u002F', '/').replace('\\n', '').replace('\\', '').strip().rstrip('"')
                if cleaned.startswith('http') and cleaned not in images:
                    if not any(x in cleaned.lower() for x in ['logo', 'avatar', 'icon', 'banner', 'cover', 'thumb']):
                        images.append(cleaned)
        return images

    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            html = self.fetch_html(series_url)
            if not html:
                return {}

            soup = BeautifulSoup(html, 'html.parser')
            chapters = {}

            # 1. محاولة __NEXT_DATA__
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    text = json.dumps(data)
                    # البحث عن روابط الفصول في البيانات
                    parsed = urlparse(series_url)
                    base = f"{parsed.scheme}://{parsed.netloc}"
                    for m in re.finditer(r'"((?:https?://[^"]+|/[^"]+)/chapter[s]?/(\d+(?:\.\d+)?))"', text):
                        href = m.group(1).replace('\\u002F', '/').replace('\\', '')
                        num = float(m.group(2))
                        if not href.startswith('http'):
                            href = urljoin(base, href)
                        # التحقق من أن الرابط ليس مجرد جزء من رابط آخر
                        if "/chapter" in href.lower():
                            chapters[num] = href

                    # محاولة البحث عن slugs الفصول إذا لم نجد روابط كاملة
                    if not chapters:
                        for m in re.finditer(r'"slug"\s*:\s*"([^"]+)"\s*.*?"chapterNumber"\s*:\s*(\d+(?:\.\d+)?)', text):
                            slug = m.group(1)
                            num = float(m.group(2))
                            if "/chapter/" not in slug:
                                chapters[num] = f"{series_url.rstrip('/')}/{slug}"
                            else:
                                chapters[num] = urljoin(base, slug)

                    if chapters:
                        return chapters
                except Exception:
                    pass

            # 2. من الروابط التقليدية
            parsed = urlparse(series_url)
            base = f"{parsed.scheme}://{parsed.netloc}"

            def _extract(h, b):
                s = BeautifulSoup(h, 'html.parser')
                res = {}
                selectors = [
                    'div.eph-num a',
                    'li.wp-manga-chapter a',
                    'a[href*="/chapter"]',
                    'a[href*="chapter-"]',
                ]
                for sel in selectors:
                    for a in s.select(sel):
                        href = a.get('href', '').strip()
                        if not href: continue
                        if not href.startswith('http'):
                            href = urljoin(base, href)
                        m = re.search(r'chapter[s]?[-/](\d+(?:\.\d+)?)', href, re.I)
                        if not m:
                            m = re.search(r'chapter[s]?[-/](\d+(?:\.\d+)?)', a.get_text(), re.I)
                        if m:
                            num = float(m.group(1))
                            if num not in res:
                                res[num] = href
                return res

            chapters = _extract(html, series_url)

            # محاولة جلب الصفحات الأخرى إذا كان هناك ترقيم صفحات
            extra = self._paginate_chapters(series_url, _extract)
            chapters.update(extra)

            return chapters
        except Exception as e:
            print(f"[AsuraScans] get_all_chapters error: {e}")
            return {}

    def get_latest_chapter(self, url: str):
        import asyncio
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(result.keys()) if result else None
