import re
import json
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
from urllib.parse import urljoin, urlparse
from typing import List, Optional


class GenericProvider(BaseProvider):
    """مزود عام ذكي يجرب عدة طرق تلقائياً"""

    def get_latest_chapter(self, url: str) -> Optional[float]:
        chapters = self.get_all_chapters(url)
        return max(chapters.keys()) if chapters else None

    def get_all_chapters(self, url: str) -> dict:
        html = self.fetch_html(url)
        if not html:
            return {}

        soup = BeautifulSoup(html, 'html.parser')
        chapters = {}
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        for a in soup.find_all('a'):
            href = a.get('href')
            if not href:
                continue
            if not href.startswith('http'):
                href = urljoin(base, href)

            text = a.get_text(strip=True)
            val = self.extract_chapter_number(text)
            if val is None:
                m = re.search(r'chapter[s]?[-/](\d+(?:\.\d+)?)', href, re.I)
                if m:
                    try:
                        val = float(m.group(1))
                    except Exception:
                        pass
            if val is not None:
                chapters[val] = href

        return chapters

    def get_images(self, url: str) -> List[str]:
        html = self.fetch_html(url)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        images = []

        # 1. محاولة __NEXT_DATA__
        next_data = soup.find('script', id='__NEXT_DATA__')
        if next_data:
            try:
                text = json.dumps(json.loads(next_data.string))
                images = self._extract_images_regex(text)
                if images:
                    return images
            except Exception:
                pass

        # 2. سلكتورات شائعة
        selectors = [
            '#readerarea', '.rdminimal', '.chapter-content',
            '.reading-content', '.canvas-container', '[class*="reader"]',
            '[id*="reader"]', '.page-break',
        ]
        for sel in selectors:
            div = soup.select_one(sel)
            if not div:
                continue
            for img in div.find_all('img'):
                src = (img.get('data-src') or img.get('src') or '').strip()
                if src.startswith('http') and src not in images:
                    images.append(src)
            if images:
                return images

        # 3. regex على الـ scripts
        for script in soup.find_all('script'):
            content = script.string or ''
            if any(x in content for x in ['.webp', '.jpg', '.jpeg', '.png']):
                found = self._extract_images_regex(content)
                images.extend(f for f in found if f not in images)
        if images:
            return images

        # 4. regex على كامل HTML
        images = self._extract_images_regex(html)
        return images

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
                    if not any(x in cleaned.lower() for x in ['logo', 'avatar', 'icon', 'banner', 'cover', 'ads', 'thumb']):
                        images.append(cleaned)
        return images
