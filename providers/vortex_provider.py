import re
import json
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
from urllib.parse import urljoin, urlparse


class VortexProvider(BaseProvider):
    """مزود VortexScans — يدعم HTML + API + Pagination"""

    BASE = "https://vortexscans.org"

    def __init__(self):
        super().__init__()
        self.headers['Referer'] = self.BASE + '/'

    # ── صور الفصل ─────────────────────────────────────────────────────────
    async def get_images(self, url: str):
        try:
            html = self.fetch_html(url, {'Referer': self.BASE + '/'})
            if not html:
                return []
            soup   = BeautifulSoup(html, 'html.parser')
            images = []

            # 1. upload/series في img tags
            for img in soup.find_all('img'):
                src = (img.get('src') or img.get('data-src') or '').strip()
                if 'upload/series' in src and src not in images:
                    if 'wsrv.nl' in src:
                        m = re.search(r'url=([^&]+)', src)
                        if m:
                            import urllib.parse
                            src = urllib.parse.unquote(m.group(1))
                    images.append(src)
            if images:
                return images

            # 2. __NEXT_DATA__
            nd = soup.find('script', id='__NEXT_DATA__')
            if nd:
                try:
                    data = json.loads(nd.string)
                    text = json.dumps(data)
                    images = self._regex_images(text)
                    if images:
                        return images
                except Exception:
                    pass

            # 3. regex على storage.vortexscans
            for p in re.findall(
                r'https?://storage\.vortexscans\.org/upload/series/[^"\'\s<>]+?\.(?:webp|jpg|jpeg|png)',
                html, re.IGNORECASE
            ):
                if p not in images:
                    images.append(p)
            if images:
                return images

            # 4. أي img vortexscans
            for img in soup.find_all('img'):
                src = (img.get('src') or '').strip()
                if 'vortexscans' in src and src not in images:
                    if not any(x in src.lower() for x in ['logo', 'icon', 'avatar']):
                        images.append(src)
            return images
        except Exception as e:
            print(f"[VortexScans] get_images: {e}")
            return []

    def _regex_images(self, text: str) -> list:
        images = []
        for pat in [
            r'"src"\s*:\s*"(https?://[^"]+\.(?:webp|jpg|jpeg|png)[^"]*)"',
            r'"url"\s*:\s*"(https?://[^"]+\.(?:webp|jpg|jpeg|png)[^"]*)"',
        ]:
            for m in re.findall(pat, text, re.IGNORECASE):
                src = (m if isinstance(m, str) else m[0])
                src = src.replace('\\u002F', '/').replace('\\', '').strip()
                if src.startswith('http') and src not in images:
                    if not any(x in src.lower() for x in ['logo', 'cover', 'avatar', 'banner']):
                        images.append(src)
        return images

    # ── كل الفصول ─────────────────────────────────────────────────────────
    async def get_all_chapters(self, series_url: str) -> dict:
        try:
            slug   = series_url.rstrip('/').split('/')[-1]
            all_ch = {}

            # ── 1. API REST (أحدث sites غالباً بيكون عندها endpoint) ─────
            api_chs = await self._try_api(slug, series_url)
            all_ch.update(api_chs)

            # ── 2. __NEXT_DATA__ ──────────────────────────────────────────
            if not all_ch:
                html = self.fetch_html(series_url, {'Referer': self.BASE + '/'})
                if html:
                    soup = BeautifulSoup(html, 'html.parser')
                    all_ch.update(self._from_next(soup, series_url))
                    if not all_ch:
                        all_ch.update(self._from_html(soup, series_url))
            else:
                # حتى مع API جرب HTML للتأكد من عدم وجود فصول إضافية
                html = self.fetch_html(series_url, {'Referer': self.BASE + '/'})
                if html:
                    soup = BeautifulSoup(html, 'html.parser')
                    all_ch.update(self._from_next(soup, series_url))
                    all_ch.update(self._from_html(soup, series_url))

            # ── 3. Pagination إذا بدت الفصول قليلة ───────────────────────
            if len(all_ch) < 30:
                extra = self._paginate_chapters(
                    series_url,
                    self._extract_from_html_str,
                )
                all_ch.update(extra)

            return all_ch
        except Exception as e:
            print(f"[VortexScans] get_all_chapters: {e}")
            return {}

    async def get_chapters_with_lock_info(self, series_url: str) -> dict:
        """جلب الفصول مع كشف الفصول المقفلة"""
        try:
            slug   = series_url.rstrip('/').split('/')[-1]
            parsed = urlparse(series_url)
            base   = f"{parsed.scheme}://{parsed.netloc}"

            # محاولة جلب البيانات من الـ API لأنه غالباً يحتوي على حالة القفل
            api_url = f"{base}/api/chapters?series={slug}&page=1&limit=9999"
            data = self.fetch_json(api_url)

            locked_nums = set()
            all_chs = {}

            if data and isinstance(data, dict):
                # الهيكل المتوقع لـ Vortex هو list من الفصول
                items = data.get('chapters', data.get('data', []))
                if isinstance(items, dict): items = items.get('data', [])

                for item in items:
                    num = float(item.get('number', item.get('chapterNumber', 0)))
                    is_locked = item.get('is_locked', item.get('locked', False))
                    slug_ch = item.get('slug')
                    if num and slug_ch:
                        all_chs[num] = f"{series_url.rstrip('/')}/{slug_ch}"
                        if is_locked:
                            locked_nums.add(num)

            if not all_chs:
                all_chs = await self.get_all_chapters(series_url)

            # فحص الـ HTML للأقفال إذا لم نجدها في الـ API
            if not locked_nums:
                html = self.fetch_html(series_url)
                if html:
                    soup = BeautifulSoup(html, 'html.parser')
                    # البحث عن أيقونات القفل بجانب روابط الفصول
                    for a in soup.find_all('a', href=True):
                        if 'chapter' in a['href']:
                            is_locked = bool(a.find(lambda t: t.name in ['svg', 'i'] and ('lock' in str(t).lower() or 'premium' in str(t).lower())))
                            m = re.search(r'chapter[s]?[-/](\d+(?:\.\d+)?)', a['href'], re.I)
                            if m and is_locked:
                                locked_nums.add(float(m.group(1)))

            return {n: {"url": u, "locked": n in locked_nums} for n, u in all_chs.items()}
        except Exception:
            chs = await self.get_all_chapters(series_url)
            return {n: {"url": u, "locked": False} for n, u in chs.items()}

    async def _try_api(self, slug: str, series_url: str) -> dict:
        """يجرب عدة API endpoints شائعة في مواقع Next.js للمانجا"""
        parsed = urlparse(series_url)
        base   = f"{parsed.scheme}://{parsed.netloc}"
        chs    = {}

        # أنماط API شائعة
        endpoints = [
            f"{base}/api/chapters?series={slug}&page=1&limit=9999",
            f"{base}/api/series/{slug}/chapters",
            f"{base}/api/comic/{slug}/chapters",
            f"{base}/api/manga/{slug}/chapters?limit=9999",
            f"{base}/api/v1/comics/{slug}/chapters",
            f"{base}/api/chapters?series_slug={slug}&page=1&limit=9999",
        ]

        for ep in endpoints:
            try:
                data = self.fetch_json(ep)
                if not data:
                    continue

                # التعامل مع Vortex API الخاص
                if isinstance(data, dict) and ('chapters' in data or 'data' in data):
                    items = data.get('chapters', data.get('data', []))
                    if isinstance(items, dict): items = items.get('data', [])
                    for item in items:
                        num = item.get('number') or item.get('chapterNumber')
                        sl = item.get('slug')
                        if num is not None and sl:
                            chs[float(num)] = f"{series_url.rstrip('/')}/{sl}"
                    if chs: return chs

                text = json.dumps(data)
                found = self._chapters_from_json(text, base, series_url)
                if found:
                    chs.update(found)
                    for page_n in range(2, 20):
                        ep2  = re.sub(r'page=\d+', f'page={page_n}', ep)
                        if ep2 == ep:
                            ep2 = ep + f"&page={page_n}" if '?' in ep else ep + f"?page={page_n}"
                        d2 = self.fetch_json(ep2)
                        if not d2: break
                        new = self._chapters_from_json(json.dumps(d2), base, series_url)
                        if not new: break
                        before = len(chs)
                        chs.update(new)
                        if len(chs) == before: break
                    break
            except Exception:
                continue

        if not chs:
            try:
                html = self.fetch_html(series_url)
                if html:
                    m = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)
                    if m:
                        build_id = m.group(1)
                        next_url = f"{base}/_next/data/{build_id}/series/{slug}.json"
                        data     = self.fetch_json(next_url)
                        if data:
                            chs.update(self._chapters_from_json(json.dumps(data), base, series_url))
            except Exception:
                pass

        return chs

    def _chapters_from_json(self, text: str, base: str, series_url: str) -> dict:
        chs = {}
        # أنماط شائعة للروابط في JSON
        for m in re.finditer(
            r'"(?:href|url|link|slug|chapterSlug)"\s*:\s*"([^"]*(?:chapter|ch)[^"]*)"',
            text, re.IGNORECASE
        ):
            href = m.group(1).replace('\\u002F', '/').replace('\\', '')
            if not href.startswith('http'):
                href = urljoin(base, href)
            nm = re.search(r'(?:chapter[s]?|ch)[/-](\d+(?:\.\d+)?)', href, re.I)
            if nm:
                try:
                    chs[float(nm.group(1))] = href
                except Exception:
                    pass

        # أنماط rقم الفصل المباشر
        for m in re.finditer(
            r'"(?:chapter_number|chapterNumber|number|num)"\s*:\s*(\d+(?:\.\d+)?)',
            text
        ):
            num = float(m.group(1))
            if num not in chs:
                # بناء رابط تخميني
                slug_m = re.search(r'"(?:slug|chapterSlug)"\s*:\s*"([^"]+)"', text[max(0, m.start()-200):m.end()+200])
                if slug_m:
                    href = f"{series_url.rstrip('/')}/{slug_m.group(1)}"
                    chs[num] = href
        return chs

    def _from_next(self, soup, series_url: str) -> dict:
        nd = soup.find('script', id='__NEXT_DATA__')
        if not nd:
            return {}
        try:
            text = json.dumps(json.loads(nd.string))
            parsed = urlparse(series_url)
            base   = f"{parsed.scheme}://{parsed.netloc}"
            return self._chapters_from_json(text, base, series_url)
        except Exception:
            return {}

    def _from_html(self, soup, series_url: str) -> dict:
        chs    = {}
        parsed = urlparse(series_url)
        base   = f"{parsed.scheme}://{parsed.netloc}"
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not href.startswith('http'):
                href = urljoin(base, href)
            if 'vortexscans' not in href:
                continue
            m = re.search(r'(?:chapter[s]?|ch)[/-](\d+(?:\.\d+)?)', href, re.I)
            if m:
                try:
                    chs[float(m.group(1))] = href
                except Exception:
                    pass
        return chs

    def _extract_from_html_str(self, html: str, base_url: str) -> dict:
        return self._from_html(BeautifulSoup(html, 'html.parser'), base_url)

    def get_latest_chapter(self, url: str):
        import asyncio
        loop   = asyncio.new_event_loop()
        result = loop.run_until_complete(self.get_all_chapters(url))
        loop.close()
        return max(result.keys()) if result else None
