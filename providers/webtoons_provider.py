import cloudscraper
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
import re
from urllib.parse import urljoin, urlparse

class WebtoonsProvider(BaseProvider):
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.headers = {
            'Referer': 'https://www.webtoons.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    async def get_images(self, url):
        try:
            # موقع Webtoons يحتاج Referer دقيق جداً لكل فصل
            headers = self.headers.copy()
            headers['Referer'] = url
            
            response = self.scraper.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # الصور موجودة في الـ viewer_img_area
            container = soup.select_one('#_img_viewer_area') or soup.select_one('.viewer_img')
            if not container:
                return []
                
            img_tags = container.find_all('img')
            images = []
            for img in img_tags:
                # ميزة تعلمناها من المستودع: data-url هي الرابط الأصلي
                src = img.get('data-url') or img.get('src')
                if src:
                    # تحسين الجودة: إزالة تقليل الحجم إذا وجد
                    src = src.split('?')[0] 
                    images.append(src.strip())
            return images
        except Exception as e:
            print(f"Webtoons images error: {e}")
            return []

    async def get_all_chapters(self, series_url):
        try:
            # استخراج title_no من الرابط
            # مثال: https://www.webtoons.com/en/fantasy/tower-of-god/list?title_no=95
            parsed_url = urlparse(series_url)
            from urllib.parse import parse_qs
            qs = parse_qs(parsed_url.query)
            title_no = qs.get('title_no', [None])[0]
            
            if not title_no:
                match = re.search(r'title_no=(\d+)', series_url)
                if match: title_no = match.group(1)

            if title_no:
                # استخدام الـ Mobile API المكتشف!
                # نحدد النوع (webtoon أو canvas)
                webtoon_type = "canvas" if "canvas" in series_url else "webtoon"
                api_url = f"https://m.webtoons.com/api/v1/{webtoon_type}/{title_no}"
                
                try:
                    # نحتاج UA خاص بالجوال للـ API
                    mobile_headers = self.headers.copy()
                    mobile_headers['User-Agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1'
                    resp = self.scraper.get(api_url, headers=mobile_headers, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        episodes = data.get('result', {}).get('episodeList', [])
                        chapters = {}
                        for ep in episodes:
                            num = ep.get('episodeNo')
                            # بناء رابط المشاهدة (Viewer URL)
                            # الرابط يكون عادة: /en/fantasy/tower-of-god/viewer?title_no=95&episode_no=1
                            viewer_path = ep.get('viewerLink')
                            if viewer_path:
                                ch_url = urljoin("https://www.webtoons.com", viewer_path)
                                chapters[float(num)] = ch_url
                        if chapters: return chapters
                except: pass

            # Fallback للـ Scraping التقليدي
            response = self.scraper.get(series_url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            chapters = {}
            # سلكتورز قائمة الفصول
            items = soup.select('#_listUl li')
            for li in items:
                a = li.find('a')
                if not a: continue
                href = a.get('href')
                # استخراج رقم الحلقة من الـ ID أو النص
                ep_match = re.search(r'episode_no=(\d+)', href)
                if ep_match:
                    num = float(ep_match.group(1))
                    chapters[num] = urljoin(series_url, href)
            return chapters
        except Exception as e:
            print(f"Webtoons chapters error: {e}")
            return {}
