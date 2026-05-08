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
C_IDLE  = discord.Color.from_rgb(47,  49,  54)    # داكن محايد
C_RUN   = discord.Color.from_rgb(250, 166,  26)   # ذهبي نشط
C_DONE  = discord.Color.from_rgb(59,  165, 105)   # أخضر ناجح
C_FAIL  = discord.Color.from_rgb(237,  66,  69)   # أحمر فشل
C_RADAR = discord.Color.from_rgb(88,  101, 242)   # بنفسجي للرادار
C_GREY  = discord.Color.greyple()

# رموز الحالة
ST = {
    "queued":      "⏸️",
    "downloading": "📥",
    "stitching":   "🧵",
    "uploading":   "☁️",
    "done":        "✅",
    "failed":      "❌",
    "selected":    "🔵",
    "idle":        "◻️",
}


def _lbl(num) -> str:
    return str(int(num)) if float(num).is_integer() else str(num)

def _series_name(url: str) -> str:
    parts = [p for p in url.rstrip("/").split("/") if p]
    return parts[-1].replace("-", " ").replace("_", " ").title() if parts else "Manga"

def _bar(pct: int, length: int = 12) -> str:
    filled = int(round(pct / 100 * length))
    return "█" * filled + "░" * (length - filled)


# ─────────────────────────────────────────────────────────────────────────
#  Modal — اختيار نطاق الفصول
# ─────────────────────────────────────────────────────────────────────────
class RangeModal(ui.Modal, title="✏️  تحديد نطاق الفصول"):
    """
    أمثلة:
      80-100     → فصول 80 حتى 100
      1,5,10     → فصول محددة
      latest:10  → آخر 10 فصول
    """
    text = ui.TextInput(
        label="أدخل النطاق أو الفصول المطلوبة",
        placeholder="مثال:  80-100  |  1,5,10  |  latest:10",
        min_length=1, max_length=120,
        style=discord.TextStyle.short,
    )

    def __init__(self, panel: "MangaPanelView"):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction):
        raw  = self.text.value.strip()
        nums = set(self.panel.all_chapters)
        sel  : set[float] = set()

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
            await interaction.response.send_message(
                f"❌ لم يُعثر على فصول بهذه القيمة.\n"
                f"الفصول المتاحة: **{_lbl(min(nums))}** ← **{_lbl(max(nums))}**",
                ephemeral=True,
            )
            return

        existing = set(self.panel.selected)
        existing.update(sel)
        self.panel.selected = sorted(existing, reverse=True)

        # ── انتقل للصفحة التي تحتوي أعلى فصل محدد (الأحدث في الاختيار)
        first_sel = max(sel)
        self.panel.page = self.panel._page_for(first_sel)

        self.panel._rebuild()
        await interaction.response.edit_message(
            embed=self.panel.build_embed(
                f"✅  أُضيف **{len(sel)}** فصل  ·  "
                f"Ch.**{_lbl(min(sel))}** → Ch.**{_lbl(max(sel))}**"
            ),
            view=self.panel,
        )


# ─────────────────────────────────────────────────────────────────────────
#  MangaPanelView
# ─────────────────────────────────────────────────────────────────────────
class MangaPanelView(ui.View):

    def __init__(self, bot, downloader, provider_manager,
                 series_url, chapters_dict,
                 requester: discord.User = None):
        super().__init__(timeout=1800)
        self.bot              = bot
        self.downloader       = downloader
        self.provider_manager = provider_manager
        self.series_url       = series_url
        self.requester        = requester

        self.all_chapters : list[float] = sorted(chapters_dict.keys(), reverse=True)
        self.chapters_dict              = chapters_dict
        self.page                       = 0
        self.selected     : list[float] = []
        self.ch_status    : dict        = {}
        self.running                    = False

        self._rebuild()

    # ── helpers ───────────────────────────────────────────────────────────
    @property
    def total_pages(self) -> int:
        return max(1, (len(self.all_chapters) + CHAPTERS_PER_PAGE - 1) // CHAPTERS_PER_PAGE)

    @property
    def page_chs(self) -> list[float]:
        s = self.page * CHAPTERS_PER_PAGE
        return self.all_chapters[s: s + CHAPTERS_PER_PAGE]

    def _page_for(self, num: float) -> int:
        try:
            idx = self.all_chapters.index(num)
            return idx // CHAPTERS_PER_PAGE
        except ValueError:
            return 0

    # ── rebuild ───────────────────────────────────────────────────────────
    def _rebuild(self):
        self.clear_items()
        chs   = self.page_chs
        sel_s = set(self.selected)

        # ── صف 0: قائمة الاختيار ──────────────────────────────────────────
        if chs:
            opts = [
                discord.SelectOption(
                    label=f"الفصل  {_lbl(n)}",
                    value=str(n),
                    emoji=ST["done"] if self.ch_status.get(n, {}).get("state") == "done"
                          else (ST["selected"] if n in sel_s else ST["idle"]),
                    description=(
                        "✅ مكتمل" if self.ch_status.get(n, {}).get("state") == "done"
                        else ("محدد للتحميل" if n in sel_s else "اضغط للإضافة")
                    ),
                    default=(n in sel_s),
                )
                for n in chs
            ]
            menu = ui.Select(
                placeholder=f"📖  اختر فصولاً  —  {self.page+1}/{self.total_pages}",
                min_values=1, max_values=len(opts),
                options=opts, row=0,
                disabled=self.running,
            )
            menu.callback = self._cb_select
            self.add_item(menu)

        # ── صف 1: تنقل ────────────────────────────────────────────────────
        at_start = self.page == 0
        at_end   = self.page >= self.total_pages - 1
        dis      = self.running

        for emoji, cb, disabled in [
            ("⏮️", self._cb_first, at_start or dis),
            ("◀️", self._cb_prev,  at_start or dis),
        ]:
            b = ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary,
                          row=1, disabled=disabled)
            b.callback = cb
            self.add_item(b)

        self.add_item(ui.Button(
            label=f"  {self.page+1} / {self.total_pages}  ",
            style=discord.ButtonStyle.secondary,
            row=1, disabled=True,
        ))

        for emoji, cb, disabled in [
            ("▶️", self._cb_next, at_end or dis),
            ("⏭️", self._cb_last, at_end or dis),
        ]:
            b = ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary,
                          row=1, disabled=disabled)
            b.callback = cb
            self.add_item(b)

        # ── صف 2: اختيار سريع ────────────────────────────────────────────
        quick = [
            ("⭐", "آخر فصل",   discord.ButtonStyle.primary,   self._cb_l1),
            ("📦", "آخر 5",     discord.ButtonStyle.secondary,  self._cb_l5),
            ("📄", "الصفحة",    discord.ButtonStyle.secondary,  self._cb_page_all),
            ("✏️", "نطاق",     discord.ButtonStyle.secondary,  self._cb_range),
            ("🗑️", "مسح",      discord.ButtonStyle.danger,     self._cb_clear),
        ]
        for emoji, label, style, cb in quick:
            b = ui.Button(emoji=emoji, label=label, style=style, row=2, disabled=self.running)
            b.callback = cb
            self.add_item(b)

        # ── صف 3: تحكم ───────────────────────────────────────────────────
        b_start = ui.Button(
            emoji="🚀", label=f"  ابدأ التحميل  ({len(self.selected)})",
            style=discord.ButtonStyle.success, row=3, disabled=self.running,
        )
        b_start.callback = self._cb_start
        self.add_item(b_start)

        b_close = ui.Button(
            emoji="✖️", label="  إغلاق",
            style=discord.ButtonStyle.secondary, row=3, disabled=self.running,
        )
        b_close.callback = self._cb_close
        self.add_item(b_close)

    # ── embed ─────────────────────────────────────────────────────────────
    def build_embed(self, note: str = None, color=None) -> discord.Embed:
        color  = color or (C_RUN if self.running else C_IDLE)
        series = _series_name(self.series_url)
        sel_s  = set(self.selected)
        chs    = self.page_chs

        em = discord.Embed(color=color,
                           timestamp=datetime.datetime.now(datetime.timezone.utc))

        # ── header ────────────────────────────────────────────────────────
        status_line = (
            "⚙️  **جاري التحميل...**" if self.running
            else "📚  **لوحة تحكم المانجا**"
        )
        pct_sel = int(len(self.selected) / max(len(self.all_chapters), 1) * 100)
        em.title       = f"{series}"
        em.description = (
            f"{status_line}\n"
            f"```\n"
            f"📊 الفصول : {len(self.all_chapters):>5}   ☑️ محدد : {len(self.selected):>4}  ({pct_sel}%)\n"
            f"📄 الصفحة : {self.page+1:>5}/{self.total_pages:<4}   🔗 رابط : {self.series_url[:38]}\n"
            f"```"
        )

        # ── قائمة فصول الصفحة الحالية (شبكة مدمجة) ────────────────────────
        if chs:
            COLS = 5
            rows_txt = []
            row_buf  = []
            for n in chs:
                st    = self.ch_status.get(n, {})
                state = st.get("state", "")
                if state in ST:
                    icon = ST[state]
                elif n in sel_s:
                    icon = ST["selected"]
                else:
                    icon = ST["idle"]

                lbl_str = f"`{_lbl(n):>4}`"
                row_buf.append(f"{icon}{lbl_str}")
                if len(row_buf) == COLS:
                    rows_txt.append("  ".join(row_buf))
                    row_buf = []
            if row_buf:
                rows_txt.append("  ".join(row_buf))

            em.add_field(
                name=f"📋  فصول الصفحة {self.page+1}",
                value="\n".join(rows_txt),
                inline=False,
            )

        # ── قائمة التنفيذ (أثناء التحميل) ────────────────────────────────
        if self.running:
            active_lines = []
            for n in sorted(self.selected):
                st    = self.ch_status.get(n, {})
                state = st.get("state", "queued")
                pct   = st.get("progress", 0)
                prov  = st.get("provider", "")
                link  = st.get("link", "")
                icon  = ST.get(state, "⏸️")
                lbl_n = _lbl(n)

                if state == "done":
                    detail = f"[{prov}]({link})" if link else "✓"
                elif state == "failed":
                    detail = st.get("detail", "فشل")[:35]
                elif state in ("downloading", "uploading"):
                    detail = f"{_bar(pct)} {pct}%"
                elif state == "stitching":
                    detail = "SmartStitch..."
                else:
                    detail = "⏳"

                active_lines.append(f"{icon} **{lbl_n}**  {detail}")

            chunk = active_lines[:12]
            if len(active_lines) > 12:
                chunk.append(f"*+ {len(active_lines)-12} فصل آخر...*")
            em.add_field(name="⚡  قائمة التنفيذ", value="\n".join(chunk), inline=False)

        # ── روابط جاهزة ───────────────────────────────────────────────────
        ready = [
            (n, self.ch_status[n])
            for n in sorted(self.selected)
            if self.ch_status.get(n, {}).get("state") == "done"
            and self.ch_status[n].get("link")
        ]
        if ready and not self.running:
            links_txt = "  ·  ".join(
                f"[Ch.{_lbl(n)}]({d['link']})" for n, d in ready[:10]
            )
            em.add_field(name="🔗  روابط جاهزة", value=links_txt, inline=False)

        if note:
            em.add_field(name="", value=f"> 💬  {note}", inline=False)

        em.set_footer(text=f"Cat-Bi  ·  Gofile → Catbox  ·  صفحة {self.page+1}/{self.total_pages}")
        return em

    # ── callbacks التنقل ──────────────────────────────────────────────────
    async def _cb_select(self, interaction: discord.Interaction):
        chosen = {float(v) for v in interaction.data["values"]}
        page_s = set(self.page_chs)
        others = {n for n in self.selected if n not in page_s}
        self.selected = sorted(others | chosen, reverse=True)
        self._rebuild()
        await interaction.response.edit_message(
            embed=self.build_embed(f"☑️  محدد الآن: **{len(self.selected)}** فصل"),
            view=self,
        )

    async def _cb_first(self, i): self.page=0; self._rebuild(); await i.response.edit_message(embed=self.build_embed(), view=self)
    async def _cb_prev(self, i):  self.page=max(0,self.page-1); self._rebuild(); await i.response.edit_message(embed=self.build_embed(), view=self)
    async def _cb_next(self, i):  self.page=min(self.total_pages-1,self.page+1); self._rebuild(); await i.response.edit_message(embed=self.build_embed(), view=self)
    async def _cb_last(self, i):  self.page=self.total_pages-1; self._rebuild(); await i.response.edit_message(embed=self.build_embed(), view=self)

    async def _cb_l1(self, i):
        self.selected=self.all_chapters[:1]; self._rebuild()
        await i.response.edit_message(embed=self.build_embed(f"⭐  تم اختيار آخر فصل — Ch.**{_lbl(self.selected[0])}**"), view=self)

    async def _cb_l5(self, i):
        self.selected=self.all_chapters[:5]; self._rebuild()
        await i.response.edit_message(embed=self.build_embed(f"📦  تم اختيار آخر 5 فصول"), view=self)

    async def _cb_page_all(self, i):
        pg  = set(self.page_chs)
        oth = {n for n in self.selected if n not in pg}
        self.selected = sorted(oth | pg, reverse=True); self._rebuild()
        await i.response.edit_message(
            embed=self.build_embed(f"📄  أُضيفت كل فصول الصفحة ({len(self.page_chs)})"), view=self
        )

    async def _cb_range(self, i):
        await i.response.send_modal(RangeModal(self))

    async def _cb_clear(self, i):
        self.selected=[]; self.ch_status={}; self._rebuild()
        await i.response.edit_message(embed=self.build_embed("🗑️  تم مسح الاختيار"), view=self)

    async def _cb_close(self, i):
        for item in self.children: item.disabled=True
        await i.response.edit_message(embed=self.build_embed("🔒  تم إغلاق اللوحة", color=C_GREY), view=self)
        self.stop()

    # ── بدء التحميل ───────────────────────────────────────────────────────
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
                f"🚀  بدأ تحميل **{len(to_dl)}** فصل  ·  "
                f"Ch.**{_lbl(to_dl[0])}** ← Ch.**{_lbl(to_dl[-1])}**",
                color=C_RUN,
            ),
            view=self,
        )
        panel_msg = interaction.message

        for num in to_dl:
            url   = self.chapters_dict[num]
            lbl   = _lbl(num)
            self.ch_status[num] = {"state": "downloading", "progress": 0}
            last_edit            = 0.0

            async def pcb(cur, tot, txt, _n=num, _l=lbl):
                nonlocal last_edit
                pct   = min(100, int(cur * 100 / max(tot, 1)))
                state = "downloading"
                if any(k in txt for k in ("SmartStitch", "دمج", "🪡")):
                    state = "stitching"
                if "رفع" in txt or "☁️" in txt:
                    state = "uploading"
                prov = ("Gofile" if "Gofile" in txt
                        else "Catbox" if "Catbox" in txt else "")
                self.ch_status[_n].update({"state": state, "progress": pct, "provider": prov})
                now = asyncio.get_running_loop().time()
                if now - last_edit < 2.0 and pct < 100:
                    return
                last_edit = now
                try:
                    await panel_msg.edit(embed=self.build_embed(f"Ch.{_l}: {txt}"))
                except Exception:
                    pass

            fp = None
            try:
                fp = await self.downloader.download_and_stitch(url, f"Ch_{lbl}", progress_callback=pcb)
                if not fp:
                    self.ch_status[num] = {"state": "failed", "detail": "فشل جلب الصور"}
                    await panel_msg.edit(embed=self.build_embed(f"❌  Ch.{lbl}: فشل التحميل"))
                    continue

                link = prov = None
                for pname, pfn in [
                    ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=pcb)),
                    ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=pcb)),
                ]:
                    self.ch_status[num].update({"state": "uploading", "provider": pname, "progress": 0})
                    await panel_msg.edit(embed=self.build_embed(f"☁️  Ch.{lbl}  →  {pname}..."))
                    link = await pfn(fp)
                    if link:
                        prov = pname
                        break

                if link:
                    self.ch_status[num] = {"state": "done", "progress": 100,
                                           "provider": prov, "link": link}
                    await panel_msg.edit(embed=self.build_embed(
                        f"✅  Ch.{lbl}  جاهز عبر **{prov}**!", color=C_DONE
                    ))
                else:
                    self.ch_status[num] = {"state": "failed",
                                           "detail": "فشل Gofile و Catbox"}
                    await panel_msg.edit(embed=self.build_embed(
                        f"❌  Ch.{lbl}: فشل الرفع على الخدمتين", color=C_FAIL
                    ))

            except Exception as e:
                self.ch_status[num] = {"state": "failed", "detail": str(e)[:80]}
                await panel_msg.edit(embed=self.build_embed(f"❌  Ch.{lbl}: خطأ", color=C_FAIL))
            finally:
                if fp:
                    self.downloader.cleanup(fp)
            await asyncio.sleep(0.5)

        # ── انتهت كل الفصول ───────────────────────────────────────────────
        self.running = False
        done_list    = [(n, self.ch_status[n]) for n in sorted(self.selected)
                        if self.ch_status.get(n, {}).get("state") == "done"]
        fail_list    = [n for n in sorted(self.selected)
                        if self.ch_status.get(n, {}).get("state") == "failed"]
        fc = C_DONE if not fail_list else (C_FAIL if not done_list else C_RUN)
        self._rebuild()
        await panel_msg.edit(
            embed=self.build_embed(
                f"🏁  انتهت العملية  ·  ✅ {len(done_list)} نجح  ·  ❌ {len(fail_list)} فشل",
                color=fc,
            ),
            view=self,
        )

        # ── منشن واحد في الآخر مع كل الروابط ────────────────────────────
        if done_list:
            mention = self.requester.mention if self.requester else ""
            series  = _series_name(self.series_url)
            summary = discord.Embed(
                title="📦  اكتمل التحميل!",
                color=C_DONE,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            summary.description = (
                f"**العمل:** `{series}`\n"
                f"**الفصول المكتملة:** `{len(done_list)}`\n"
                f"{'⚠️ فشل: ' + ', '.join(f'Ch.{_lbl(n)}' for n in fail_list) if fail_list else '✅ جميع الفصول اكتملت بنجاح'}"
            )
            links_txt = "\n".join(
                f"[📥  Ch.{_lbl(n)}  —  {d.get('provider','')}]({d['link']})"
                for n, d in done_list
            )
            summary.add_field(name="🔗  روابط التحميل", value=links_txt[:1020], inline=False)
            summary.set_footer(text="Cat-Bi Manga System")
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
                    print(f"[Radar] ✅ فصل جديد {latest} → {url}")
                    dl_link = None
                    if dl_en:
                        ch_url = url
                        zp = await self.downloader.download_and_stitch(ch_url, f"Ch_{latest}")
                        if zp:
                            dl_link = (
                                await self.downloader.upload_to_gofile(zp)
                                or await self.downloader.upload_to_catbox(zp)
                            )
                            self.downloader.cleanup(zp)
                    ch = self.bot.get_channel(cid)
                    if ch:
                        em = discord.Embed(
                            title="🚨  فصل جديد!",
                            description=(
                                f"**الفصل {_lbl(latest)}** متاح الآن\n"
                                f"*(السابق: {_lbl(last_ch)})*\n\n"
                                f"[🔗 رابط الموقع]({url})"
                            ),
                            color=C_RADAR, timestamp=now,
                        )
                        if dl_link:
                            em.add_field(name="📥  تحميل مباشر", value=f"[اضغط هنا]({dl_link})", inline=False)
                        em.set_footer(text="Cat-Bi Radar")
                        await ch.send(content=msg, embed=em)
                    await database.update_tracker_chapter(tid, latest, now.isoformat())
                except Exception as e:
                    print(f"[Radar] ❌ {tid}: {e}")
                    await database.update_tracker_time(tid, now.isoformat())

        await asyncio.gather(*[check_one(r) for r in due])

    # ── أوامر الأدمن ──────────────────────────────────────────────────────
    @app_commands.command(name="track_add", description="[أدمن] إضافة عمل لرادار الفصول.")
    @app_commands.describe(url="رابط العمل", channel="روم الإشعارات",
                           custom_message="رسالة مرفقة (مثال: @everyone)",
                           interval_hours="فحص كل كم ساعة",
                           current_chapter="رقم الفصل الحالي",
                           auto_download="تحميل ورفع تلقائي")
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
        em = discord.Embed(title="📡  تم تفعيل الرادار!", color=C_RADAR,
                           description=(
                               f"**الرابط:** {url}\n**الروم:** {channel.mention}\n"
                               f"**الفصل الحالي:** `{_lbl(current_chapter)}`\n"
                               f"**فحص كل:** `{interval_hours}h`\n"
                               f"**تحميل تلقائي:** {'✅' if auto_download else '❌'}"
                           ))
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="track_list", description="[أدمن] الأعمال المتتبعة.")
    @is_admin()
    @app_commands.guild_only()
    async def track_list_cmd(self, interaction: discord.Interaction):
        rows = [r for r in await database.get_all_trackers() if r[1] == interaction.guild_id]
        if not rows:
            return await interaction.response.send_message("لا توجد أعمال مُتابَعة.", ephemeral=True)
        em = discord.Embed(title="📡  قائمة الرادار", color=C_RADAR,
                           timestamp=datetime.datetime.now(datetime.timezone.utc))
        desc = ""
        for tid, gid, cid, url, lch, msg, interval, _, dl in rows:
            ch   = self.bot.get_channel(cid)
            name = ch.mention if ch else "محذوف"
            desc += (f"**`ID:{tid}`** — **{_series_name(url)}**\n"
                     f"↳ {name} | Ch.{_lbl(lch)} | كل {interval}h | تحميل:{'✅' if dl else '❌'}\n\n")
        em.description = desc[:3900]
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="track_remove", description="[أدمن] إزالة متتبع بالـ ID.")
    @app_commands.describe(tracker_id="الـ ID من track_list")
    @is_admin()
    @app_commands.guild_only()
    async def track_remove_cmd(self, interaction: discord.Interaction, tracker_id: int):
        ok = await database.remove_tracker(tracker_id, interaction.guild_id)
        em = discord.Embed(
            title="✅  تمت الإزالة" if ok else "❌  لم يُعثر عليه",
            description=f"الرادار `{tracker_id}`" if ok else "تأكد من الـ ID.",
            color=C_DONE if ok else C_FAIL,
        )
        await interaction.response.send_message(embed=em, ephemeral=True)

    # ── تحميل فصل واحد ────────────────────────────────────────────────────
    @app_commands.command(name="download_chapter", description="تحميل فصل برابط مباشر (ZIP).")
    @app_commands.describe(url="رابط الفصل")
    @is_admin()
    async def dl_chapter_cmd(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()
        msg = await interaction.followup.send("⏳  جاري التجهيز...")

        async def pcb(cur, tot, txt):
            try:
                await msg.edit(content=f"⏳  **{txt}**\n{self.downloader.create_progress_bar(cur,tot)}")
            except Exception:
                pass

        try:
            ttl = f"Manual_{url.rstrip('/').split('/')[-2]}"
            fp  = await self.downloader.download_and_stitch(url, ttl, progress_callback=pcb)
            if not fp:
                return await msg.edit(content="❌  فشل تحميل الصور.")
            link = prov = None
            for pname, pfn in [
                ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=pcb)),
                ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=pcb)),
            ]:
                await pcb(0, 1, f"☁️  رفع إلى {pname}...")
                link = await pfn(fp)
                if link:
                    prov = pname
                    break
            self.downloader.cleanup(fp)
            if link:
                em = discord.Embed(
                    title="✅  الفصل جاهز (ZIP)",
                    description=f"**المزود:** {prov}\n[📥  اضغط هنا]({link})",
                    color=C_DONE, timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                await msg.edit(content=None, embed=em)
            else:
                await msg.edit(content="❌  فشل الرفع على Gofile و Catbox.")
        except Exception as e:
            await msg.edit(content=f"❌  خطأ: {e}")

    # ── تحميل نطاق ────────────────────────────────────────────────────────
    @app_commands.command(name="download_range", description="تحميل نطاق فصول — ضع {num} مكان رقم الفصل.")
    @app_commands.describe(base_url="رابط مع {num}", start_ch="أول فصل", end_ch="آخر فصل")
    @is_admin()
    async def dl_range_cmd(self, interaction: discord.Interaction,
                           base_url: str, start_ch: int, end_ch: int):
        if "{num}" not in base_url:
            return await interaction.response.send_message("❌ الرابط يجب أن يحتوي `{num}`.", ephemeral=True)
        if end_ch < start_ch or (end_ch - start_ch) > 20:
            return await interaction.response.send_message("❌ النطاق غير صالح (الحد 20 فصل).", ephemeral=True)
        await interaction.response.send_message(f"⏳  بدء تحميل Ch.{start_ch} ← Ch.{end_ch}")

        for ch in range(start_ch, end_ch + 1):
            url  = base_url.replace("{num}", str(ch))
            smsg = await interaction.channel.send(f"⏳  **Ch.{ch}:** جاري...")
            await asyncio.sleep(2)

            async def rcb(cur, tot, txt, _s=smsg, _c=ch):
                try:
                    await _s.edit(content=f"⏳  **Ch.{_c}:** {txt}\n{self.downloader.create_progress_bar(cur,tot)}")
                except Exception:
                    pass

            try:
                fp = await self.downloader.download_and_stitch(url, f"Ch_{ch}", progress_callback=rcb)
                if not fp:
                    await smsg.edit(content=f"❌  **Ch.{ch}:** فشل."); continue
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
                        description=f"**{prov}**\n[📥  تحميل]({link})",
                        color=C_DONE,
                    ))
                else:
                    await smsg.edit(content=f"❌  **Ch.{ch}:** فشل الرفع.")
            except Exception as e:
                await interaction.channel.send(f"❌  **Ch.{ch}:** {e}")

        await interaction.channel.send("🏁  **اكتمل النطاق.**")

    # ── تحميل سلسلة ────────────────────────────────────────────────────────
    @app_commands.command(name="download_series", description="استخراج ذكي للسلسلة ثم تحميل النطاق.")
    @app_commands.describe(series_url="رابط صفحة المانجا", start_ch="أول فصل", end_ch="آخر فصل")
    @is_admin()
    async def dl_series_cmd(self, interaction: discord.Interaction,
                            series_url: str, start_ch: float, end_ch: float):
        if end_ch < start_ch or (end_ch - start_ch) > 20:
            return await interaction.response.send_message("❌ النطاق غير صالح (الحد 20).", ephemeral=True)
        await interaction.response.send_message("🔍  جاري تحليل الصفحة...")
        chs = await self.provider_manager.get_all_chapters(series_url)
        if not chs:
            return await interaction.channel.send("❌  فشل استخراج الفصول.")
        target = {n: u for n, u in chs.items() if start_ch <= n <= end_ch}
        if not target:
            return await interaction.channel.send(
                f"❌  لا فصول في هذا النطاق.\n"
                f"المتاح: Ch.**{_lbl(min(chs))}** ← Ch.**{_lbl(max(chs))}**"
            )
        await interaction.channel.send(f"⏳  **{len(target)} فصل للتحميل...**")

        for ch_n, url in sorted(target.items()):
            smsg = await interaction.channel.send(f"⏳  **Ch.{_lbl(ch_n)}:** جاري...")
            await asyncio.sleep(2)

            async def scb(cur, tot, txt, _s=smsg, _n=ch_n):
                try:
                    await _s.edit(content=f"⏳  **Ch.{_lbl(_n)}:** {txt}\n{self.downloader.create_progress_bar(cur,tot)}")
                except Exception:
                    pass

            try:
                fp = await self.downloader.download_and_stitch(url, f"Ch_{ch_n}", progress_callback=scb)
                if not fp:
                    await smsg.edit(content=f"❌  **Ch.{_lbl(ch_n)}:** فشل."); continue
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
                        description=f"**{prov}**\n[📥  تحميل]({link})",
                        color=C_DONE,
                    ))
                else:
                    await smsg.edit(content=f"❌  **Ch.{_lbl(ch_n)}:** فشل الرفع.")
            except Exception as e:
                await interaction.channel.send(f"❌  **Ch.{_lbl(ch_n)}:** {e}")

        await interaction.channel.send("🏁  **اكتملت السلسلة.**")

    # ── لوحة التحكم ────────────────────────────────────────────────────────
    @app_commands.command(name="manga_panel", description="لوحة تحكم للتصفح الكامل وتحميل الفصول.")
    @app_commands.describe(url="الرابط الرئيسي للمانجا/المانهوا")
    @is_admin()
    async def manga_panel_cmd(self, interaction: discord.Interaction, url: str):
        await interaction.response.send_message("🔍  جاري جلب قائمة الفصول...")
        try:
            chs = await self.provider_manager.get_all_chapters(url)
            if not chs:
                return await interaction.edit_original_response(
                    content="❌  فشل استخراج الفصول — تأكد من الرابط أو جرب لاحقاً."
                )
            view = MangaPanelView(
                self.bot, self.downloader, self.provider_manager,
                url, chs, requester=interaction.user,
            )
            em = view.build_embed(
                f"✅  تم جلب **{len(chs)}** فصل  ·  "
                f"Ch.**{_lbl(min(chs))}** → Ch.**{_lbl(max(chs))}**\n"
                f"تصفح الصفحات ← اختر الفصول ← اضغط 🚀"
            )
            await interaction.edit_original_response(content=None, embed=em, view=view)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌  خطأ: {e}")


async def setup(bot):
    await bot.add_cog(RadarCog(bot))
