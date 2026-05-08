import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import asyncio
import datetime
import re
import os
from typing import Optional
import database
from manga_downloader import MangaDownloader

RADAR_CONCURRENT  = 5
CHAPTERS_PER_PAGE = 20

# ── ألوان ─────────────────────────────────────────────────────────────────
C_IDLE  = discord.Color.from_rgb(30,  31,  34)    # خلفية داكنة محايدة
C_RUN   = discord.Color.from_rgb(245, 158,  11)   # ذهبي عنبري
C_DONE  = discord.Color.from_rgb(34,  197,  94)   # أخضر نضاري
C_FAIL  = discord.Color.from_rgb(239,  68,  68)   # أحمر
C_RADAR = discord.Color.from_rgb(99,  102, 241)   # بنفسجي indigo
C_GREY  = discord.Color.from_rgb(71,  85, 105)    # رمادي سليت

# ── أيقونات الحالة ─────────────────────────────────────────────────────────
ICO = {
    "idle":        "◻",
    "selected":    "◈",
    "queued":      "◷",
    "downloading": "↓",
    "stitching":   "⊕",
    "uploading":   "↑",
    "done":        "✓",
    "failed":      "✗",
}

# ── شريط تقدم عصري ────────────────────────────────────────────────────────
def pbar(pct: int, length: int = 16) -> str:
    filled = int(round(pct / 100 * length))
    empty  = length - filled
    return f"{'█' * filled}{'░' * empty}  {pct:>3}%"

def _lbl(num) -> str:
    return str(int(num)) if float(num).is_integer() else str(num)

def _series_name(url: str) -> str:
    parts = [p for p in url.rstrip("/").split("/") if p]
    return parts[-1].replace("-", " ").replace("_", " ").title() if parts else "Manga"

def _domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return url


# ─────────────────────────────────────────────────────────────────────────
#  Modal — نطاق الفصول
# ─────────────────────────────────────────────────────────────────────────
class RangeModal(ui.Modal, title="تحديد نطاق الفصول"):
    text = ui.TextInput(
        label="أدخل النطاق أو الفصول",
        placeholder="أمثلة:  80-100  |  1,5,10  |  latest:10",
        min_length=1, max_length=120,
        style=discord.TextStyle.short,
    )

    def __init__(self, panel: "MangaPanelView"):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction):
        raw  = self.text.value.strip()
        nums = set(self.panel.all_chapters)
        sel: set[float] = set()

        try:
            if raw.lower().startswith("latest:"):
                n   = int(raw.split(":")[1])
                sel = set(self.panel.all_chapters[:n])
            elif re.match(r"^\d+(\.\d+)?-\d+(\.\d+)?$", raw):
                lo, hi = (float(x) for x in raw.split("-"))
                if lo > hi:
                    lo, hi = hi, lo
                sel = {n for n in nums if lo <= n <= hi}
            else:
                for tok in raw.replace(" ", "").split(","):
                    try:
                        v = float(tok)
                        if v in nums:
                            sel.add(v)
                    except ValueError:
                        pass
        except Exception:
            pass

        if not sel:
            return await interaction.response.send_message(
                f"❌  لم يُعثر على فصول بهذه القيمة.\n"
                f"الفصول المتاحة: `{_lbl(min(nums))}` ← `{_lbl(max(nums))}`",
                ephemeral=True,
            )

        self.panel.selected = sorted(set(self.panel.selected) | sel, reverse=True)
        self.panel.page     = self.panel._page_for(max(sel))
        self.panel._rebuild()
        await interaction.response.edit_message(
            embed=self.panel.build_embed(
                f"✓  أُضيف {len(sel)} فصل  ·  "
                f"Ch.{_lbl(min(sel))} → Ch.{_lbl(max(sel))}"
            ),
            view=self.panel,
        )


# ─────────────────────────────────────────────────────────────────────────
#  MangaPanelView
# ─────────────────────────────────────────────────────────────────────────
class MangaPanelView(ui.View):

    def __init__(self, bot, downloader, provider_manager,
                 series_url, chapters_dict,
                 requester: discord.User = None,
                 provider_name: str = "Generic"):
        super().__init__(timeout=1800)
        self.bot              = bot
        self.downloader       = downloader
        self.provider_manager = provider_manager
        self.series_url       = series_url
        self.requester        = requester
        self.provider_name    = provider_name

        self.all_chapters : list[float] = sorted(chapters_dict.keys(), reverse=True)
        self.chapters_dict              = chapters_dict
        self.page                       = 0
        self.selected     : list[float] = []
        self.ch_status    : dict        = {}
        self.running                    = False

        self._rebuild()

    @property
    def total_pages(self) -> int:
        return max(1, (len(self.all_chapters) + CHAPTERS_PER_PAGE - 1) // CHAPTERS_PER_PAGE)

    @property
    def page_chs(self) -> list[float]:
        s = self.page * CHAPTERS_PER_PAGE
        return self.all_chapters[s: s + CHAPTERS_PER_PAGE]

    def _page_for(self, num: float) -> int:
        try:
            return self.all_chapters.index(num) // CHAPTERS_PER_PAGE
        except ValueError:
            return 0

    # ── بناء العناصر ──────────────────────────────────────────────────────
    def _rebuild(self):
        self.clear_items()
        chs   = self.page_chs
        sel_s = set(self.selected)

        # ── صف 0: select menu ─────────────────────────────────────────────
        if chs:
            opts = [
                discord.SelectOption(
                    label=f"Ch.{_lbl(n):>6}",
                    value=str(n),
                    emoji=("✅" if self.ch_status.get(n, {}).get("state") == "done"
                           else ("🔵" if n in sel_s else "▫️")),
                    description=(
                        "✓ مكتمل" if self.ch_status.get(n, {}).get("state") == "done"
                        else ("محدد للتحميل" if n in sel_s else "اضغط للإضافة")
                    ),
                    default=(n in sel_s),
                )
                for n in chs
            ]
            menu = ui.Select(
                placeholder=f"📖  الصفحة {self.page+1}/{self.total_pages}  —  اختر فصولاً",
                min_values=1, max_values=len(opts),
                options=opts, row=0, disabled=self.running,
            )
            menu.callback = self._cb_select
            self.add_item(menu)

        # ── صف 1: تنقل ────────────────────────────────────────────────────
        at_s = self.page == 0
        at_e = self.page >= self.total_pages - 1
        d    = self.running

        for emoji, cb, dis in [("⏮️", self._cb_first, at_s or d), ("◀️", self._cb_prev, at_s or d)]:
            b = ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary, row=1, disabled=dis)
            b.callback = cb; self.add_item(b)

        self.add_item(ui.Button(
            label=f"{self.page+1} / {self.total_pages}",
            style=discord.ButtonStyle.secondary, row=1, disabled=True,
        ))

        for emoji, cb, dis in [("▶️", self._cb_next, at_e or d), ("⏭️", self._cb_last, at_e or d)]:
            b = ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary, row=1, disabled=dis)
            b.callback = cb; self.add_item(b)

        # ── صف 2: اختيار سريع ────────────────────────────────────────────
        for emoji, lbl, style, cb in [
            ("⭐", "آخر فصل",  discord.ButtonStyle.primary,   self._cb_l1),
            ("📦", "آخر 5",   discord.ButtonStyle.secondary,  self._cb_l5),
            ("📄", "الصفحة",  discord.ButtonStyle.secondary,  self._cb_pg),
            ("✏️", "نطاق",   discord.ButtonStyle.secondary,  self._cb_range),
            ("🗑️", "مسح",   discord.ButtonStyle.danger,     self._cb_clear),
        ]:
            b = ui.Button(emoji=emoji, label=lbl, style=style, row=2, disabled=self.running)
            b.callback = cb; self.add_item(b)

        # ── صف 3: تحكم ───────────────────────────────────────────────────
        b_go = ui.Button(
            label=f"  ابدأ التحميل  [ {len(self.selected)} ]",
            style=discord.ButtonStyle.success, emoji="🚀", row=3, disabled=self.running,
        )
        b_go.callback = self._cb_start; self.add_item(b_go)

        b_x = ui.Button(label="  إغلاق", style=discord.ButtonStyle.secondary,
                         emoji="✖️", row=3, disabled=self.running)
        b_x.callback = self._cb_close; self.add_item(b_x)

    # ── بناء الـ Embed ─────────────────────────────────────────────────────
    def build_embed(self, note: str = None, color=None) -> discord.Embed:
        color  = color or (C_RUN if self.running else C_IDLE)
        series = _series_name(self.series_url)
        site   = _domain(self.series_url)
        sel_s  = set(self.selected)
        chs    = self.page_chs
        total  = len(self.all_chapters)
        selcnt = len(self.selected)
        pct_s  = int(selcnt / max(total, 1) * 100)

        # ── title
        state_icon = "⚙️" if self.running else "📚"
        em = discord.Embed(
            title=f"{state_icon}  {series}",
            color=color,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        # ── description: info panel in code block ─────────────────────────
        status_txt = "● جاري التحميل" if self.running else "● جاهز"
        em.description = (
            f"```yaml\n"
            f"  Site     : {site}\n"
            f"  Provider : {self.provider_name}\n"
            f"  Status   : {status_txt}\n"
            f"─────────────────────────────\n"
            f"  Chapters : {total:<6}  Selected : {selcnt} ({pct_s}%)\n"
            f"  Page     : {self.page+1}/{self.total_pages}"
            f"{'  Range : Ch.' + _lbl(min(sel_s)) + ' → Ch.' + _lbl(max(sel_s)) if sel_s else ''}\n"
            f"```"
        )

        # ── chapter grid ──────────────────────────────────────────────────
        if chs:
            COLS  = 5
            rows  = []
            row   = []
            ch_lo = _lbl(min(chs))
            ch_hi = _lbl(max(chs))

            for n in chs:
                st    = self.ch_status.get(n, {})
                state = st.get("state", "")
                if state in ICO:
                    ico = ICO[state]
                elif n in sel_s:
                    ico = ICO["selected"]
                else:
                    ico = ICO["idle"]
                row.append(f"{ico} {_lbl(n):>4}")
                if len(row) == COLS:
                    rows.append("  ".join(row))
                    row = []
            if row:
                rows.append("  ".join(row))

            em.add_field(
                name=f"▸  Ch.{ch_lo} → {ch_hi}  │  صفحة {self.page+1}",
                value=f"```\n{chr(10).join(rows)}\n```",
                inline=False,
            )

            # legend (مختصر)
            legend = (
                f"`◻` غير محدد  `◈` محدد  "
                f"`↓` تحميل  `⊕` دمج  `↑` رفع  `✓` جاهز  `✗` فشل"
            )
            em.add_field(name="", value=legend, inline=False)

        # ── download queue (أثناء التشغيل) ────────────────────────────────
        if self.running:
            lines = []
            for n in sorted(self.selected):
                st    = self.ch_status.get(n, {})
                state = st.get("state", "queued")
                pct   = st.get("progress", 0)
                prov  = st.get("provider", "")
                link  = st.get("link", "")
                ico   = ICO.get(state, "◷")
                lbl   = _lbl(n)

                if state == "done":
                    line = f"`✓` **Ch.{lbl}**  ─  {prov}  [↗]({link})" if link else f"`✓` **Ch.{lbl}**"
                elif state == "failed":
                    line = f"`✗` **Ch.{lbl}**  ─  {st.get('detail','فشل')[:35]}"
                elif state in ("downloading", "uploading"):
                    bar  = pbar(pct, 12)
                    line = f"`{ico}` **Ch.{lbl}**  `{bar}`  {prov}"
                elif state == "stitching":
                    line = f"`⊕` **Ch.{lbl}**  SmartStitch..."
                else:
                    line = f"`◷` **Ch.{lbl}**  في الانتظار"
                lines.append(line)

            chunk = lines[:10]
            if len(lines) > 10:
                chunk.append(f"*... و {len(lines)-10} فصل آخر*")
            em.add_field(name="⚡  قائمة التنفيذ", value="\n".join(chunk), inline=False)

        # ── روابط جاهزة (بعد انتهاء التحميل) ─────────────────────────────
        ready = [
            (n, self.ch_status[n])
            for n in sorted(self.selected)
            if self.ch_status.get(n, {}).get("state") == "done"
            and self.ch_status[n].get("link")
        ]
        if ready and not self.running:
            lnks = "  ·  ".join(
                f"[Ch.{_lbl(n)}]({d['link']})" for n, d in ready[:10]
            )
            em.add_field(name="🔗  روابط جاهزة", value=lnks, inline=False)

        if note:
            em.add_field(name="", value=f"```fix\n{note}\n```", inline=False)

        em.set_footer(text=f"Cat-Bi  ·  Gofile → Catbox  ·  {site}")
        return em

    # ── navigation callbacks ──────────────────────────────────────────────
    async def _cb_select(self, interaction: discord.Interaction):
        chosen = {float(v) for v in interaction.data["values"]}
        page_s = set(self.page_chs)
        others = {n for n in self.selected if n not in page_s}
        self.selected = sorted(others | chosen, reverse=True)
        self._rebuild()
        await interaction.response.edit_message(
            embed=self.build_embed(f"☑  محدد الآن: {len(self.selected)} فصل"),
            view=self,
        )

    async def _cb_first(self, i):
        self.page = 0; self._rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)

    async def _cb_prev(self, i):
        self.page = max(0, self.page - 1); self._rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)

    async def _cb_next(self, i):
        self.page = min(self.total_pages - 1, self.page + 1); self._rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)

    async def _cb_last(self, i):
        self.page = self.total_pages - 1; self._rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)

    # ── quick-select callbacks ────────────────────────────────────────────
    async def _cb_l1(self, i):
        self.selected = self.all_chapters[:1]; self._rebuild()
        await i.response.edit_message(
            embed=self.build_embed(f"⭐  آخر فصل  ─  Ch.{_lbl(self.selected[0])}"), view=self)

    async def _cb_l5(self, i):
        self.selected = self.all_chapters[:5]; self._rebuild()
        await i.response.edit_message(embed=self.build_embed("📦  آخر 5 فصول"), view=self)

    async def _cb_pg(self, i):
        pg  = set(self.page_chs)
        oth = {n for n in self.selected if n not in pg}
        self.selected = sorted(oth | pg, reverse=True); self._rebuild()
        await i.response.edit_message(
            embed=self.build_embed(f"📄  أُضيفت كل فصول الصفحة ({len(self.page_chs)})"), view=self)

    async def _cb_range(self, i):
        await i.response.send_modal(RangeModal(self))

    async def _cb_clear(self, i):
        self.selected = []; self.ch_status = {}; self._rebuild()
        await i.response.edit_message(embed=self.build_embed("🗑  مُسح الاختيار"), view=self)

    async def _cb_close(self, i):
        for item in self.children:
            item.disabled = True
        await i.response.edit_message(
            embed=self.build_embed("✖  اللوحة مغلقة", color=C_GREY), view=self)
        self.stop()

    # ── start download ─────────────────────────────────────────────────────
    async def _cb_start(self, interaction: discord.Interaction):
        if self.running:
            return await interaction.response.send_message("⚠️ عملية جارية.", ephemeral=True)
        if not self.selected:
            return await interaction.response.send_message(
                "❗ اختر فصولاً أولاً.\nاستخدم القائمة أو ✏️ نطاق أو أزرار الاختيار السريع.",
                ephemeral=True,
            )

        self.running   = True
        to_dl          = sorted(self.selected)
        self.ch_status = {n: {"state": "queued"} for n in to_dl}
        self._rebuild()

        await interaction.response.edit_message(
            embed=self.build_embed(
                f"Starting {len(to_dl)} chapters  ·  "
                f"Ch.{_lbl(to_dl[0])} → Ch.{_lbl(to_dl[-1])}",
                color=C_RUN,
            ),
            view=self,
        )
        panel_msg = interaction.message

        for num in to_dl:
            url   = self.chapters_dict[num]
            lbl   = _lbl(num)
            self.ch_status[num] = {"state": "downloading", "progress": 0}
            last_edit = 0.0

            async def pcb(cur, tot, txt, _n=num, _l=lbl):
                nonlocal last_edit
                pct   = min(100, int(cur * 100 / max(tot, 1)))
                state = "downloading"
                if any(k in txt for k in ("SmartStitch", "دمج", "🪡", "stitch")):
                    state = "stitching"
                if "رفع" in txt or "upload" in txt.lower() or "☁️" in txt:
                    state = "uploading"
                prov = ("Gofile" if "Gofile" in txt
                        else "Catbox" if "Catbox" in txt else "")
                self.ch_status[_n].update(
                    {"state": state, "progress": pct, "provider": prov}
                )
                now = asyncio.get_running_loop().time()
                if now - last_edit < 2.0 and pct < 100:
                    return
                last_edit = now
                try:
                    await panel_msg.edit(embed=self.build_embed(f"Ch.{_l}  {txt}"))
                except Exception:
                    pass

            fp = None
            try:
                fp = await self.downloader.download_and_stitch(
                    url, f"Ch_{lbl}", progress_callback=pcb
                )
                if not fp:
                    self.ch_status[num] = {"state": "failed", "detail": "فشل جلب الصور"}
                    await panel_msg.edit(embed=self.build_embed(f"Ch.{lbl}  ─  فشل التحميل"))
                    continue

                link = prov = None
                for pname, pfn in [
                    ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=pcb)),
                    ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=pcb)),
                ]:
                    self.ch_status[num].update(
                        {"state": "uploading", "provider": pname, "progress": 0}
                    )
                    await panel_msg.edit(
                        embed=self.build_embed(f"Ch.{lbl}  →  {pname}  uploading...")
                    )
                    link = await pfn(fp)
                    if link:
                        prov = pname
                        break

                if link:
                    self.ch_status[num] = {
                        "state": "done", "progress": 100,
                        "provider": prov, "link": link,
                    }
                    await panel_msg.edit(
                        embed=self.build_embed(f"Ch.{lbl}  ✓  {prov}", color=C_DONE)
                    )
                else:
                    self.ch_status[num] = {
                        "state": "failed", "detail": "Gofile & Catbox failed"
                    }
                    await panel_msg.edit(
                        embed=self.build_embed(f"Ch.{lbl}  ✗  رفع فاشل", color=C_FAIL)
                    )

            except Exception as e:
                self.ch_status[num] = {"state": "failed", "detail": str(e)[:80]}
                await panel_msg.edit(
                    embed=self.build_embed(f"Ch.{lbl}  ✗  Error", color=C_FAIL)
                )
            finally:
                if fp:
                    self.downloader.cleanup(fp)
            await asyncio.sleep(0.5)

        # ── انتهى التحميل ──────────────────────────────────────────────────
        self.running = False
        done_list = [
            (n, self.ch_status[n]) for n in sorted(self.selected)
            if self.ch_status.get(n, {}).get("state") == "done"
        ]
        fail_list = [
            n for n in sorted(self.selected)
            if self.ch_status.get(n, {}).get("state") == "failed"
        ]
        fc = C_DONE if not fail_list else (C_FAIL if not done_list else C_RUN)
        self._rebuild()
        await panel_msg.edit(
            embed=self.build_embed(
                f"Done  ·  ✓ {len(done_list)} succeeded  ·  ✗ {len(fail_list)} failed",
                color=fc,
            ),
            view=self,
        )

        # ── منشن واحد في الآخر ────────────────────────────────────────────
        if done_list:
            mention = self.requester.mention if self.requester else ""
            series  = _series_name(self.series_url)

            summary = discord.Embed(
                title="📦  Download Complete",
                color=C_DONE,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            status_note = (
                f"✓  {len(done_list)} chapters ready"
                + (f"  ·  ✗  {len(fail_list)} failed" if fail_list else "")
            )
            failed_txt = (
                "\n**Failed:** " + ", ".join(f"Ch.{_lbl(n)}" for n in fail_list)
                if fail_list else ""
            )
            summary.description = (
                f"```yaml\n"
                f"  Series  : {series}\n"
                f"  Status  : {status_note}\n"
                f"  Site    : {_domain(self.series_url)}\n"
                f"```"
                + failed_txt
            )

            links_txt = "\n".join(
                f"[**Ch.{_lbl(n)}**  ─  {d.get('provider','')}]({d['link']})"
                for n, d in done_list
            )
            summary.add_field(
                name="🔗  Download Links",
                value=links_txt[:1020],
                inline=False,
            )
            summary.set_footer(text="Cat-Bi  ·  Manga System")
            await panel_msg.channel.send(content=mention, embed=summary)

        self.stop()


# ─────────────────────────────────────────────────────────────────────────
def is_admin():
    async def predicate(i: discord.Interaction):
        return i.user.guild_permissions.administrator
    return app_commands.check(predicate)


from providers.manager import ProviderManager


# ─────────────────────────────────────────────────────────────────────────
#  RadarCog
# ─────────────────────────────────────────────────────────────────────────
class RadarCog(commands.Cog):
    def __init__(self, bot):
        self.bot              = bot
        self.downloader       = MangaDownloader()
        self.provider_manager = ProviderManager()
        self.chapter_radar_loop.start()

    def cog_unload(self):
        self.chapter_radar_loop.cancel()

    async def fetch_latest(self, url: str, cur: float) -> Optional[float]:
        try:
            latest = await self.provider_manager.get_latest_chapter(url)
            if latest and latest > cur and latest <= cur + 15:
                return latest
        except Exception as e:
            print(f"[Radar] {url}: {e}")
        return None

    @tasks.loop(minutes=30)
    async def chapter_radar_loop(self):
        await self.bot.wait_until_ready()
        now      = datetime.datetime.now(datetime.timezone.utc)
        trackers = await database.get_all_trackers()
        if not trackers:
            return

        due = []
        for row in trackers:
            tid, gid, cid, url, last_ch, msg, interval, last_str, dl_en = row
            try:
                if (now - datetime.datetime.fromisoformat(last_str)) >= datetime.timedelta(hours=interval):
                    due.append(row)
            except Exception:
                due.append(row)
        if not due:
            return

        print(f"[Radar] فحص {len(due)}/{len(trackers)}")
        sem = asyncio.Semaphore(RADAR_CONCURRENT)

        async def check_one(row):
            tid, gid, cid, url, last_ch, msg, interval, _, dl_en = row
            async with sem:
                try:
                    latest = await self.fetch_latest(url, last_ch)
                    if not (latest and latest > last_ch):
                        await database.update_tracker_time(tid, now.isoformat())
                        return
                    print(f"[Radar] ✅ Ch.{latest} → {url}")
                    dl_link = None
                    if dl_en:
                        zp = await self.downloader.download_and_stitch(url, f"Ch_{latest}")
                        if zp:
                            dl_link = (
                                await self.downloader.upload_to_gofile(zp)
                                or await self.downloader.upload_to_catbox(zp)
                            )
                            self.downloader.cleanup(zp)
                    ch = self.bot.get_channel(cid)
                    if ch:
                        em = discord.Embed(
                            title="🚨  New Chapter!",
                            description=(
                                f"**Ch.{_lbl(latest)}** is now available\n"
                                f"*(Previous: Ch.{_lbl(last_ch)})*\n\n"
                                f"[🔗 Visit]({url})"
                            ),
                            color=C_RADAR, timestamp=now,
                        )
                        if dl_link:
                            em.add_field(name="📥  Download", value=f"[Click here]({dl_link})", inline=False)
                        em.set_footer(text="Cat-Bi Radar")
                        await ch.send(content=msg, embed=em)
                    await database.update_tracker_chapter(tid, latest, now.isoformat())
                except Exception as e:
                    print(f"[Radar] ❌ {tid}: {e}")
                    await database.update_tracker_time(tid, now.isoformat())

        await asyncio.gather(*[check_one(r) for r in due])

    # ── أوامر ─────────────────────────────────────────────────────────────
    @app_commands.command(name="track_add", description="[أدمن] إضافة عمل للرادار.")
    @app_commands.describe(url="رابط العمل", channel="روم الإشعارات",
                           custom_message="رسالة مرفقة", interval_hours="فحص كل كم ساعة",
                           current_chapter="الفصل الحالي", auto_download="تحميل تلقائي")
    @is_admin()
    @app_commands.guild_only()
    async def track_add_cmd(self, interaction: discord.Interaction,
                            url: str, channel: discord.TextChannel,
                            custom_message: str, interval_hours: int,
                            current_chapter: float, auto_download: bool = False):
        if interval_hours < 1:
            return await interaction.response.send_message("❌ أقل مدة: ساعة.", ephemeral=True)
        await database.add_tracker(interaction.guild_id, channel.id, url,
                                   custom_message, interval_hours, current_chapter,
                                   1 if auto_download else 0)
        em = discord.Embed(
            title="📡  تم تفعيل الرادار!", color=C_RADAR,
            description=(
                f"```yaml\n"
                f"  URL      : {url}\n"
                f"  Channel  : #{channel.name}\n"
                f"  Chapter  : {_lbl(current_chapter)}\n"
                f"  Interval : {interval_hours}h\n"
                f"  AutoDL   : {'yes' if auto_download else 'no'}\n"
                f"```"
            ),
        )
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="track_list", description="[أدمن] الأعمال المتتبعة.")
    @is_admin()
    @app_commands.guild_only()
    async def track_list_cmd(self, interaction: discord.Interaction):
        rows = [r for r in await database.get_all_trackers() if r[1] == interaction.guild_id]
        if not rows:
            return await interaction.response.send_message("لا توجد أعمال.", ephemeral=True)
        em = discord.Embed(title="📡  قائمة الرادار", color=C_RADAR,
                           timestamp=datetime.datetime.now(datetime.timezone.utc))
        desc = ""
        for tid, gid, cid, url, lch, msg, interval, _, dl in rows:
            ch   = self.bot.get_channel(cid)
            name = ch.mention if ch else "محذوف"
            desc += (f"`ID:{tid}` **{_series_name(url)}**\n"
                     f"↳ {name}  Ch.{_lbl(lch)}  {interval}h  DL:{'✓' if dl else '✗'}\n\n")
        em.description = desc[:3900]
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="track_remove", description="[أدمن] إزالة متتبع.")
    @app_commands.describe(tracker_id="الـ ID من track_list")
    @is_admin()
    @app_commands.guild_only()
    async def track_remove_cmd(self, interaction: discord.Interaction, tracker_id: int):
        ok = await database.remove_tracker(tracker_id, interaction.guild_id)
        em = discord.Embed(
            title="✅  Removed" if ok else "❌  Not Found",
            description=f"Tracker `{tracker_id}`",
            color=C_DONE if ok else C_FAIL,
        )
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="download_chapter", description="تحميل فصل واحد برابط مباشر.")
    @app_commands.describe(url="رابط الفصل")
    @is_admin()
    async def dl_chapter_cmd(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()
        msg = await interaction.followup.send("⏳  Preparing...")

        async def pcb(cur, tot, txt):
            bar = pbar(min(100, int(cur * 100 / max(tot, 1))))
            try:
                await msg.edit(content=f"```\n{txt}\n{bar}\n```")
            except Exception:
                pass

        try:
            ttl = f"Manual_{url.rstrip('/').split('/')[-2]}"
            fp  = await self.downloader.download_and_stitch(url, ttl, progress_callback=pcb)
            if not fp:
                return await msg.edit(content="❌  Failed to fetch images.")
            link = prov = None
            for pname, pfn in [
                ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=pcb)),
                ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=pcb)),
            ]:
                link = await pfn(fp)
                if link:
                    prov = pname; break
            self.downloader.cleanup(fp)
            if link:
                em = discord.Embed(
                    title="✅  Chapter Ready",
                    description=f"**{prov}**\n[📥  Download]({link})",
                    color=C_DONE, timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                await msg.edit(content=None, embed=em)
            else:
                await msg.edit(content="❌  Upload failed (Gofile & Catbox).")
        except Exception as e:
            await msg.edit(content=f"❌  Error: {e}")

    @app_commands.command(name="download_range", description="تحميل نطاق فصول — ضع {num} مكان رقم الفصل.")
    @app_commands.describe(base_url="رابط مع {num}", start_ch="أول فصل", end_ch="آخر فصل")
    @is_admin()
    async def dl_range_cmd(self, interaction: discord.Interaction,
                           base_url: str, start_ch: int, end_ch: int):
        if "{num}" not in base_url:
            return await interaction.response.send_message("❌ يجب أن يحتوي الرابط {num}.", ephemeral=True)
        if end_ch < start_ch or (end_ch - start_ch) > 20:
            return await interaction.response.send_message("❌ النطاق غير صالح (الحد 20).", ephemeral=True)
        await interaction.response.send_message(f"⏳  Downloading Ch.{start_ch} → Ch.{end_ch}")

        for ch in range(start_ch, end_ch + 1):
            url  = base_url.replace("{num}", str(ch))
            smsg = await interaction.channel.send(f"```\nCh.{ch}  ─  Starting...\n```")
            await asyncio.sleep(2)

            async def rcb(cur, tot, txt, _s=smsg, _c=ch):
                bar = pbar(min(100, int(cur * 100 / max(tot, 1))), 14)
                try:
                    await _s.edit(content=f"```\nCh.{_c}  ─  {txt}\n{bar}\n```")
                except Exception:
                    pass

            try:
                fp = await self.downloader.download_and_stitch(url, f"Ch_{ch}", progress_callback=rcb)
                if not fp:
                    await smsg.edit(content=f"```\nCh.{ch}  ─  ✗ Failed\n```"); continue
                link = prov = None
                for pname, pfn in [
                    ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=rcb)),
                    ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=rcb)),
                ]:
                    link = await pfn(fp)
                    if link:
                        prov = pname; break
                self.downloader.cleanup(fp)
                if link:
                    await smsg.edit(content=None, embed=discord.Embed(
                        title=f"✅  Ch.{ch}",
                        description=f"**{prov}**\n[📥 Download]({link})",
                        color=C_DONE,
                    ))
                else:
                    await smsg.edit(content=f"```\nCh.{ch}  ─  ✗ Upload failed\n```")
            except Exception as e:
                await interaction.channel.send(f"```\nCh.{ch}  ─  Error: {e}\n```")

        await interaction.channel.send("```\n✓  Range complete\n```")

    @app_commands.command(name="download_series", description="استخراج ذكي ثم تحميل نطاق.")
    @app_commands.describe(series_url="رابط صفحة المانجا", start_ch="أول فصل", end_ch="آخر فصل")
    @is_admin()
    async def dl_series_cmd(self, interaction: discord.Interaction,
                            series_url: str, start_ch: float, end_ch: float):
        if end_ch < start_ch or (end_ch - start_ch) > 20:
            return await interaction.response.send_message("❌ النطاق غير صالح (الحد 20).", ephemeral=True)
        await interaction.response.send_message("🔍  Analyzing page...")
        chs = await self.provider_manager.get_all_chapters(series_url)
        if not chs:
            return await interaction.channel.send("❌  Failed to extract chapters.")
        target = {n: u for n, u in chs.items() if start_ch <= n <= end_ch}
        if not target:
            return await interaction.channel.send(
                f"❌  No chapters in range.\n"
                f"Available: Ch.{_lbl(min(chs))} → Ch.{_lbl(max(chs))}"
            )
        await interaction.channel.send(f"```\n⏳  {len(target)} chapters queued\n```")

        for ch_n, url in sorted(target.items()):
            smsg = await interaction.channel.send(f"```\nCh.{_lbl(ch_n)}  ─  Starting...\n```")
            await asyncio.sleep(2)

            async def scb(cur, tot, txt, _s=smsg, _n=ch_n):
                bar = pbar(min(100, int(cur * 100 / max(tot, 1))), 14)
                try:
                    await _s.edit(content=f"```\nCh.{_lbl(_n)}  ─  {txt}\n{bar}\n```")
                except Exception:
                    pass

            try:
                fp = await self.downloader.download_and_stitch(url, f"Ch_{ch_n}", progress_callback=scb)
                if not fp:
                    await smsg.edit(content=f"```\nCh.{_lbl(ch_n)}  ─  ✗ Failed\n```"); continue
                link = prov = None
                for pname, pfn in [
                    ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=scb)),
                    ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=scb)),
                ]:
                    link = await pfn(fp)
                    if link:
                        prov = pname; break
                self.downloader.cleanup(fp)
                if link:
                    await smsg.edit(content=None, embed=discord.Embed(
                        title=f"✅  Ch.{_lbl(ch_n)}",
                        description=f"**{prov}**\n[📥 Download]({link})",
                        color=C_DONE,
                    ))
                else:
                    await smsg.edit(content=f"```\nCh.{_lbl(ch_n)}  ─  ✗ Upload failed\n```")
            except Exception as e:
                await interaction.channel.send(f"```\nCh.{_lbl(ch_n)}  ─  Error: {e}\n```")

        await interaction.channel.send("```\n✓  Series range complete\n```")

    # ── manga_panel ────────────────────────────────────────────────────────
    @app_commands.command(name="manga_panel", description="لوحة تحكم متكاملة لتصفح وتحميل الفصول.")
    @app_commands.describe(url="الرابط الرئيسي للمانجا/المانهوا")
    @is_admin()
    async def manga_panel_cmd(self, interaction: discord.Interaction, url: str):
        await interaction.response.send_message(
            f"```yaml\n  Fetching chapters...\n  Site : {_domain(url)}\n```"
        )
        try:
            prov_name = self.provider_manager.get_provider_name(url)
            chs       = await self.provider_manager.get_all_chapters(url)
            if not chs:
                return await interaction.edit_original_response(
                    content=(
                        f"```yaml\n"
                        f"  Status   : FAILED\n"
                        f"  Site     : {_domain(url)}\n"
                        f"  Provider : {prov_name}\n"
                        f"  Error    : Could not extract chapters\n"
                        f"             Check the URL or try again later\n"
                        f"```"
                    )
                )

            view = MangaPanelView(
                self.bot, self.downloader, self.provider_manager,
                url, chs,
                requester=interaction.user,
                provider_name=prov_name,
            )
            em = view.build_embed(
                f"Fetched {len(chs)} chapters  ·  "
                f"Ch.{_lbl(min(chs))} → Ch.{_lbl(max(chs))}  ·  "
                f"Browse pages, select chapters, press Launch"
            )
            await interaction.edit_original_response(content=None, embed=em, view=view)
        except Exception as e:
            await interaction.edit_original_response(
                content=f"```yaml\n  Status : ERROR\n  Detail : {e}\n```"
            )


async def setup(bot):
    await bot.add_cog(RadarCog(bot))
