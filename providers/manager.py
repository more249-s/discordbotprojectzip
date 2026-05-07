import asyncio
from .generic_provider import GenericProvider
from .madara_provider import MadaraProvider
from .asura_provider import AsuraProvider
from .vortex_provider import VortexProvider
from .qimanhwa_provider import QimanhwaProvider
from .mangapill_provider import MangaPillProvider
from .manganato_provider import ManganatoProvider
from .webtoons_provider import WebtoonsProvider
from .weebcentral_provider import WeebCentralProvider
from .naver_provider import NaverProvider
from .mangadex_provider import MangaDexProvider
from .tcbscans_provider import TCBScansProvider
from .gemini_provider import GeminiProvider
from gemini_client import GeminiClient
from typing import List, Optional


class ProviderManager:
    def __init__(self):
        self.generic = GenericProvider()
        self.madara = MadaraProvider(scraper=self.generic.scraper)
        self.asura = AsuraProvider()
        self.vortex = VortexProvider()
        self.qimanhwa = QimanhwaProvider()
        self.mangapill = MangaPillProvider()
        self.manganato = ManganatoProvider()
        self.webtoons = WebtoonsProvider()
        self.weebcentral = WeebCentralProvider()
        self.naver = NaverProvider()
        self.mangadex = MangaDexProvider()
        self.tcbscans = TCBScansProvider()

        self.gemini_client = GeminiClient()
        self.gemini_fallback = GeminiProvider(self.gemini_client, scraper=self.generic.scraper)

        # مواقع Manganato
        self.manganato_sites = [
            "manganato", "mangakakalot", "manganelo", "chapmanganato",
        ]

        # مواقع تعتمد على Madara WordPress أو بنية مشابهة
        self.madara_sites = [
            # مواقع كورية / ترجمة إنجليزية شهيرة
            "toonily", "manhuaplus", "manhuafast", "webtoon.xyz",
            "mangaonlineteam", "mangapro",
            "utoon.net", "utoon.co",
            # Flame / Reaper / Luminous
            "flamescans.org", "flamecomics.xyz", "flamecomics.me",
            "reaperscans.com", "reapercomics.com",
            "luminousscans.net", "luminousscans.com",
            # مواقع أخرى شهيرة
            "isekaiscan.com", "isekaiscan.to",
            "azuremanga.com", "aquamanga.com",
            "247manga.com", "mangabaz.net",
            "zinmanga.com", "mangatx.com",
            "kunmanga.com", "topmanhua.com",
            "manhuaus.com", "1stkissmanga.io",
            "s2manga.com", "infernalvoidscans.com",
            "manhwaclan.com", "manhwatop.com",
            "toongod.org", "mangaclash.com",
            "nightscans.net", "disasterscans.com",
            "biblioscan.me", "rawkuma.com",
            "manga68.com", "manhua88.com",
            "manhuazone.net", "manhuafast.com",
            "chapscans.com", "drake-scans.com",
            "void-scans.com", "asura.nacm.xyz",
        ]

    def get_provider(self, url: str):
        url_lower = url.lower()

        if "mangadex.org" in url_lower:
            return self.mangadex

        if any(x in url_lower for x in ["asurascans", "asura.gg", "asuracomics", "asuratoon", "asura.nacm.xyz"]):
            return self.asura

        if "vortexscans" in url_lower:
            return self.vortex

        if any(x in url_lower for x in ["qimanhwa", "qimanhua", "qi manhwa"]):
            return self.qimanhwa

        if "mangapill" in url_lower:
            return self.mangapill

        if any(s in url_lower for s in self.manganato_sites):
            return self.manganato

        if "webtoons.com" in url_lower:
            return self.webtoons

        if "comic.naver.com" in url_lower:
            return self.naver

        if "weebcentral.com" in url_lower:
            return self.weebcentral

        if any(x in url_lower for x in ["tcbscans", "tcb-scans"]):
            return self.tcbscans

        # Madara-based sites
        if any(s in url_lower for s in self.madara_sites):
            return self.madara

        return self.generic

    def get_provider_name(self, url: str) -> str:
        p = self.get_provider(url)
        return type(p).__name__.replace("Provider", "")

    async def get_latest_chapter(self, url: str) -> Optional[float]:
        provider = self.get_provider(url)
        try:
            if asyncio.iscoroutinefunction(provider.get_latest_chapter):
                chapter = await provider.get_latest_chapter(url)
            else:
                loop = asyncio.get_event_loop()
                chapter = await loop.run_in_executor(None, provider.get_latest_chapter, url)
            if chapter is not None:
                return chapter
        except Exception as e:
            print(f"[ProviderManager] get_latest_chapter error: {e}")

        if provider is not self.generic:
            try:
                loop = asyncio.get_event_loop()
                chapter = await loop.run_in_executor(None, self.generic.get_latest_chapter, url)
                if chapter is not None:
                    return chapter
            except Exception:
                pass

        print(f"⚠️ كل المزودات فشلت، جاري تجربة Gemini...")
        try:
            return await self.gemini_fallback.get_latest_chapter_async(url)
        except Exception:
            return None

    async def get_images(self, url: str) -> List[str]:
        provider = self.get_provider(url)
        images = []
        try:
            if asyncio.iscoroutinefunction(provider.get_images):
                images = await provider.get_images(url)
            else:
                loop = asyncio.get_event_loop()
                images = await loop.run_in_executor(None, provider.get_images, url)
        except Exception as e:
            print(f"[ProviderManager] get_images error: {e}")

        if not images and provider is not self.generic:
            print(f"⚠️ فشل {type(provider).__name__}، جاري تجربة GenericProvider...")
            try:
                loop = asyncio.get_event_loop()
                images = await loop.run_in_executor(None, self.generic.get_images, url)
            except Exception:
                pass

        if not images:
            print(f"⚠️ فشل جلب الصور، جاري استخدام Gemini...")
            try:
                images = await self.gemini_fallback.get_images_async(url)
            except Exception:
                pass

        return images or []

    async def get_all_chapters(self, url: str) -> dict:
        provider = self.get_provider(url)
        chapters = {}
        try:
            if asyncio.iscoroutinefunction(provider.get_all_chapters):
                chapters = await provider.get_all_chapters(url)
            else:
                loop = asyncio.get_event_loop()
                chapters = await loop.run_in_executor(None, provider.get_all_chapters, url)
        except Exception as e:
            print(f"[ProviderManager] get_all_chapters error: {e}")

        if not chapters and provider is not self.generic:
            print(f"⚠️ فشل {type(provider).__name__}، جاري تجربة GenericProvider...")
            try:
                loop = asyncio.get_event_loop()
                chapters = await loop.run_in_executor(None, self.generic.get_all_chapters, url)
            except Exception:
                pass

        if not chapters:
            print(f"⚠️ فشل استخراج الفصول، جاري استخدام Gemini...")
            try:
                chapters = await self.gemini_fallback.get_all_chapters_async(url)
            except Exception:
                pass

        return chapters or {}
