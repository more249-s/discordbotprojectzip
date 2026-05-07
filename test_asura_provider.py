    import cloudscraper
    from bs4 import BeautifulSoup
    from .base_provider import BaseProvider
    import re
    import html

    class AsuraProvider(BaseProvider):
        def __init__(self):
            self.scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'mobile': False
                }
            )
            self.headers = {
                'Referer': 'https://asuracomics.com/',
                'sec-ch-ua': '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
            }

        async def get_images(self, url):
            try:
                # التأكد من استخدام النطاق الصحيح
                if "asurascans.com" in url:
                    url = url.replace("asurascans.com", "asuracomics.com")

                response = self.scraper.get(url, headers=self.headers, timeout=15)
                if response.status_code != 200:
                    return []

                text = response.text
                soup = BeautifulSoup(text, 'html.parser')
                images = []

                # 1. محاولة استخراج الصور من الوسوم التقليدية
                reader_area = soup.select_one('#readerarea') or soup.select_one('.rdminimal')
                if reader_area:
                    img_tags = reader_area.find_all('img')
                    for img in img_tags:
                        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                        if src and src.startswith('http') and not any(x in src for x in ['logo', 'discord']):
                            images.append(src.strip())

                # 2. استخراج الصور في حال كان النظام الجديد (JSON/JS)
                if not images:
                    patterns = [
                        r'https?://[^"\'\s<>]+?\.(?:webp|jpg|jpeg|png)',
                        r'\"url\":\"(https?://[^\"]+)\"'
                    ]
                    for pattern in patterns:
                        for match in re.findall(pattern, text, flags=re.IGNORECASE):
                            if isinstance(match, tuple): match = match[0]
                            cleaned = match.replace('\\', '').strip()
                            if 'chapter' in cleaned.lower() and cleaned not in images:
                                images.append(cleaned)
                        if images:
                            break

                return images
            except Exception as e:
                print(f"Asura images error: {e}")
                return []

        async def get_all_chapters(self, series_url):
            try:
                response = self.scraper.get(series_url, headers=self.headers, timeout=15)
                soup = BeautifulSoup(response.text, 'html.parser')

                chapters = {}
                chapter_elements = soup.select('.eplister li a') or soup.select('.cl-item a')

                for a in chapter_elements:
                    href = a.get('href')
                    text = a.text.lower()
                    match = re.search(r'chapter\s*([\d.]+)', text) or re.search(r'-([\d.]+)/?$', href)
                    if match:
                        ch_num = float(match.group(1))
                        chapters[ch_num] = href

                return chapters
            except Exception as e:
                print(f"Asura chapters error: {e}")
                return {}