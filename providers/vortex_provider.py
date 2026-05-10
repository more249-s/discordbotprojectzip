"""
vortex_provider.py — مزود VortexScans المحسّن

يدعم:
  • HTML links (أحدث 20 فصل)
  • Chapter sitemaps (كل الفصول)
  • Retry مع exponential backoff
  • كشف الفصول المقفلة
"""

from __future__ import annotations
import re
import json
import time
import asyncio
from typing import Optional
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import cloudscraper
from bs4 import BeautifulSoup

from .base_provider import BaseProvider

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://vortexscans.org/",
}

_NUM_RE = re.compile(
    r"(?:chapter|chap|ch)[-_/]?(\d+(?:\.\d+)?)", re.I
)


class VortexProvider(BaseProvider):
    """مزود VortexScans — HTML + Sitemaps + Retry"""

    BASE = "https://vortexscans.org"

    def __init__(self):
        super().__init__()
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        self.scraper.headers.update(HEADERS)

    # ── Fetch مع Retry ─────────────────────────────────────────────────────
    def _fetch_with_retry(self, url: str, retries: int = 3, timeout: int = 20) -> str | None:
        for attempt in range(retries):
            try:
                r = self.scraper.get(url, headers=HEADERS, timeout=timeout)
                if r.status_code == 200 and len(r.text) > 300:
                    return r.text
                if r.status_code in (403, 404):
                    return None
                if r.status_code in (429, 503, 504):
                    wait = 2 ** attempt
                    print(f"[Vortex] {r.status_code} on {url}, waiting {wait}s...")
                    time.sleep(wait)
                    continue
            except Exception as e:
                print(f"[Vortex] fetch attempt {attempt+1}: {e}")
                if attempt < retries - 1:
                    time.sleep(2)
        return None

    # ── صور الفصل ─────────────────────────────────────────────────────────
    async def get_images(self, url: str) -> list[str]:
        loop = asyncio.get_event_loop()

        def _scrape():
            html = self._fetch_with_retry(url)
            if not html:
                return []
            soup   = BeautifulSoup(html, "html.parser")
            images = []

            # 1. img tags with upload/series
            for img in soup.find_all("img"):
                src = (img.get("src") or img.get("data-src") or "").strip()
                if "upload/series" in src and src not in images:
                    if "wsrv.nl" in src:
                        m = re.search(r"url=([^&]+)", src)
                        if m:
                            import urllib.parse
                            src = urllib.parse.unquote(m.group(1))
                    images.append(src)
            if images:
                return images

            # 2. regex direct
            for p in re.findall(
                r"https?://(?:storage\.)?vortexscans\.org/upload/series/[^\"'\s<>]+?"
                r"\.(?:webp|jpg|jpeg|png)",
                html, re.I,
            ):
                if p not in images:
                    images.append(p)
            return images

        return await loop.run_in_executor(None, _scrape)

    # ── كل الفصول ─────────────────────────────────────────────────────────
    async def get_all_chapters(self, series_url: str) -> dict[float, str]:
        rich = await self._get_chapters_rich(series_url)
        return {num: info["url"] for num, info in rich.items()}

    async def get_chapters_with_lock_info(self, series_url: str) -> dict[float, dict]:
        return await self._get_chapters_rich(series_url)

    async def _get_chapters_rich(self, series_url: str) -> dict[float, dict]:
        loop = asyncio.get_event_loop()
        slug = series_url.rstrip("/").split("/")[-1]

        def _fetch_all():
            all_chs: dict[float, dict] = {}

            # ── 1. HTML links (يجلب أحدث 20 فصل دائماً) ─────────────────
            html = self._fetch_with_retry(series_url, retries=3, timeout=25)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                chs  = self._from_html_links(soup, series_url)
                all_chs.update(chs)
                print(f"[Vortex] HTML links: {len(chs)} chapters")

                # استخرج غلاف السلسلة للعرض
                cover = soup.find("meta", property="og:image")
                if cover:
                    self._last_cover = cover.get("content", "")

            # ── 2. Sitemaps (يجلب كل الفصول) ─────────────────────────────
            sitemap_chs = self._fetch_sitemap_chapters(slug, series_url)
            if sitemap_chs:
                # أضف الفصول من السيتماب التي لم تُجلب من HTML
                new = {k: v for k, v in sitemap_chs.items() if k not in all_chs}
                all_chs.update(new)
                print(f"[Vortex] Sitemaps: +{len(new)} new chapters (total from sitemap: {len(sitemap_chs)})")

            return all_chs

        result = await loop.run_in_executor(None, _fetch_all)
        print(f"[Vortex] Total: {len(result)} chapters from {series_url}")
        return result

    def _fetch_sitemap_chapters(self, slug: str, series_url: str) -> dict[float, dict]:
        """جلب كل فصول السلسلة من سيتماب VortexScans."""
        all_chs: dict[float, dict] = {}

        try:
            # جلب فهرس السيتماب
            r = self.scraper.get(
                f"{self.BASE}/sitemap.xml", headers=HEADERS, timeout=15
            )
            if r.status_code != 200:
                return {}

            sitemap_urls = re.findall(
                r"<loc>(https://vortexscans\.org/chapter-sitemap-\d+\.xml)</loc>",
                r.text,
            )
            if not sitemap_urls:
                return {}

            print(f"[Vortex] Found {len(sitemap_urls)} chapter sitemaps, scanning...")

            def fetch_one(url: str) -> list[str]:
                try:
                    resp = self.scraper.get(url, headers=HEADERS, timeout=12)
                    if resp.status_code != 200:
                        return []
                    # فقط الفصول الخاصة بهذه السلسلة
                    slug_encoded = slug.replace("'", "%27").replace("'", "%27")
                    locs = re.findall(
                        r"<loc>(https://vortexscans\.org/series/[^<]+/chapter-[^<]+)</loc>",
                        resp.text,
                    )
                    # فلتر بالـ slug (مع مراعاة أن الـ ' قد يكون encoded أو raw)
                    matched = []
                    for loc in locs:
                        series_part = loc.split("/chapter-")[0].split("/series/")[-1]
                        # مقارنة slugs بعد إزالة الـ apostrophe والـ encode
                        s_clean = series_part.replace("%27", "'").replace("'", "")
                        t_clean = slug.replace("'", "").replace("'", "")
                        if s_clean.lower() == t_clean.lower():
                            matched.append(loc)
                    return matched
                except Exception:
                    return []

            # جلب كل السيتمابات بشكل متوازي
            with ThreadPoolExecutor(max_workers=6) as ex:
                futures = {ex.submit(fetch_one, u): u for u in sitemap_urls}
                for f in as_completed(futures):
                    found = f.result()
                    for url in found:
                        m = _NUM_RE.search(url)
                        if m:
                            try:
                                num = float(m.group(1))
                                if num > 0 and num not in all_chs:
                                    all_chs[num] = {
                                        "url": url,
                                        "locked": False,
                                        "reason": "sitemap",
                                    }
                            except Exception:
                                pass

        except Exception as e:
            print(f"[Vortex] sitemap error: {e}")

        return all_chs

    def _from_html_links(self, soup: BeautifulSoup, series_url: str) -> dict[float, dict]:
        chs = {}
        parsed = urlparse(series_url)
        base   = f"{parsed.scheme}://{parsed.netloc}"

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                href = urljoin(base, href)
            if "vortexscans" not in href:
                continue
            m = _NUM_RE.search(href)
            if m:
                try:
                    num = float(m.group(1))

                    # فحص القفل من العنصر الأب
                    locked = False
                    parent = a.parent
                    if parent:
                        parent_html = str(parent)
                        locked = bool(
                            parent.select_one("[class*='lock'], [class*='premium'], .fa-lock")
                            or re.search(r'\block\b|\bpremium\b|\bpaid\b', parent_html, re.I)
                        )
                    chs[num] = {"url": href, "locked": locked, "reason": "html-link"}
                except Exception:
                    pass
        return chs

    async def get_latest_chapter(self, series_url: str) -> Optional[float]:
        chs = await self.get_all_chapters(series_url)
        return max(chs.keys()) if chs else None
