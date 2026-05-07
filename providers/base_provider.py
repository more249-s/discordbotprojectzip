import cloudscraper
from bs4 import BeautifulSoup
import re
from typing import List, Optional

class BaseProvider:
    def __init__(self, scraper=None):
        self.scraper = scraper or cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
            'Referer': 'https://www.google.com/',
        }

    def fetch_html(self, url: str) -> Optional[str]:
        try:
            response = self.scraper.get(url, headers=self.headers, timeout=25)
            if response.status_code == 200:
                return response.text
        except Exception as e:
            print(f"Error fetching {url}: {e}")
        return None

    def get_latest_chapter(self, url: str) -> Optional[float]:
        """يجب توريث هذه الدالة في كل مزود"""
        raise NotImplementedError

    def get_images(self, url: str) -> List[str]:
        """يجب توريث هذه الدالة في كل مزود"""
        raise NotImplementedError

    def get_all_chapters(self, url: str) -> dict:
        """
        ترجع قاموس يحتوي على رقم الفصل كرقم (float) والرابط (str)
        مثال: {1.0: "http...", 2.0: "http..."}
        """
        raise NotImplementedError

    def extract_chapter_number(self, text: str) -> Optional[float]:
        """دالة مساعدة لاستخراج رقم الفصل من النص"""
        match = re.search(r'(?i)(?:الفصل|فصل|chapter|ch|ep|v)\s*[:\-]?\s*(\d+(?:\.\d+)?)', text)
        if match:
            try:
                return float(match.group(1))
            except:
                pass
        return None
