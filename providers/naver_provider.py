import cloudscraper
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
import re
from urllib.parse import urljoin, urlparse

class NaverProvider(BaseProvider):
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.headers = {
            'Referer': 'https://comic.naver.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    async def get_images(self, url):
        try:
            # Naver needs Referer for the main page too sometimes
            response = self.scraper.get(url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # الصور موجودة في الـ wt_viewer
            container = soup.select_one('.wt_viewer')
            if not container:
                # محاولة أخرى للبحث في الـ scripts إذا كانت الصفحة تعتمد على الـ dynamic loading
                # لكن عادة Naver تضعها في الـ HTML مباشرة
                return []
                
            img_tags = container.find_all('img')
            images = []
            for img in img_tags:
                src = img.get('src')
                if src:
                    images.append(src.strip())
            return images
        except Exception as e:
            print(f"Naver images error: {e}")
            return []

    async def get_all_chapters(self, series_url):
        try:
            # Naver series URL example: https://comic.naver.com/webtoon/list?titleId=841762
            response = self.scraper.get(series_url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            chapters = {}
            
            # قائمة الفصول عادة في جدول أو قائمة
            items = soup.select('.item a') or soup.select('ul.lst li a')
            for a in items:
                href = a.get('href')
                if not href: continue
                
                # استخراج رقم الفصل من الرابط (no=XX)
                no_match = re.search(r'no=(\d+)', href)
                if no_match:
                    num = float(no_match.group(1))
                    chapters[num] = urljoin(series_url, href)
            return chapters
        except Exception as e:
            print(f"Naver chapters error: {e}")
            return {}
