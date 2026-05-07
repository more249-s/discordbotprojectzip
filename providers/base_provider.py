import cloudscraper
from bs4 import BeautifulSoup
import re
from typing import List, Optional

try:
    from curl_cffi import requests as curl_requests
    CURL_AVAILABLE = True
except ImportError:
    CURL_AVAILABLE = False

CHROME_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}


def create_scraper():
    """إنشاء scraper بإعدادات مثلى لتخطي Cloudflare"""
    return cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True,
            'mobile': False,
        },
        delay=5,
    )


def fetch_with_curl(url: str, headers: dict = None, timeout: int = 25) -> Optional[str]:
    """أقوى طريقة لتخطي Cloudflare باستخدام curl_cffi مع TLS fingerprinting حقيقي"""
    if not CURL_AVAILABLE:
        return None

    h = {**CHROME_HEADERS, **(headers or {})}
    targets = ["chrome131", "chrome124", "chrome120", "safari180", "firefox133"]

    for target in targets:
        try:
            resp = curl_requests.get(
                url,
                headers=h,
                timeout=timeout,
                impersonate=target,
                allow_redirects=True,
            )
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            if "not supported" not in str(e).lower():
                print(f"[curl_cffi:{target}] error for {url}: {e}")
            continue

    return None


class BaseProvider:
    def __init__(self, scraper=None):
        self.scraper = scraper or create_scraper()
        self.headers = CHROME_HEADERS.copy()

    def fetch_html(self, url: str, extra_headers: dict = None, timeout: int = 25) -> Optional[str]:
        """جلب HTML مع تجربة curl_cffi أولاً ثم cloudscraper كبديل"""
        h = {**self.headers, **(extra_headers or {})}

        # المحاولة 1: curl_cffi (أقوى bypass)
        html = fetch_with_curl(url, h, timeout)
        if html and len(html) > 500:
            return html

        # المحاولة 2: cloudscraper
        try:
            resp = self.scraper.get(url, headers=h, timeout=timeout)
            if resp.status_code == 200:
                return resp.text
            print(f"[cloudscraper] HTTP {resp.status_code} for {url}")
        except Exception as e:
            print(f"[cloudscraper] error for {url}: {e}")

        return None

    def get_latest_chapter(self, url: str) -> Optional[float]:
        raise NotImplementedError

    def get_images(self, url: str) -> List[str]:
        raise NotImplementedError

    def get_all_chapters(self, url: str) -> dict:
        raise NotImplementedError

    def extract_chapter_number(self, text: str) -> Optional[float]:
        match = re.search(r'(?i)(?:الفصل|فصل|chapter|ch|ep|v)\s*[:\-]?\s*(\d+(?:\.\d+)?)', text)
        if match:
            try:
                return float(match.group(1))
            except Exception:
                pass
        return None
