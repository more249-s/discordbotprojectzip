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
from .comick_provider import ComickProvider
from .mangafire_provider import MangaFireProvider
from .bato_provider import BatoProvider
from .arabic_provider import ArabicProvider
from .mangaplus_provider import MangaPlusProvider
from gemini_client import GeminiClient
from typing import List, Optional


class ProviderManager:
    def __init__(self):
        self.generic     = GenericProvider()
        self.madara      = MadaraProvider(scraper=self.generic.scraper)
        self.asura       = AsuraProvider()
        self.vortex      = VortexProvider()
        self.qimanhwa    = QimanhwaProvider()
        self.mangapill   = MangaPillProvider()
        self.manganato   = ManganatoProvider()
        self.webtoons    = WebtoonsProvider()
        self.weebcentral = WeebCentralProvider()
        self.naver       = NaverProvider()
        self.mangadex    = MangaDexProvider()
        self.tcbscans    = TCBScansProvider()
        self.comick      = ComickProvider()
        self.mangafire   = MangaFireProvider()
        self.bato        = BatoProvider()
        self.arabic      = ArabicProvider(scraper=self.generic.scraper)
        self.mangaplus   = MangaPlusProvider()

        self.gemini_client   = GeminiClient()
        self.gemini_fallback = GeminiProvider(self.gemini_client, scraper=self.generic.scraper)

        # ── مواقع Manganato ───────────────────────────────────────────────────
        self.manganato_sites = [
            "manganato", "mangakakalot", "manganelo", "chapmanganato",
            "readmanganato", "mangakakalots",
        ]

        # ── مواقع Bato ────────────────────────────────────────────────────────
        self.bato_sites = [
            "bato.to", "batotoo.com", "dto.to", "bato.site",
        ]

        # ── مواقع Comick ──────────────────────────────────────────────────────
        self.comick_sites = [
            "comick.fun", "comick.io", "comick.cc", "comick.app",
        ]

        # ── مواقع MangaFire ───────────────────────────────────────────────────
        self.mangafire_sites = [
            "mangafire.to",
        ]

        # ── المواقع العربية ───────────────────────────────────────────────────
        self.arabic_sites = [
            "mangalek.com",
            "3asq.to", "3asq.net", "3asq.org",
            "manga-ar.com", "mangaarab.com", "manga-ar.net",
            "arabsama.com", "mangaae.com", "ozulscans.com",
            "mangat.to", "mangat.me", "mangazone.net",
            "gmanga.org", "onma.net",
            "mangaadm.com", "7oman.com",
            "shaymanga.net", "mangaswat.com",
            "mangatime.com",
        ]

        # ── مواقع Madara WordPress (100+ موقع) ───────────────────────────────
        self.madara_sites = [
            # Flame / Reaper / Luminous / Night
            "flamescans.org", "flamecomics.xyz", "flamecomics.me", "flamecomics.io",
            "reaperscans.com", "reapercomics.com",
            "luminousscans.net", "luminousscans.com",
            "nightscans.net", "nightcomic.com",
            "disasterscans.com",
            # كورية / ترجمة إنجليزية شهيرة
            "toonily.com", "toonily.net",
            "manhuaplus.com", "manhuafast.com",
            "webtoon.xyz",
            "mangaonlineteam.com", "mangapro.com",
            "utoon.net", "utoon.co",
            "isekaiscan.com", "isekaiscan.to",
            "azuremanga.com", "aquamanga.com",
            "247manga.com", "mangabaz.net",
            "zinmanga.com", "mangatx.com",
            "kunmanga.com", "topmanhua.com",
            "manhuaus.com", "1stkissmanga.io", "1stkissmanga.love",
            "s2manga.com", "infernalvoidscans.com",
            "manhwaclan.com", "manhwatop.com",
            "toongod.org", "mangaclash.com",
            "biblioscan.me", "rawkuma.com",
            "manga68.com", "manhua88.com",
            "manhuazone.net",
            "chapscans.com", "drake-scans.com",
            "void-scans.com",
            # Scans شهيرة
            "reset-scans.com", "reset-scans.us",
            "alpha-scans.net",
            "hivescans.com", "hive-scans.com",
            "dragontea.ink",
            "suryascans.com",
            "immortalupdates.com",
            "nitroscans.com",
            "mangapanda.onl", "mangapanda.in",
            "secretscans.com",
            "mangadistrict.com",
            "phenixscans.fr", "phenixscans.com",
            "setsuscans.com",
            "leviatanscans.com",
            "sushiscan.net", "sushiscan.fr",
            # مانهوا / مانهوا صينية
            "manhuadex.com", "manhuascan.us",
            "readmanhua.com", "readmanhuax.com",
            "manhwafreaks.com", "readmanhwa.com",
            "kingofshojo.com",
            "lhtranslation.net",
            "scansmangas.com",
            # مواقع متنوعة
            "mangageko.com",
            "mangahere.cc",
            "readmanga.today",
            "mangabuddy.com",
            "harimanga.com",
            "klmanga.net", "klmanga.com",
            "manga4life.com",
            "mangasee123.com",
            "mangaworld.biz", "mangaworld.ac",
            "mangakomi.io",
            "mangajar.com",
            "mangaread.org",
            "mangaraw.org", "mangarawjp.io",
            "rawmanga.top",
            "readm.org", "readmangabat.com",
            "zeroscans.com",
            "galaxymanga.net", "galaxymanga.org",
            "mangaowl.net", "mangaowl.to",
            "colamanga.com",
            "manhwabuddy.com",
            "manytoon.com",
            "manhwa18.com", "manhwa18.org",
            "manhwax.com",
            "asura.nacm.xyz",
            "skymanga.xyz",
        ]

    def get_provider(self, url: str):
        url_lower = url.lower()

        # مزودات بـ API مخصص
        if "mangadex.org" in url_lower:
            return self.mangadex

        if "mangaplus.shueisha" in url_lower:
            return self.mangaplus

        if any(x in url_lower for x in self.comick_sites):
            return self.comick

        if any(x in url_lower for x in self.mangafire_sites):
            return self.mangafire

        if any(x in url_lower for x in self.bato_sites):
            return self.bato

        # مزودات مخصصة
        if any(x in url_lower for x in ["asurascans", "asura.gg", "asuracomics",
                                          "asuratoon", "asura.nacm.xyz"]):
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

        # المواقع العربية
        if any(s in url_lower for s in self.arabic_sites):
            return self.arabic

        # Madara WordPress
        if any(s in url_lower for s in self.madara_sites):
            return self.madara

        return self.generic

    def get_provider_name(self, url: str) -> str:
        p = self.get_provider(url)
        return type(p).__name__.replace("Provider", "")

    async def search_manga(self, query: str, limit: int = 10) -> list:
        """بحث عن مانجا بالاسم عبر MangaDex API"""
        try:
            import aiohttp
            api = "https://api.mangadex.org"
            params = {
                "title": query,
                "limit": limit,
                "order[relevance]": "desc",
                "contentRating[]": ["safe", "suggestive", "erotica"],
                "includes[]": ["cover_art"],
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{api}/manga",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as r:
                    if r.status != 200:
                        return []
                    data = await r.json()

            results = []
            for manga in data.get("data", []):
                attrs    = manga.get("attributes", {})
                title_obj = attrs.get("title", {})
                title    = (title_obj.get("en") or title_obj.get("ja-ro")
                            or next(iter(title_obj.values()), "Unknown"))
                desc_obj = attrs.get("description", {})
                desc     = desc_obj.get("en", "")[:200] if desc_obj else ""
                status   = attrs.get("status", "unknown")
                mid      = manga["id"]
                url_out  = f"https://mangadex.org/title/{mid}"

                cover_url = None
                for rel in manga.get("relationships", []):
                    if rel["type"] == "cover_art":
                        fname = rel.get("attributes", {}).get("fileName", "")
                        if fname:
                            cover_url = f"https://uploads.mangadex.org/covers/{mid}/{fname}.256.jpg"
                        break

                results.append({
                    "title":       title,
                    "url":         url_out,
                    "description": desc,
                    "status":      status,
                    "cover":       cover_url,
                })
            return results
        except Exception as e:
            print(f"[Search] error: {e}")
            return []

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
        images   = []
        try:
            if asyncio.iscoroutinefunction(provider.get_images):
                images = await provider.get_images(url)
            else:
                loop   = asyncio.get_event_loop()
                images = await loop.run_in_executor(None, provider.get_images, url)
        except Exception as e:
            print(f"[ProviderManager] get_images error: {e}")

        if not images and provider is not self.generic:
            print(f"⚠️ فشل {type(provider).__name__}، جاري تجربة GenericProvider...")
            try:
                loop   = asyncio.get_event_loop()
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
                loop     = asyncio.get_event_loop()
                chapters = await loop.run_in_executor(None, provider.get_all_chapters, url)
        except Exception as e:
            print(f"[ProviderManager] get_all_chapters error: {e}")

        if not chapters and provider is not self.generic:
            print(f"⚠️ فشل {type(provider).__name__}، جاري تجربة GenericProvider...")
            try:
                loop     = asyncio.get_event_loop()
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
