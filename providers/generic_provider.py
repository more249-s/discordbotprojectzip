from .base_provider import BaseProvider
from bs4 import BeautifulSoup
import re
from typing import List, Optional

class GenericProvider(BaseProvider):
    def _fetch_html_with_diagnostics(self, url: str) -> Optional[str]:
        html = self.fetch_html(url)
        if html:
            return html
        try:
            resp = self.scraper.get(url, timeout=20)
            if resp.status_code == 403 and "just a moment" in resp.text.lower():
                print(f"Cloudflare challenge blocked this URL: {url}")
            elif resp.status_code >= 400:
                print(f"HTTP {resp.status_code} while fetching: {url}")
        except Exception:
            pass
        return None

    def get_latest_chapter(self, url: str) -> Optional[float]:
        chapters = self.get_all_chapters(url)
        if chapters:
            return max(chapters.keys())
        return None

    def get_all_chapters(self, url: str) -> dict:
        html = self._fetch_html_with_diagnostics(url)
        if not html: return {}
        
        soup = BeautifulSoup(html, 'html.parser')
        chapters = {}
        
        # البحث في كل الروابط للحصول على رقم الفصل والرابط الخاص به
        for a in soup.find_all('a'):
            href = a.get('href')
            if not href: continue
            
            text = a.get_text(strip=True)
            val = self.extract_chapter_number(text)
            if val is not None:
                # نحتفظ بالرابط، ولكننا نحتاج التأكد من أنه رابط كامل
                if href.startswith('/'):
                    from urllib.parse import urlparse
                    parsed_url = urlparse(url)
                    href = f"{parsed_url.scheme}://{parsed_url.netloc}{href}"
                
                chapters[val] = href
        
        return chapters

    def get_images(self, url: str) -> List[str]:
        html = self._fetch_html_with_diagnostics(url)
        if not html: return []
        
        soup = BeautifulSoup(html, 'html.parser')
        img_urls = []
        
        # البحث عن منطقة القراءة الشائعة
        reader_area = soup.find('div', id='readerarea') or \
                      soup.find('div', class_='rdminimal') or \
                      soup.find('div', class_='canvas-container')
        
        if reader_area:
            imgs = reader_area.find_all('img')
            for img in imgs:
                src = img.get('data-src') or img.get('src')
                if src and src.startswith('http'):
                    img_urls.append(src)
        else:
            # محاولة أخيرة: البحث عن أي صورة كبيرة
            for img in soup.find_all('img'):
                src = img.get('data-src') or img.get('src')
                if src and ('wp-content/uploads' in src or 'manga' in src):
                    img_urls.append(src)
        
        return list(dict.fromkeys(img_urls))
