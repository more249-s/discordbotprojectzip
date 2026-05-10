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
from .bilibili_provider import BilibiliProvider
from .kakao_provider import KakaoProvider
from .lekmanga_provider import LekMangaProvider
from .raw_providers import (
    AcQQProvider, KuaikanProvider, LineMangaProvider,
    PiccomaProvider, IqiyiProvider,
)
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
        self.bilibili    = BilibiliProvider()
        self.kakao       = KakaoProvider()
        self.lekmanga    = LekMangaProvider()
        self.acqq        = AcQQProvider()
        self.kuaikan     = KuaikanProvider()
        self.linemanga   = LineMangaProvider()
        self.piccoma     = PiccomaProvider()
        self.iqiyi       = IqiyiProvider()

        self.gemini_client   = GeminiClient()
        self.gemini_fallback = GeminiProvider(self.gemini_client, scraper=self.generic.scraper)

        # ── RAW الأصلية ─────────────────────────────────────────────────────
        self.bilibili_sites  = ["manga.bilibili.com", "bilibili.com/manga"]
        self.kakao_sites     = ["page.kakao.com", "webtoon.kakao.com", "kakaopage.com"]
        self.acqq_sites      = ["ac.qq.com", "ac.q.qq.com"]
        self.kuaikan_sites   = ["kuaikanmanhua.com", "kuaikan.com"]
        self.linemanga_sites = ["manga.line.me", "lin.ee/manga"]
        self.piccoma_sites   = ["piccoma.com", "piccoma.jp"]
        self.iqiyi_sites     = ["manhua.iqiyi.com", "iqiyi.com/manhua"]

        self.manganato_sites = [
            "manganato", "mangakakalot", "manganelo", "chapmanganato",
            "readmanganato", "mangakakalots",
        ]
        self.bato_sites    = ["bato.to", "batotoo.com", "dto.to", "bato.site"]
        self.comick_sites  = ["comick.fun", "comick.io", "comick.cc", "comick.app"]
        self.mangafire_sites = ["mangafire.to"]

        self.lekmanga_sites = ["lekmanga.net", "lekmanga.com"]

        self.arabic_sites = [
            "mangalek.com",
            "3asq.to", "3asq.net", "3asq.org",
            "manga-ar.com", "mangaarab.com", "manga-ar.net",
            "arabsama.com", "mangaae.com", "ozulscans.com",
            "mangat.to", "mangat.me", "mangazone.net",
            "gmanga.org", "onma.net", "mangaadm.com",
            "7oman.com", "shaymanga.net", "mangaswat.com",
            "mangatime.com",
        ]

        self.madara_sites = [
            "flamescans.org", "flamecomics.xyz", "flamecomics.me", "flamecomics.io",
            "reaperscans.com", "reapercomics.com",
            "luminousscans.net", "luminousscans.com",
            "nightscans.net", "nightcomic.com", "disasterscans.com",
            "toonily.com", "toonily.net",
            "manhuaplus.com", "manhuafast.com",
            "webtoon.xyz", "mangaonlineteam.com",
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
            "manga68.com", "manhua88.com", "manhuazone.net",
            "chapscans.com", "drake-scans.com", "void-scans.com",
            "reset-scans.com", "alpha-scans.net",
            "hivescans.com", "hive-scans.com",
            "dragontea.ink", "suryascans.com",
            "immortalupdates.com", "nitroscans.com",
            "secretscans.com", "mangadistrict.com",
            "setsuscans.com", "leviatanscans.com",
            "zeroscans.com", "skymanga.xyz",
            "asura.nacm.xyz",
            # فرنسية
            "sushiscan.net", "sushiscan.fr",
            "phenixscans.fr", "phenixscans.com",
            "scantrad-vf.co", "scantrad.net",
            "scan-vf.net", "scan-vf.to",
            "fr.mangatoto.com", "mangas-origines.fr",
            "japanread.fr", "mangaparadise.fr",
            "lelscan-vf.com", "animesama.fr",
            "scansmangas.com", "manga-scantrad.net", "scan-manga.com",
            # إندونيسية
            "komiku.org", "komiku.id",
            "manhwaindo.id", "manhwaindo.net",
            "komikcast.com", "komikcast.biz",
            "mangkomik.id", "mangkomik.com",
            "kiryuu.id", "kiryuu.co",
            "westmanga.id", "westmanga.net",
            "gudangkomik.com", "klikmanga.id",
            "bacakomik.co", "doujindesu.tv",
            "shinigamid.me",
            # إسبانية
            "tumangaonline.co", "tumangaonline.org",
            "lectortmo.com", "mangatigre.com",
            "mangaes.net", "manhuaes.com",
            "leercomics.com", "ikigaimangas.com", "mangatigre.org",
            # برتغالية
            "mangalivre.net", "mangalivre.org",
            "unionmangas.xyz", "unionmangas.net",
            "brmangas.net", "brmangas.com",
            "mangasproject.net", "centraldemangas.net", "taosect.com",
            # روسية
            "mangalib.me", "mangalib.org",
            "remanga.org", "readmanga.live", "manga-chan.me",
            # متنوعة
            "manga108.org", "mangathailand.com",
            "mangalist.de", "manfra.de", "mangadeutsch.com",
            "mangaworld.biz", "mangaworld.ac", "mangaeden.com",
            "mangageko.com", "mangahere.cc",
            "readmanga.today", "mangabuddy.com",
            "harimanga.com", "klmanga.net", "klmanga.com",
            "manga4life.com", "mangasee123.com",
            "mangakomi.io", "mangajar.com",
            "mangaread.org", "rawmanga.top",
            "readm.org", "readmangabat.com",
            "galaxymanga.net", "galaxymanga.org",
            "mangaowl.net", "mangaowl.to",
            "colamanga.com", "manhwabuddy.com",
            "manytoon.com", "manhwa18.com", "manhwa18.org",
            "manhwax.com", "mangaraw.org", "mangarawjp.io",
            "manhuadex.com", "manhuascan.us",
            "readmanhua.com", "readmanhuax.com",
            "manhwafreaks.com", "readmanhwa.com",
            "kingofshojo.com", "lhtranslation.net",
        ]

        # مواقع مخصصة مضافة من قاعدة البيانات
        self._custom_madara: list = []
        self._custom_arabic: list = []
        self._custom_generic: list = []
        self._custom_loaded = False

    async def _load_custom_sites(self):
        """تحميل المواقع المخصصة من قاعدة البيانات."""
        try:
            import database
            self._custom_madara  = await database.get_custom_madara_sites()
            self._custom_arabic  = await database.get_custom_arabic_sites()
            all_sites = await database.get_custom_sites()
            self._custom_generic = [d[0] for d in all_sites if d[1] == "generic"]
            self._custom_loaded  = True
        except Exception as e:
            print(f"[ProviderManager] failed to load custom sites: {e}")

    async def reload_custom_sites(self):
        """إعادة تحميل المواقع المخصصة بعد إضافة جديدة."""
        await self._load_custom_sites()
        print(f"[ProviderManager] Reloaded: {len(self._custom_madara)} madara, "
              f"{len(self._custom_arabic)} arabic, {len(self._custom_generic)} generic")

    def get_provider(self, url: str):
        url_lower = url.lower()

        # ── RAW الأصلية ──────────────────────────────────────────────────
        if any(x in url_lower for x in self.bilibili_sites): return self.bilibili
        if any(x in url_lower for x in self.kakao_sites):    return self.kakao
        if any(x in url_lower for x in self.acqq_sites):     return self.acqq
        if any(x in url_lower for x in self.kuaikan_sites):  return self.kuaikan
        if any(x in url_lower for x in self.linemanga_sites): return self.linemanga
        if any(x in url_lower for x in self.piccoma_sites):  return self.piccoma
        if any(x in url_lower for x in self.iqiyi_sites):    return self.iqiyi

        # ── API مخصص ─────────────────────────────────────────────────────
        if "mangadex.org" in url_lower:                       return self.mangadex
        if "mangaplus.shueisha" in url_lower:                 return self.mangaplus
        if any(x in url_lower for x in self.comick_sites):   return self.comick
        if any(x in url_lower for x in self.mangafire_sites): return self.mangafire
        if any(x in url_lower for x in self.bato_sites):     return self.bato

        # ── مزودات مخصصة ─────────────────────────────────────────────────
        if any(x in url_lower for x in ["asurascans", "asura.gg", "asuracomics",
                                         "asuratoon", "asura.nacm.xyz"]):
            return self.asura
        if "vortexscans" in url_lower:                        return self.vortex
        if any(x in url_lower for x in ["qimanhwa", "qimanhua"]): return self.qimanhwa
        if "mangapill" in url_lower:                          return self.mangapill
        if any(s in url_lower for s in self.manganato_sites): return self.manganato
        if "webtoons.com" in url_lower:                       return self.webtoons
        if "comic.naver.com" in url_lower:                    return self.naver
        if "weebcentral.com" in url_lower:                    return self.weebcentral
        if any(x in url_lower for x in ["tcbscans", "tcb-scans"]): return self.tcbscans

        # ── LekManga ─────────────────────────────────────────────────────
        if any(s in url_lower for s in self.lekmanga_sites):  return self.lekmanga

        # ── المواقع العربية ───────────────────────────────────────────────
        if any(s in url_lower for s in self.arabic_sites):    return self.arabic
        # مخصصة عربية
        if any(s in url_lower for s in self._custom_arabic):  return self.arabic

        # ── Madara WordPress ──────────────────────────────────────────────
        if any(s in url_lower for s in self.madara_sites):    return self.madara
        # مخصصة Madara
        if any(s in url_lower for s in self._custom_madara):  return self.madara

        # ── مخصصة Generic ────────────────────────────────────────────────
        if any(s in url_lower for s in self._custom_generic): return self.generic

        return self.generic

    def get_provider_name(self, url: str) -> str:
        p = self.get_provider(url)
        return type(p).__name__.replace("Provider", "")

    async def get_series_cover(self, url: str) -> str | None:
        import aiohttp, re
        from bs4 import BeautifulSoup

        if "mangadex.org" in url:
            try:
                m = re.search(r'mangadex\.org/title/([a-z0-9-]+)', url)
                if m:
                    mid = m.group(1)
                    async with aiohttp.ClientSession() as s:
                        async with s.get(
                            f"https://api.mangadex.org/manga/{mid}?includes[]=cover_art",
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as r:
                            if r.status == 200:
                                data = await r.json()
                    for rel in data.get("data", {}).get("relationships", []):
                        if rel["type"] == "cover_art":
                            fn = rel.get("attributes", {}).get("fileName", "")
                            if fn:
                                return f"https://uploads.mangadex.org/covers/{mid}/{fn}.512.jpg"
            except Exception:
                pass

        if any(x in url for x in ["comick.fun", "comick.io", "comick.cc"]):
            try:
                slug = url.rstrip("/").split("/")[-1]
                async with aiohttp.ClientSession() as s:
                    async with s.get(
                        f"https://api.comick.fun/comic/{slug}",
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as r:
                        if r.status == 200:
                            d = await r.json()
                            cover = d.get("comic", {}).get("md_covers", [{}])[0].get("b2key", "")
                            if cover:
                                return f"https://meo.comick.pictures/{cover}"
            except Exception:
                pass

        loop = asyncio.get_event_loop()
        def _scrape():
            try:
                html = self.generic.fetch_html(url)
                if not html:
                    return None
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
                if og and og.get("content", "").startswith("http"):
                    return og["content"]
                tw = soup.find("meta", attrs={"name": "twitter:image"})
                if tw and tw.get("content", "").startswith("http"):
                    return tw["content"]
                for sel in ["img.img-cover", ".summary_image img", ".thumb img",
                            ".series-thumb img", ".manga-cover img", "img.cover"]:
                    el = soup.select_one(sel)
                    if el:
                        src = el.get("src") or el.get("data-src") or el.get("data-lazy-src", "")
                        if src.startswith("http"):
                            return src
            except Exception:
                pass
            return None
        return await loop.run_in_executor(None, _scrape)

    async def get_chapters_with_lock_info(self, url: str) -> dict:
        if not self._custom_loaded:
            await self._load_custom_sites()

        from .paginated_scraper import PaginatedScraper

        provider = self.get_provider(url)
        pname    = type(provider).__name__

        if "Bilibili" in pname:
            try:
                import aiohttp
                comic_id = provider._extract_comic_id(url)
                if comic_id:
                    async with aiohttp.ClientSession(headers=provider.HEADERS) as s:
                        async with s.post(
                            f"{provider.API}/ComicDetail",
                            json={"comic_id": int(comic_id)},
                            timeout=aiohttp.ClientTimeout(total=15)
                        ) as r:
                            if r.status == 200:
                                data = await r.json()
                    if data.get("code") == 0:
                        result = {}
                        for ep in data.get("data", {}).get("ep_list", []):
                            ep_id  = ep.get("id")
                            ord_   = ep.get("ord")
                            locked = ep.get("is_locked", True)
                            if ep_id and ord_:
                                try:
                                    result[float(ord_)] = {
                                        "url":    f"https://manga.bilibili.com/mc{comic_id}/{ep_id}",
                                        "locked": locked,
                                        "reason": "bilibili-api",
                                    }
                                except Exception:
                                    pass
                        if result:
                            return result
            except Exception as e:
                print(f"[BilibiliLock] {e}")

        if pname in ("Generic", "Madara", "Arabic", "MangaFire",
                     "Bato", "Asura", "Vortex", "MangaPill",
                     "Manganato", "WeebCentral", "LekManga"):
            try:
                scraper = PaginatedScraper(
                    fetch_fn=self.generic.fetch_html,
                    max_pages=50,
                )
                rich = await scraper.get_all_chapters(url, detect_lock=True)
                if rich:
                    print(f"[PaginatedScraper] {len(rich)} chapters from {url}")
                    locked_cnt = sum(1 for v in rich.values() if v.get("locked"))
                    if locked_cnt:
                        print(f"[PaginatedScraper] 🔒 {locked_cnt} locked chapters")
                    return rich
            except Exception as e:
                print(f"[PaginatedScraper] error: {e}")

        chapters = await self.get_all_chapters(url)
        return {
            num: {"url": ch_url, "locked": False, "reason": "no-lock-data"}
            for num, ch_url in chapters.items()
        }

    async def search_manga(self, query: str, limit: int = 10) -> list:
        try:
            import aiohttp
            params = {
                "title": query,
                "limit": limit,
                "order[relevance]": "desc",
                "contentRating[]": ["safe", "suggestive", "erotica"],
                "includes[]": ["cover_art"],
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.mangadex.org/manga",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as r:
                    if r.status != 200:
                        return []
                    data = await r.json()

            results = []
            for manga in data.get("data", []):
                attrs     = manga.get("attributes", {})
                title_obj = attrs.get("title", {})
                title     = (title_obj.get("en") or title_obj.get("ja-ro")
                             or next(iter(title_obj.values()), "Unknown"))
                desc_obj  = attrs.get("description", {})
                desc      = desc_obj.get("en", "")[:200] if desc_obj else ""
                status    = attrs.get("status", "unknown")
                mid       = manga["id"]
                url_out   = f"https://mangadex.org/title/{mid}"

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
        if not self._custom_loaded:
            await self._load_custom_sites()
        provider = self.get_provider(url)
        try:
            if asyncio.iscoroutinefunction(provider.get_latest_chapter):
                chapter = await provider.get_latest_chapter(url)
            else:
                loop = asyncio.get_event_loop()
                chapter = await loop.run_in_executor(None, provider.get_latest_chapter, url)
            return float(chapter) if chapter is not None else None
        except Exception as e:
            print(f"[ProviderManager] get_latest_chapter error for {url}: {e}")
            return None

    async def get_all_chapters(self, url: str) -> dict:
        if not self._custom_loaded:
            await self._load_custom_sites()
        provider = self.get_provider(url)
        try:
            if asyncio.iscoroutinefunction(provider.get_all_chapters):
                chapters = await provider.get_all_chapters(url)
            else:
                loop = asyncio.get_event_loop()
                chapters = await loop.run_in_executor(None, provider.get_all_chapters, url)
            return chapters or {}
        except Exception as e:
            print(f"[ProviderManager] get_all_chapters error for {url}: {e}")
            return {}

    async def get_images(self, url: str) -> list:
        if not self._custom_loaded:
            await self._load_custom_sites()
        provider = self.get_provider(url)
        try:
            if asyncio.iscoroutinefunction(provider.get_images):
                images = await provider.get_images(url)
            else:
                loop = asyncio.get_event_loop()
                images = await loop.run_in_executor(None, provider.get_images, url)
            return images or []
        except Exception as e:
            print(f"[ProviderManager] get_images error: {e}")
            return []
