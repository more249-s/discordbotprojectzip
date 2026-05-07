import asyncio
from .generic_provider import GenericProvider
from .madara_provider import MadaraProvider
from .asura_provider import AsuraProvider
from .mangapill_provider import MangaPillProvider
from .manganato_provider import ManganatoProvider
from .webtoons_provider import WebtoonsProvider
from .weebcentral_provider import WeebCentralProvider
from .naver_provider import NaverProvider
from .gemini_provider import GeminiProvider
from gemini_client import GeminiClient
from typing import List, Optional

class ProviderManager:
    def __init__(self):
        self.generic = GenericProvider()
        self.madara = MadaraProvider(scraper=self.generic.scraper)
        self.asura = AsuraProvider()
        self.mangapill = MangaPillProvider()
        self.manganato = ManganatoProvider()
        self.webtoons = WebtoonsProvider()
        self.weebcentral = WeebCentralProvider()
        self.naver = NaverProvider()
        
        # نستخدم عميل جيميناي كنظام احتياطي للمواقع الصعبة
        self.gemini_client = GeminiClient()
        self.gemini_fallback = GeminiProvider(self.gemini_client, scraper=self.generic.scraper)
        
        # قائمة المواقع التي نعرف يقيناً أنها تستخدم Madara
        self.madara_sites = [
            "asurascans", "vortexscans", "mangapro", "mangaonlineteam", "manhuaplus", "toonily", "manhuafast", "webtoon.xyz"
        ]
        self.manganato_sites = [
            "manganato", "mangakakalot", "manganelo", "chapmanganato"
        ]

    def get_provider(self, url: str):
        url_lower = url.lower()
        
        if "asura" in url_lower:
            return self.asura
        if "mangapill" in url_lower:
            return self.mangapill
        
        for site in self.manganato_sites:
            if site in url_lower:
                return self.manganato
        
        if "webtoons.com" in url_lower:
            return self.webtoons
            
        if "comic.naver.com" in url_lower:
            return self.naver
            
        if "weebcentral.com" in url_lower:
            return self.weebcentral
            
        for site in self.madara_sites:
            if site in url_lower:
                return self.madara
        
        return self.generic

    async def get_latest_chapter(self, url: str) -> Optional[float]:
        provider = self.get_provider(url)
        # Check if provider method is async
        if asyncio.iscoroutinefunction(provider.get_latest_chapter):
            chapter = await provider.get_latest_chapter(url)
        else:
            loop = asyncio.get_event_loop()
            chapter = await loop.run_in_executor(None, provider.get_latest_chapter, url)
        
        if chapter is None:
            print(f"⚠️ فشل المزود العادي، محاولة استخدام Gemini لموقع {url}")
            chapter = await self.gemini_fallback.get_latest_chapter_async(url)
        return chapter

    async def get_images(self, url: str) -> List[str]:
        provider = self.get_provider(url)
        if asyncio.iscoroutinefunction(provider.get_images):
            images = await provider.get_images(url)
        else:
            loop = asyncio.get_event_loop()
            images = await loop.run_in_executor(None, provider.get_images, url)
        
        if not images:
            print(f"⚠️ فشل جلب الصور بالطريقة العادية، جاري استخدام Gemini لـ {url}")
            images = await self.gemini_fallback.get_images_async(url)
        return images

    async def get_all_chapters(self, url: str) -> dict:
        provider = self.get_provider(url)
        if asyncio.iscoroutinefunction(provider.get_all_chapters):
            chapters = await provider.get_all_chapters(url)
        else:
            loop = asyncio.get_event_loop()
            chapters = await loop.run_in_executor(None, provider.get_all_chapters, url)
        
        if not chapters:
            print(f"⚠️ فشل استخراج الفصول بالطريقة العادية، جاري استخدام Gemini لـ {url}")
            chapters = await self.gemini_fallback.get_all_chapters_async(url)
        return chapters
