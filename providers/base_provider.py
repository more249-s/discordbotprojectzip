import cloudscraper
from bs4 import BeautifulSoup
import re
from typing import List, Optional, Callable

try:
    from curl_cffi import requests as curl_requests
    CURL_AVAILABLE = True
except ImportError:
    CURL_AVAILABLE = False

CHROME_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
    'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Upgrade-Insecure-Requests': '1',
}

AJAX_HEADERS = {
    **CHROME_HEADERS,
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'X-Requested-With': 'XMLHttpRequest',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Dest': 'empty',
}


def create_scraper():
    return cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
        delay=3,
    )


def fetch_with_curl(url: str, headers: dict = None, timeout: int = 25,
                    method: str = "GET", data=None) -> Optional[str]:
    if not CURL_AVAILABLE:
        return None
    h = {**CHROME_HEADERS, **(headers or {})}
    for target in ["chrome131", "chrome124", "chrome120", "safari180"]:
        try:
            if method == "POST":
                resp = curl_requests.post(url, headers=h, data=data,
                                          timeout=timeout, impersonate=target)
            else:
                resp = curl_requests.get(url, headers=h, timeout=timeout,
                                         impersonate=target, allow_redirects=True)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            if "not supported" not in str(e).lower():
                continue
    return None


class BaseProvider:
    def __init__(self, scraper=None):
        self.scraper = scraper or create_scraper()
        self.headers = CHROME_HEADERS.copy()

    def fetch_html(self, url: str, extra_headers: dict = None, timeout: int = 25) -> Optional[str]:
        h = {**self.headers, **(extra_headers or {})}
        html = fetch_with_curl(url, h, timeout)
        if html and len(html) > 500:
            return html
        try:
            resp = self.scraper.get(url, headers=h, timeout=timeout)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            print(f"[cloudscraper] {url}: {e}")
        return None

    def fetch_json(self, url: str, method: str = "GET",
                   data=None, json_data=None, timeout: int = 20) -> Optional[dict]:
        """جلب JSON من API endpoint"""
        h = {**AJAX_HEADERS}
        try:
            if method == "POST":
                resp = self.scraper.post(url, data=data, json=json_data,
                                         headers=h, timeout=timeout)
            else:
                resp = self.scraper.get(url, headers=h, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        # fallback curl
        try:
            raw = fetch_with_curl(url, h, timeout, method=method, data=data)
            if raw:
                import json
                return json.loads(raw)
        except Exception:
            pass
        return None

    # ── Pagination helper ─────────────────────────────────────────────────
    def _paginate_chapters(
        self,
        base_url: str,
        extract_fn: Callable[[str, str], dict],
        max_pages: int = 40,
    ) -> dict:
        """
        يجرب أنماط Pagination متعددة ويجمع كل الفصول:
          • ?page=N
          • /page/N/
          • ?p=N
        يتوقف عندما لا تجد فصولاً جديدة في صفحة ما.
        """
        all_chapters: dict = {}

        patterns = [
            lambda u, n: f"{u.rstrip('/')}?page={n}",
            lambda u, n: f"{u.rstrip('/')}/page/{n}/",
            lambda u, n: f"{u.rstrip('/')}?p={n}",
        ]

        for pattern in patterns:
            found_any_new = False
            for page_num in range(2, max_pages + 1):
                try:
                    page_url = pattern(base_url, page_num)
                    html     = self.fetch_html(page_url)
                    if not html or len(html) < 500:
                        break
                    new_chs = extract_fn(html, base_url)
                    if not new_chs:
                        break
                    before = len(all_chapters)
                    all_chapters.update(new_chs)
                    if len(all_chapters) == before:
                        break          # نفس الفصول = آخر صفحة
                    found_any_new = True
                except Exception:
                    break
            if found_any_new:
                break   # النمط الأول الذي نجح يكفي

        return all_chapters

    def _extract_chapter_links(self, html: str, base_url: str) -> dict:
        """استخراج روابط الفصول من HTML خام — مساعد مشترك"""
        from urllib.parse import urljoin, urlparse
        soup    = BeautifulSoup(html, 'html.parser')
        parsed  = urlparse(base_url)
        domain  = f"{parsed.scheme}://{parsed.netloc}"
        chs     = {}
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not href.startswith('http'):
                href = urljoin(domain, href)
            m = re.search(r'(?:chapter[s]?|ch)[/-](\d+(?:\.\d+)?)', href, re.I)
            if m and domain.split('//')[1].split('/')[0] in href:
                try:
                    num = float(m.group(1))
                    if num not in chs:
                        chs[num] = href
                except Exception:
                    pass
        return chs

    def get_latest_chapter(self, url: str) -> Optional[float]:
        raise NotImplementedError

    def get_images(self, url: str) -> List[str]:
        raise NotImplementedError

    def get_all_chapters(self, url: str) -> dict:
        raise NotImplementedError

    def extract_chapter_number(self, text: str) -> Optional[float]:
        m = re.search(r'(?i)(?:الفصل|فصل|chapter|ch|ep|v)\s*[:\-]?\s*(\d+(?:\.\d+)?)', text)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass
        return None
