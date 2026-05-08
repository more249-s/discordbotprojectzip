import re
import json
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
from urllib.parse import urljoin, urlparse
from typing import List, Optional


class GenericProvider(BaseProvider):
    """مزود عام ذكي: يجرب HTML + Next.js + Pagination + API"""

    def get_latest_chapter(self, url: str) -> Optional[float]:
        chapters = self.get_all_chapters(url)
        return max(chapters.keys()) if chapters else None

    def get_all_chapters(self, url: str) -> dict:
        html = self.fetch_html(url)
        if not html:
            return {}
        soup = BeautifulSoup(html, 'html.parser')

        # 1. __NEXT_DATA__
        nd = soup.find('script', id='__NEXT_DATA__')
        if nd:
            try:
                chs = self._chapters_from_json(json.dumps(json.loads(nd.string)), url)
                if len(chs) > 5:
                    return chs
            except Exception:
                pass

        # 2. HTML links
        chs = self._from_html_links(soup, url)

        # 3. Pagination إذا وجدنا عدد قليل
        if len(chs) < 25:
            extra = self._paginate_chapters(
                url,
                lambda h, u: self._from_html_links(BeautifulSoup(h, 'html.parser'), u),
            )
            chs.update(extra)

        # 4. إذا لا شيء جرب API شائعة
        if not chs:
            chs = self._try_generic_apis(url)

        return chs

    def _from_html_links(self, soup, base_url: str) -> dict:
        chs    = {}
        parsed = urlparse(base_url)
        base   = f"{parsed.scheme}://{parsed.netloc}"

        for a in soup.find_all('a', href=True):
            href = a['href']
            if not href.startswith('http'):
                href = urljoin(base, href)
            text = a.get_text(strip=True)
            val  = self.extract_chapter_number(text)
            if val is None:
                m = re.search(r'chapter[s]?[-/](\d+(?:\.\d+)?)', href, re.I)
                if m:
                    try:
                        val = float(m.group(1))
                    except Exception:
                        pass
            if val is not None and base.split('//')[1].split('/')[0] in href:
                chs[val] = href
        return chs

    def _chapters_from_json(self, text: str, base_url: str) -> dict:
        chs    = {}
        parsed = urlparse(base_url)
        base   = f"{parsed.scheme}://{parsed.netloc}"
        for m in re.finditer(
            r'"((?:https?://[^"]+|/[^"]+)/chapter[s]?[-/](\d+(?:\.\d+)?)(?:[/"\\]))',
            text,
        ):
            href = m.group(1).replace('\\u002F', '/').replace('\\', '')
            if not href.startswith('http'):
                href = urljoin(base, href)
            try:
                chs[float(m.group(2))] = href
            except Exception:
                pass
        return chs

    def _try_generic_apis(self, series_url: str) -> dict:
        """يجرب API endpoints عامة شائعة في مواقع المانجا"""
        parsed = urlparse(series_url)
        base   = f"{parsed.scheme}://{parsed.netloc}"
        slug   = series_url.rstrip('/').split('/')[-1]
        chs    = {}
        for ep in [
            f"{base}/api/chapters?series={slug}&limit=9999",
            f"{base}/api/manga/{slug}/chapters",
            f"{base}/api/comic/{slug}/chapters",
        ]:
            try:
                data = self.fetch_json(ep)
                if data:
                    text = json.dumps(data)
                    found = self._chapters_from_json(text, series_url)
                    if found:
                        chs.update(found)
                        break
            except Exception:
                continue
        return chs

    def get_images(self, url: str) -> List[str]:
        html = self.fetch_html(url)
        if not html:
            return []
        soup   = BeautifulSoup(html, 'html.parser')
        images = []

        # 1. __NEXT_DATA__
        nd = soup.find('script', id='__NEXT_DATA__')
        if nd:
            try:
                images = self._regex_images(json.dumps(json.loads(nd.string)))
                if images:
                    return images
            except Exception:
                pass

        # 2. سلكتورات شائعة
        for sel in [
            '#readerarea', '.rdminimal', '.chapter-content',
            '.reading-content', '[class*="reader"]',
            '[id*="reader"]', '.page-break',
        ]:
            div = soup.select_one(sel)
            if not div:
                continue
            for img in div.find_all('img'):
                src = (img.get('data-src') or img.get('src') or '').strip()
                if src.startswith('http') and src not in images:
                    images.append(src)
            if images:
                return images

        # 3. scripts
        for script in soup.find_all('script'):
            content = script.string or ''
            if any(x in content for x in ['.webp', '.jpg', '.jpeg', '.png']):
                for f in self._regex_images(content):
                    if f not in images:
                        images.append(f)
        if images:
            return images

        return self._regex_images(html)

    def _regex_images(self, text: str) -> list:
        images = []
        for pat in [
            r'"src"\s*:\s*"(https?://[^"]+\.(?:webp|jpg|jpeg|png)[^"]*)"',
            r'"url"\s*:\s*"(https?://[^"]+\.(?:webp|jpg|jpeg|png)[^"]*)"',
            r'https?://[a-zA-Z0-9\-_.]+/[^"\'\s<>]+?\.(?:webp|jpg|jpeg|png)(?:\?[^"\'\s<>]*)?',
        ]:
            for m in re.findall(pat, text, re.IGNORECASE):
                src = (m if isinstance(m, str) else m[0])
                src = src.replace('\\u002F', '/').replace('\\', '').strip().rstrip('"')
                if src.startswith('http') and src not in images:
                    if not any(x in src.lower() for x in ['logo', 'avatar', 'icon', 'banner', 'cover', 'ads', 'thumb']):
                        images.append(src)
        return images
