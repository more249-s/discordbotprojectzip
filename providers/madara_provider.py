import cloudscraper
from bs4 import BeautifulSoup
from .base_provider import BaseProvider
import re
from urllib.parse import urljoin

class MadaraProvider(BaseProvider):
    def __init__(self, scraper=None):
        self.scraper = scraper or cloudscraper.create_scraper()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    async def get_images(self, url):
        try:
            response = self.scraper.get(url, headers=self.headers, timeout=15)
            if response.status_code != 200:
                print(f"Madara error {response.status_code} for {url}")
                return []
                
            text = response.text
            soup = BeautifulSoup(text, 'html.parser')
            
            # 1. استخراج من المحددات التقليدية
            selectors = [
                "[data-reader-page-image]",
                "div.reading-content img",
                "div#chapter-images img",
                "div.page-break img",
                "div.wp-manga-chapter-img img",
                "img.wp-manga-chapter-img"
            ]
            
            images = []
            for selector in selectors:
                nodes = soup.select(selector)
                for img in nodes:
                    src = (img.get('data-src') or img.get('data-lazy-src') or 
                           img.get('data-cfsrc') or img.get('src'))
                    if src:
                        src = src.strip()
                        if src.startswith('//'): src = 'https:' + src
                        elif not src.startswith('http'): src = urljoin(url, src)
                        if src not in images and not any(x in src.lower() for x in ['logo', 'banner', 'ads']):
                            images.append(src)
            
            # 2. إذا فشل المحددات، نستخدم Regex للبحث عن روابط الصور في JSON/Script
            if not images:
                # هذا النطاق يغطي معظم مواقع التخزين للمانجا
                patterns = [
                    r'https?://[^"\'\s<>]+?\.(?:webp|jpg|jpeg|png|gif)',
                    r'\"(https?://storage\.vortexscans\.org/[^"]+)\"',
                    r'\"(https?://cdn\.[^"]+/[^"]+\.(?:webp|jpg|jpeg|png))\"'
                ]
                for pattern in patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    for match in matches:
                        if isinstance(match, tuple): match = match[0]
                        cleaned = match.replace('\\', '')
                        if cleaned not in images and not any(x in cleaned.lower() for x in ['logo', 'avatar', 'icon', 'theme']):
                            images.append(cleaned)

            return images
        except Exception as e:
            print(f"Madara images error: {e}")
            return []

    async def get_all_chapters(self, series_url):
        try:
            response = self.scraper.get(series_url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            chapters = self._extract_chapters_from_html(soup, series_url)
            
            # إذا لم نجد فصولاً، قد يكون الموقع يستخدم AJAX (ميزة جديدة!)
            if not chapters:
                chapters = await self._load_ajax_chapters(soup, series_url)
                
            return chapters
        except Exception as e:
            print(f"Madara chapters error: {e}")
            return {}

    def _extract_chapters_from_html(self, soup, series_url):
        chapters = {}
        # سلكتورز شاملة لعائلة Madara
        selectors = ["li.wp-manga-chapter a", "div#chapterlist li a", "ul.main.version-chap li a"]
        for selector in selectors:
            nodes = soup.select(selector)
            for a in nodes:
                href = a.get('href')
                if not href: continue
                href = urljoin(series_url, href)
                text = a.text.lower()
                # استخراج الرقم
                match = re.search(r'chapter\s*([\d.]+)', text) or re.search(r'-([\d.]+)/?$', href)
                if match:
                    try:
                        ch_num = float(match.group(1))
                        chapters[ch_num] = href
                    except: pass
            if chapters: break
        return chapters

    async def _load_ajax_chapters(self, soup, series_url):
        # محاكاة طلب AJAX الخاص بـ Madara
        try:
            # البحث عن الـ ID الخاص بالمانجا
            holder = soup.select_one("#manga-chapters-holder")
            post_id = holder.get("data-id") if holder else None
            if not post_id:
                # محاولة البحث عن ID في الكود المصدري
                match = re.search(r'manga_id\s*:\s*(\d+)', str(soup))
                if match: post_id = match.group(1)

            if post_id:
                base_url = "/".join(series_url.split("/")[:3])
                ajax_url = f"{base_url}/wp-admin/admin-ajax.php"
                data = {
                    "action": "manga_get_chapters",
                    "manga": post_id
                }
                # إرسال طلب الـ AJAX
                resp = self.scraper.post(ajax_url, data=data, headers=self.headers, timeout=10)
                if resp.status_code == 200:
                    ajax_soup = BeautifulSoup(resp.text, 'html.parser')
                    return self._extract_chapters_from_html(ajax_soup, series_url)
        except: pass
        return {}
