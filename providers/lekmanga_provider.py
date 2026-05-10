"""
lekmanga_provider.py — مزود lekmanga.net المتخصص

يتحايل على Cloudflare باستخدام:
  1. admin-ajax.php (manga_get_chapters) للحصول على الفصول
  2. madara_load_more للبحث عن المانجا وآخر فصل
  3. curl_cffi chrome120 impersonation لجلب الصور

نمط روابط الفصول: {manga_url}{chapter_num}/
"""

from __future__ import annotations
import re
import asyncio
from typing import Optional
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from .base_provider import BaseProvider

SITE = "lekmanga.net"
AJAX_URL = "https://lekmanga.net/wp-admin/admin-ajax.php"
HOME_URL = "https://lekmanga.net/"


class LekMangaProvider(BaseProvider):
    """مزود lekmanga.net — يستخدم Madara AJAX لتجاوز Cloudflare."""

    def __init__(self):
        super().__init__()
        self._cf_session = None
        self._slug_id_cache: dict[str, str] = {}

    # ── إدارة الجلسة ────────────────────────────────────────────────────
    def _get_cf_session(self):
        """جلسة curl_cffi بـ chrome120 مع تسخين من الصفحة الرئيسية."""
        if self._cf_session is None:
            try:
                from curl_cffi import requests as cfreq
                self._cf_session = cfreq.Session(impersonate="chrome120")
                self._cf_session.get(HOME_URL, timeout=15)
            except Exception as e:
                print(f"[LekManga] session init error: {e}")
        return self._cf_session

    def _ajax_post(self, data: dict) -> Optional[str]:
        """POST إلى admin-ajax.php — يرجع HTML أو None."""
        try:
            session = self._get_cf_session()
            r = session.post(
                AJAX_URL,
                data=data,
                timeout=15,
                headers={
                    "Referer": HOME_URL,
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            if r.status_code == 200 and r.text.strip() not in ("", "0", "false"):
                return r.text
        except Exception as e:
            print(f"[LekManga] AJAX error: {e}")
        return None

    # ── البحث عن post_id ────────────────────────────────────────────────
    def _find_post_id_from_homepage(self, slug: str) -> Optional[str]:
        """استخراج post_id من الصفحة الرئيسية إذا ظهرت المانجا فيها."""
        try:
            session = self._get_cf_session()
            r = session.get(HOME_URL, timeout=15)
            if r.status_code != 200:
                return None
            # data-post-id="12345" ... /manga/slug/
            pattern = rf'data-post-id=["\'](\d+)[^>]*>.*?/manga/{re.escape(slug)}/'
            m = re.search(pattern, r.text, re.DOTALL)
            if m:
                return m.group(1)
            # بديل: بحث بالترتيب المعكوس (slug ثم أقرب post-id قبله)
            idx = r.text.find(f"/manga/{slug}/")
            if idx > 0:
                snippet = r.text[max(0, idx - 300): idx]
                m2 = re.search(r'data-post-id=["\'](\d+)', snippet)
                if m2:
                    return m2.group(1)
        except Exception as e:
            print(f"[LekManga] homepage post_id error: {e}")
        return None

    def _find_post_id_from_search(self, slug: str) -> Optional[str]:
        """البحث عن post_id عبر AJAX search."""
        title = slug.replace("-", " ")
        html = self._ajax_post({
            "action": "madara_load_more",
            "template": "madara-core/content/content-search",
            "vars[s]": title,
            "page": "0",
        })
        if not html:
            return None
        # ابحث عن data-post-id بجانب slug الصحيح
        idx = html.find(f"/manga/{slug}/")
        if idx > 0:
            snippet = html[max(0, idx - 400): idx]
            m = re.search(r'data-post-id=["\'](\d+)', snippet)
            if m:
                return m.group(1)
        return None

    def _get_post_id(self, series_url: str) -> Optional[str]:
        """يجلب post_id بكل الطرق الممكنة."""
        slug = series_url.rstrip("/").split("/")[-1]
        if slug in self._slug_id_cache:
            return self._slug_id_cache[slug]

        pid = (self._find_post_id_from_homepage(slug)
               or self._find_post_id_from_search(slug))

        if pid:
            self._slug_id_cache[slug] = pid
        return pid

    # ── جلب الفصول عبر AJAX ─────────────────────────────────────────────
    def _chapters_via_ajax(self, post_id: str, series_url: str) -> dict:
        """
        يستخدم manga_get_chapters AJAX لجلب كل الفصول.
        نمط الرابط: {manga_url}{num}/
        """
        chapters: dict[float, str] = {}
        manga_slug = series_url.rstrip("/").split("/")[-1]

        for page_num in range(1, 200):
            html = self._ajax_post({
                "action": "manga_get_chapters",
                "manga": post_id,
                "paged": str(page_num),
            })
            if not html:
                break

            soup = BeautifulSoup(html, "html.parser")
            before = len(chapters)
            found_any = False

            for a in soup.select("li.wp-manga-chapter a, a[href*='/manga/']"):
                href = a.get("href", "").strip()
                if not href or manga_slug not in href:
                    continue
                if not href.startswith("http"):
                    href = urljoin("https://lekmanga.net", href)
                # نمط الرابط: /manga/slug/24/
                m = re.search(r"/manga/[^/]+/(\d+(?:\.\d+)?)/?$", href)
                if m:
                    try:
                        num = float(m.group(1))
                        chapters[num] = href
                        found_any = True
                    except Exception:
                        pass

            if not found_any:
                break
            if len(chapters) == before:
                break
            # إذا صفحة 1 أرجعت كثيراً → يعني كل الفصول مرة واحدة
            if page_num == 1 and len(chapters) > 50:
                break

        return chapters

    # ── البناء التسلسلي للفصول ───────────────────────────────────────────
    def _latest_chapter_from_search(self, slug: str) -> tuple[float, str]:
        """
        يستخرج آخر فصل ورابط المانجا من نتيجة البحث AJAX.
        يرجع (latest_num, manga_url).
        """
        title = slug.replace("-", " ")
        html = self._ajax_post({
            "action": "madara_load_more",
            "template": "madara-core/content/content-search",
            "vars[s]": title,
            "page": "0",
        })
        if not html:
            return 0.0, ""

        soup = BeautifulSoup(html, "html.parser")
        # ابحث عن بلوك المانجا التي تطابق الـ slug
        for a in soup.select("a[href*='/manga/']"):
            href = a.get("href", "")
            if slug not in href:
                continue
            manga_url = href.rstrip("/") + "/"
            # آخر فصل في نفس البلوك
            block = a.find_parent("div", class_=re.compile(r"row|item|content"))
            if block:
                ch_link = block.select_one(".latest-chap a, .chapter a")
                if ch_link:
                    ch_href = ch_link.get("href", "")
                    m = re.search(r"/(\d+(?:\.\d+)?)/?$", ch_href)
                    if m:
                        return float(m.group(1)), manga_url
        return 0.0, ""

    def _build_sequential(self, manga_url: str, latest: float) -> dict:
        """يبني روابط الفصول تسلسلياً من 1 إلى latest."""
        base = manga_url.rstrip("/")
        chapters: dict[float, str] = {}
        n = int(latest)
        for i in range(1, n + 1):
            chapters[float(i)] = f"{base}/{i}/"
        if latest != float(n):
            chapters[latest] = f"{base}/{latest}/"
        return chapters

    # ── الواجهة الرئيسية ─────────────────────────────────────────────────
    def _sync_get_all_chapters(self, series_url: str) -> dict:
        slug = series_url.rstrip("/").split("/")[-1]

        # 1. حاول AJAX مع post_id
        post_id = self._get_post_id(series_url)
        if post_id:
            chapters = self._chapters_via_ajax(post_id, series_url)
            if chapters:
                print(f"[LekManga] ✅ AJAX: {len(chapters)} chapters (post_id={post_id})")
                return chapters

        # 2. ابحث عن آخر فصل وابنِ الروابط تسلسلياً
        latest, manga_url = self._latest_chapter_from_search(slug)
        if latest > 0:
            if not manga_url:
                manga_url = series_url
            chapters = self._build_sequential(manga_url, latest)
            print(f"[LekManga] ✅ Sequential: {len(chapters)} chapters (latest={latest})")
            return chapters

        print(f"[LekManga] ⚠️ No chapters found for {series_url}")
        return {}

    async def get_all_chapters(self, series_url: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_get_all_chapters, series_url)

    def get_latest_chapter(self, url: str) -> Optional[float]:
        chs = self._sync_get_all_chapters(url)
        return max(chs.keys()) if chs else None

    async def get_images(self, url: str) -> list:
        """جلب صور الفصل عبر جلسة CF."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_get_images, url)

    def _sync_get_images(self, url: str) -> list:
        try:
            session = self._get_cf_session()
            r = session.get(
                url, timeout=20,
                headers={"Referer": HOME_URL}
            )
            if r.status_code == 200 and len(r.text) > 1000:
                soup = BeautifulSoup(r.text, "html.parser")
                images = []
                for sel in [
                    "#readerarea img",
                    ".reading-content img",
                    ".page-break img",
                    "div.wp-manga-chapter-img img",
                    "img[data-src]",
                ]:
                    for img in soup.select(sel):
                        src = (
                            img.get("data-src") or
                            img.get("data-lazy-src") or
                            img.get("src") or ""
                        ).strip()
                        if src.startswith("http") and src not in images:
                            if not any(x in src.lower() for x in ["logo", "banner", "icon", "avatar"]):
                                images.append(src)
                    if images:
                        return images
            elif r.status_code == 403:
                print(f"[LekManga] Chapter page still blocked: {url}")
        except Exception as e:
            print(f"[LekManga] get_images error: {e}")
        return []
