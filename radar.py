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
from user_system import owner_only, vip_only, get_rank

RADAR_CONCURRENT  = 5
CHAPTERS_PER_PAGE = 20
DL_CONCURRENT     = 3       # فصول تتحمّل بالتوازي في البانل

# ── ألوان ─────────────────────────────────────────────────────────────────
C_IDLE  = discord.Color.from_rgb(43, 45, 49)
C_RUN   = discord.Color.from_rgb(88, 101, 242)
C_DONE  = discord.Color.from_rgb(35, 165, 89)
C_FAIL  = discord.Color.from_rgb(242, 63, 66)
C_RADAR = discord.Color.from_rgb(114, 137, 218)
C_GREY  = discord.Color.from_rgb(148, 156, 164)
C_INFO  = discord.Color.from_rgb(0, 168, 252)

# ── أيقونات الحالة ─────────────────────────────────────────────────────────
ICO = {
    "idle":        "⬛",
    "selected":    "🟦",
    "locked":      "🔒",
    "queued":      "⏳",
    "downloading": "📥",
    "stitching":   "🧵",
    "uploading":   "📤",
    "done":        "✅",
    "failed":      "❌",
}

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
                f"❌  لم يُعثر على فصول.\nالمتاح: `{_lbl(min(nums))}` ← `{_lbl(max(nums))}`",
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
#  Modal — إعدادات SmartStitch
# ─────────────────────────────────────────────────────────────────────────
class StitchSettingsModal(ui.Modal, title="إعدادات SmartStitch"):
    width = ui.TextInput(
        label="عرض الصورة (px)",
        placeholder="800",
        default="800",
        min_length=2, max_length=5,
        required=True,
    )
    height = ui.TextInput(
        label="الحد الأقصى للارتفاع (px)",
        placeholder="14500",
        default="14500",
        min_length=3, max_length=6,
        required=True,
    )
    sensitivity = ui.TextInput(
        label="حساسية الدمج (1-100)",
        placeholder="90",
        default="90",
        min_length=1, max_length=3,
        required=True,
    )

    def __init__(self, panel: "MangaPanelView"):
        super().__init__()
        self.panel = panel
        self.width.default       = str(panel.stitch_width)
        self.height.default      = str(panel.stitch_height)
        self.sensitivity.default = str(panel.stitch_sensitivity)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            w = int(self.width.value.strip())
            h = int(self.height.value.strip())
            s = int(self.sensitivity.value.strip())
            if not (200 <= w <= 4000):
                raise ValueError("عرض غير صالح")
            if not (3000 <= h <= 50000):
                raise ValueError("ارتفاع غير صالح")
            if not (1 <= s <= 100):
                raise ValueError("حساسية غير صالحة")
            self.panel.stitch_width       = w
            self.panel.stitch_height      = h
            self.panel.stitch_sensitivity = s
            self.panel._rebuild()
            await interaction.response.edit_message(
                embed=self.panel.build_embed(
                    f"⚙️  SmartStitch  │  {w}px × {h}px  │  حساسية {s}%"
                ),
                view=self.panel,
            )
        except ValueError as e:
            await interaction.response.send_message(
                f"❌  قيم غير صالحة: {e}", ephemeral=True
            )


# ─────────────────────────────────────────────────────────────────────────
#  MangaPanelView — محسّن كلياً
# ─────────────────────────────────────────────────────────────────────────
class MangaPanelView(ui.View):

    def __init__(self, bot, downloader, provider_manager,
                 series_url, chapters_dict,
                 requester: discord.User = None,
                 provider_name: str = "Generic",
                 cover_url: str = None,
                 locked_chapters: set = None):
        super().__init__(timeout=1800)
        self.bot              = bot
        self.downloader       = downloader
        self.provider_manager = provider_manager
        self.series_url       = series_url
        self.requester        = requester
        self.provider_name    = provider_name
        self.cover_url        = cover_url
        self.locked_chapters  = locked_chapters or set()

        self.all_chapters : list[float] = sorted(chapters_dict.keys(), reverse=True)
        self.chapters_dict              = chapters_dict
        self.page                       = 0
        self.selected     : list[float] = []
        self.ch_status    : dict        = {}
        self.running                    = False

        # ── إعدادات SmartStitch ────────────────────────────────────────────
        self.stitch_enabled   : bool = True      # SmartStitch ON/OFF
        self.stitch_width     : int  = 800
        self.stitch_height    : int  = 14500
        self.stitch_sensitivity: int = 90

        # ── ترتيب الفصول ──────────────────────────────────────────────────
        self.sort_desc : bool = True   # True = تنازلي (أحدث أولاً)

        self._rebuild()

    # ── الترتيب ────────────────────────────────────────────────────────────
    def _apply_sort(self):
        self.all_chapters = sorted(
            self.all_chapters,
            reverse=self.sort_desc,
        )

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
            opts = []
            for n in chs:
                st       = self.ch_status.get(n, {})
                state    = st.get("state", "")
                is_done  = state == "done"
                in_sel   = n in sel_s
                is_locked = n in self.locked_chapters

                emoji = ICO.get(state, ICO["selected"] if in_sel else (ICO["locked"] if is_locked else ICO["idle"]))
                desc  = f"Ch. {_lbl(n)}"
                if is_done: desc += " (Ready)"
                elif in_sel: desc += " (Selected)"
                elif is_locked: desc += " (Paid/Locked)"

                opts.append(discord.SelectOption(
                    label=f"Chapter {_lbl(n)}",
                    value=str(n),
                    emoji=emoji,
                    description=desc,
                    default=in_sel,
                ))
            menu = ui.Select(
                placeholder=f"Select chapters (Page {self.page+1}/{self.total_pages})",
                min_values=1, max_values=len(opts),
                options=opts, row=0, disabled=self.running,
            )
            menu.callback = self._cb_select
            self.add_item(menu)

        # ── صف 1: تنقل ────────────────────────────────────────────────────
        d = self.running
        nav_row = [
            ("⏮️", self._cb_first, self.page == 0 or d),
            ("◀️", self._cb_prev,  self.page == 0 or d),
            (f"{self.page+1} / {self.total_pages}", None, True),
            ("▶️", self._cb_next, self.page >= self.total_pages - 1 or d),
            ("⏭️", self._cb_last, self.page >= self.total_pages - 1 or d),
        ]
        for label, cb, dis in nav_row:
            style = discord.ButtonStyle.secondary
            if cb is None:
                b = ui.Button(label=label, style=style, row=1, disabled=True)
            else:
                b = ui.Button(emoji=label, style=style, row=1, disabled=dis)
                b.callback = cb
            self.add_item(b)

        # ── صف 2: أدوات الاختيار ──────────────────────────────────────────
        tools = [
            ("Select Range", discord.ButtonStyle.primary, self._cb_range),
            ("Select All", discord.ButtonStyle.success, self._cb_pg),
            ("Clear All", discord.ButtonStyle.danger, self._cb_clear),
        ]
        for lbl, style, cb in tools:
            b = ui.Button(label=lbl, style=style, row=2, disabled=self.running)
            b.callback = cb; self.add_item(b)

        # ── صف 3: إعدادات ────────────────────────────────────────────────
        mode_lbl = "🧵 SmartStitch" if self.stitch_enabled else "⚡ ZIP Only"
        b_mode = ui.Button(label=mode_lbl, style=discord.ButtonStyle.secondary, row=3, disabled=self.running)
        b_mode.callback = self._cb_mode; self.add_item(b_mode)

        b_sett = ui.Button(emoji="⚙️", label="Settings", style=discord.ButtonStyle.secondary, row=3, disabled=self.running)
        b_sett.callback = self._cb_settings; self.add_item(b_sett)

        b_sort = ui.Button(label="Latest" if self.sort_desc else "Oldest", emoji="🔃", style=discord.ButtonStyle.secondary, row=3, disabled=self.running)
        b_sort.callback = self._cb_sort; self.add_item(b_sort)

        # ── صف 4: تنفيذ ──────────────────────────────────────────────────
        b_close = ui.Button(label="Close", style=discord.ButtonStyle.danger, emoji="❌", row=4, disabled=self.running)
        b_close.callback = self._cb_close; self.add_item(b_close)

        b_start = ui.Button(
            label=f"Confirm ({len(self.selected)})",
            style=discord.ButtonStyle.success, emoji="✅", row=4,
            disabled=self.running or not self.selected,
        )
        b_start.callback = self._cb_start; self.add_item(b_start)

    # ── بناء الـ Embed ─────────────────────────────────────────────────────
    def build_embed(self, note: str = None, color=None) -> discord.Embed:
        color  = color or (C_RUN if self.running else C_IDLE)
        series = _series_name(self.series_url)
        site   = _domain(self.series_url)
        selcnt = len(self.selected)
        total  = len(self.all_chapters)

        em = discord.Embed(title=series, url=self.series_url, color=color)
        if self.cover_url:
            em.set_image(url=self.cover_url)

        em.set_author(name="Manga Downloader", icon_url=self.bot.user.display_avatar.url)

        desc = (
            f"Please, choose not more than **25** chapters in one request.\n"
            f"Click the button below and input the range of indexes you may need.\n"
            f"*Important note: Index column **the left one**, always check the index of chapters you may need.*\n"
            f"Example: «1-3, 10, 15-16» will download chapters with indexes 1,2,3,10,15,16.\n"
            f"─────────────────────────────────────────"
        )
        em.description = desc

        # عرض الفصول بشكل مرتب
        chs = self.page_chs
        sel_s = set(self.selected)
        ch_list = []
        for n in chs:
            is_locked = n in self.locked_chapters
            in_sel    = n in sel_s
            state     = self.ch_status.get(n, {}).get("state", "")

            ico = ICO.get(state, ICO["selected"] if in_sel else (ICO["locked"] if is_locked else "[ ]"))
            if ico == ICO["idle"]: ico = "[ ]"

            idx = self.all_chapters.index(n) + 1
            line = f"{ico} {idx}. Chapter {_lbl(n)}"
            if is_locked: line += " 🔒"
            ch_list.append(line)

        if ch_list:
            em.add_field(name="Chapters", value=f"```\n{chr(10).join(ch_list)}\n```", inline=False)

        # ── download queue ─────────────────────────────────────────────────
        if self.running:
            lines    = []
            running_ = [n for n in self.selected
                        if self.ch_status.get(n, {}).get("state") in
                        ("downloading", "stitching", "uploading")]
            queued_  = [n for n in self.selected
                        if self.ch_status.get(n, {}).get("state") == "queued"]
            done_n   = sum(1 for n in self.selected
                           if self.ch_status.get(n, {}).get("state") == "done")
            fail_n   = sum(1 for n in self.selected
                           if self.ch_status.get(n, {}).get("state") == "failed")

            for n in sorted(self.selected):
                st    = self.ch_status.get(n, {})
                state = st.get("state", "queued")
                pct   = st.get("progress", 0)
                prov  = st.get("provider", "")
                link  = st.get("link", "")
                ico   = ICO.get(state, "⏳")
                lbl   = _lbl(n)

                if state == "done":
                    line = (f"`✅` **Ch.{lbl}**  ─  {prov}  [↗]({link})"
                            if link else f"`✅` **Ch.{lbl}**")
                elif state == "failed":
                    line = f"`❌` **Ch.{lbl}**  ─  {st.get('detail','فشل')[:35]}"
                elif state in ("downloading", "uploading"):
                    bar  = pbar(pct, 12)
                    line = f"`{ico}` **Ch.{lbl}**  `{bar}`  {prov}"
                elif state == "stitching":
                    line = f"`🧵` **Ch.{lbl}**  SmartStitch..."
                else:
                    line = f"`⏳` **Ch.{lbl}**  Waiting..."
                lines.append(line)

            summary = (
                f"⚡ **{len(running_)} Downloading**  "
                f"│  ⏳ {len(queued_)} Queued  "
                f"│  ✅ {done_n}  │  ❌ {fail_n}"
            )
            chunk = lines[:10]
            if len(lines) > 10:
                chunk.append(f"*... and {len(lines)-10} more*")
            em.add_field(
                name=f"⚡ Processing Queue",
                value=summary + "\n" + "\n".join(chunk),
                inline=False,
            )

        # ── روابط جاهزة ───────────────────────────────────────────────────
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
            em.add_field(name="🔗 Ready Links", value=lnks, inline=False)

        if note:
            em.add_field(name="Note", value=f"```fix\n{note}\n```", inline=False)

        em.set_footer(text=f"Page {self.page+1}/{self.total_pages} | Selected: {selcnt}/{total} | {site}")
        return em

    # ── navigation callbacks ──────────────────────────────────────────────
    async def _cb_select(self, interaction: discord.Interaction):
        chosen = {float(v) for v in interaction.data["values"]}
        page_s = set(self.page_chs)
        others = {n for n in self.selected if n not in page_s}
        self.selected = sorted(others | chosen, reverse=self.sort_desc)
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

    # ── quick-select ──────────────────────────────────────────────────────
    async def _cb_l1(self, i):
        self.selected = self.all_chapters[:1]; self._rebuild()
        await i.response.edit_message(
            embed=self.build_embed(f"⭐  آخر فصل  ─  Ch.{_lbl(self.selected[0])}"), view=self)

    async def _cb_l5(self, i):
        self.selected = list(self.all_chapters[:5]); self._rebuild()
        await i.response.edit_message(embed=self.build_embed("📦  آخر 5 فصول"), view=self)

    async def _cb_l10(self, i):
        self.selected = list(self.all_chapters[:10]); self._rebuild()
        await i.response.edit_message(embed=self.build_embed("🔟  آخر 10 فصول"), view=self)

    async def _cb_pg(self, i):
        pg  = set(self.page_chs)
        oth = {n for n in self.selected if n not in pg}
        self.selected = sorted(oth | pg, reverse=self.sort_desc); self._rebuild()
        await i.response.edit_message(
            embed=self.build_embed(f"📄  أُضيفت كل فصول الصفحة ({len(self.page_chs)})"), view=self)

    async def _cb_sort(self, i):
        self.sort_desc = not self.sort_desc
        self._apply_sort()
        # إعادة ترتيب المحدود بنفس الاتجاه
        self.selected = sorted(self.selected, reverse=self.sort_desc)
        self.page     = 0
        self._rebuild()
        lbl = "تنازلي (أحدث أولاً)" if self.sort_desc else "تصاعدي (أقدم أولاً)"
        await i.response.edit_message(
            embed=self.build_embed(f"🔀  الترتيب: {lbl}"), view=self)

    async def _cb_range(self, i):
        await i.response.send_modal(RangeModal(self))

    async def _cb_settings(self, i):
        if not self.stitch_enabled:
            return await i.response.send_message(
                "⚠️  تفعّل وضع SmartStitch أولاً لتغيير الإعدادات.", ephemeral=True)
        await i.response.send_modal(StitchSettingsModal(self))

    async def _cb_mode(self, i):
        self.stitch_enabled = not self.stitch_enabled
        mode = "SmartStitch ✓" if self.stitch_enabled else "ZIP فقط (بلا دمج)"
        self._rebuild()
        await i.response.edit_message(
            embed=self.build_embed(f"⚡  الوضع: {mode}"), view=self)

    async def _cb_clear(self, i):
        self.selected = []; self.ch_status = {}; self._rebuild()
        await i.response.edit_message(embed=self.build_embed("🗑  مُسح الاختيار"), view=self)

    async def _cb_close(self, i):
        for item in self.children:
            item.disabled = True
        await i.response.edit_message(
            embed=self.build_embed("✖  اللوحة مغلقة", color=C_GREY), view=self)
        self.stop()

    async def _cb_retry(self, i):
        """إعادة المحاولة للفصول الفاشلة."""
        failed = [n for n, v in self.ch_status.items() if v.get("state") == "failed"]
        if not failed:
            return await i.response.send_message("لا توجد فصول فاشلة.", ephemeral=True)
        # أعد تعيين الفاشلة لـ queued
        for n in failed:
            self.ch_status[n] = {"state": "queued"}
        # ضعها في المحدد
        self.selected = sorted(
            set(self.selected) | set(failed), reverse=self.sort_desc
        )
        self._rebuild()
        await i.response.edit_message(
            embed=self.build_embed(f"🔄  إعادة {len(failed)} فصل فاشل..."), view=self)
        # ابدأ التحميل
        await self._run_downloads(i.message, failed)

    # ── start download ─────────────────────────────────────────────────────
    async def _cb_start(self, interaction: discord.Interaction):
        if self.running:
            return await interaction.response.send_message("⚠️ عملية جارية.", ephemeral=True)
        if not self.selected:
            return await interaction.response.send_message(
                "❗ اختر فصولاً أولاً.", ephemeral=True)

        to_dl = sorted(self.selected, reverse=self.sort_desc)
        for n in to_dl:
            if self.ch_status.get(n, {}).get("state") != "done":
                self.ch_status[n] = {"state": "queued"}

        self.running = True
        self._rebuild()
        await interaction.response.edit_message(
            embed=self.build_embed(
                f"🚀 بدء تحميل {len(to_dl)} فصل  ·  توازي×{DL_CONCURRENT}",
                color=C_RUN,
            ),
            view=self,
        )
        await self._run_downloads(interaction.message, to_dl)

    # ── منطق التحميل المتوازي ─────────────────────────────────────────────
    async def _run_downloads(self, panel_msg: discord.Message, to_dl: list):
        self.running  = True
        sem           = asyncio.Semaphore(DL_CONCURRENT)
        last_edit_ts  = 0.0
        edit_lock     = asyncio.Lock()

        async def _safe_edit(note=None, col=None):
            nonlocal last_edit_ts
            async with edit_lock:
                now = asyncio.get_running_loop().time()
                if now - last_edit_ts < 1.8:
                    return
                last_edit_ts = now
                try:
                    await panel_msg.edit(embed=self.build_embed(note, color=col))
                except Exception:
                    pass

        async def _dl_one(num: float):
            url = self.chapters_dict[num]
            lbl = _lbl(num)

            async def pcb(cur, tot, txt, _n=num, _l=lbl):
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
                await _safe_edit(f"Ch.{_l}  {txt}")

            fp = None
            async with sem:
                if self.ch_status.get(num, {}).get("state") == "done":
                    return
                self.ch_status[num] = {"state": "downloading", "progress": 0}
                await _safe_edit(f"↓ Ch.{lbl}  بدأ التحميل...")

                try:
                    if self.stitch_enabled:
                        fp = await self.downloader.download_and_stitch(
                            url, f"Ch_{lbl}",
                            target_height=self.stitch_height,
                            target_width=self.stitch_width,
                            sensitivity=self.stitch_sensitivity,
                            progress_callback=pcb,
                        )
                    else:
                        fp = await self.downloader.download_chapter(
                            url, f"Ch_{lbl}", progress_callback=pcb,
                        )

                    if not fp:
                        self.ch_status[num] = {"state": "failed", "detail": "فشل جلب الصور"}
                        await _safe_edit(f"✗ Ch.{lbl}  فشل التحميل", col=C_FAIL)
                        return

                    link = prov = None
                    for pname, pfn in [
                        ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=pcb)),
                        ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=pcb)),
                    ]:
                        self.ch_status[num].update(
                            {"state": "uploading", "provider": pname, "progress": 0}
                        )
                        await _safe_edit(f"↑ Ch.{lbl}  رفع → {pname}...")
                        link = await pfn(fp)
                        if link:
                            prov = pname
                            break

                    if link:
                        self.ch_status[num] = {
                            "state": "done", "progress": 100,
                            "provider": prov, "link": link,
                        }
                        await _safe_edit(f"✓ Ch.{lbl}  {prov}", col=C_DONE)
                    else:
                        self.ch_status[num] = {
                            "state": "failed", "detail": "Gofile & Catbox failed"
                        }
                        await _safe_edit(f"✗ Ch.{lbl}  رفع فاشل", col=C_FAIL)

                except Exception as e:
                    self.ch_status[num] = {"state": "failed", "detail": str(e)[:80]}
                    await _safe_edit(f"✗ Ch.{lbl}  خطأ: {e}", col=C_FAIL)
                finally:
                    if fp:
                        self.downloader.cleanup(fp)

        await asyncio.gather(*[_dl_one(n) for n in to_dl])

        # ── انتهى التحميل ──────────────────────────────────────────────────
        self.running = False
        done_list = [
            (n, self.ch_status[n]) for n in sorted(to_dl)
            if self.ch_status.get(n, {}).get("state") == "done"
        ]
        fail_list = [
            n for n in sorted(to_dl)
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

        if done_list:
            mention = self.requester.mention if self.requester else ""
            series  = _series_name(self.series_url)
            summary = discord.Embed(
                title="📦  Download Complete",
                color=fc,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            mode_used = "SmartStitch" if self.stitch_enabled else "ZIP only"
            summary.description = (
                f"```yaml\n"
                f"  Series  : {series}\n"
                f"  Mode    : {mode_used}\n"
                f"  Done    : {len(done_list)}"
                + (f"  │  Failed: {len(fail_list)}" if fail_list else "") + "\n"
                f"  Site    : {_domain(self.series_url)}\n"
                f"```"
                + ("\n**Failed:** " + ", ".join(f"Ch.{_lbl(n)}" for n in fail_list)
                   if fail_list else "")
            )
            links_txt = "\n".join(
                f"[**Ch.{_lbl(n)}**  ─  {d.get('provider','')}]({d['link']})"
                for n, d in done_list
            )
            summary.add_field(name="🔗  Download Links", value=links_txt[:1020], inline=False)
            summary.set_footer(text="Cat-Bi  ·  Manga System")
            await panel_msg.channel.send(content=mention, embed=summary)

        self.stop()


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

    @tasks.loop(minutes=10)
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
                last_dt = datetime.datetime.fromisoformat(last_str)
                if (now - last_dt) >= datetime.timedelta(hours=interval):
                    due.append(row)
            except Exception:
                due.append(row)
        if not due:
            return

        print(f"[Radar] Checking {len(due)} trackers...")
        sem = asyncio.Semaphore(RADAR_CONCURRENT)

        async def check_one(row):
            tid, gid, cid, url, last_ch, msg, interval, _, dl_en = row
            async with sem:
                try:
                    # استخدام get_all_chapters للحصول على أدق نتائج
                    all_chs = await self.provider_manager.get_all_chapters(url)
                    if not all_chs:
                        await database.update_tracker_time(tid, now.isoformat())
                        return

                    latest = max(all_chs.keys())
                    if latest <= last_ch:
                        await database.update_tracker_time(tid, now.isoformat())
                        return

                    new_chapters = sorted([n for n in all_chs.keys() if n > last_ch])

                    for ch_num in new_chapters:
                        ch_url = all_chs[ch_num]
                        print(f"[Radar] ✅ Found Ch.{ch_num} for {url}")

                        dl_link = None
                        if dl_en:
                            zp = await self.downloader.download_and_stitch(ch_url, f"Ch_{ch_num}")
                            if zp:
                                dl_link = (
                                    await self.downloader.upload_to_gofile(zp)
                                    or await self.downloader.upload_to_catbox(zp)
                                )
                                self.downloader.cleanup(zp)

                        ch = self.bot.get_channel(cid)
                        if ch:
                            em = discord.Embed(
                                title="🚨 New Chapter Released!",
                                description=(
                                    f"**{_series_name(url)}**\n"
                                    f"**Chapter {_lbl(ch_num)}** is now out!\n"
                                    f"[🔗 Read here]({ch_url})"
                                ),
                                color=C_DONE, timestamp=now,
                            )
                            if dl_link:
                                em.add_field(name="📥 Download", value=f"[Download ZIP]({dl_link})", inline=False)
                            em.set_footer(text=f"Cat-Bi Radar • {_domain(url)}")
                            await ch.send(content=msg, embed=em)

                    await database.update_tracker_chapter(tid, latest, now.isoformat())
                except Exception as e:
                    print(f"[Radar] ❌ Error checking {url}: {e}")
                    await database.update_tracker_time(tid, now.isoformat())

        await asyncio.gather(*[check_one(r) for r in due])

    # ── أوامر ─────────────────────────────────────────────────────────────
    @app_commands.command(name="track_add", description="[Owner] إضافة عمل للرادار.")
    @app_commands.describe(url="رابط العمل", channel="روم الإشعارات",
                           custom_message="رسالة مرفقة", interval_hours="فحص كل كم ساعة",
                           current_chapter="الفصل الحالي", auto_download="تحميل تلقائي")
    @owner_only()
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

    @app_commands.command(name="track_list", description="[Owner] الأعمال المتتبعة.")
    @owner_only()
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

    @app_commands.command(name="track_remove", description="[Owner] إزالة متتبع.")
    @app_commands.describe(tracker_id="الـ ID من track_list")
    @owner_only()
    @app_commands.guild_only()
    async def track_remove_cmd(self, interaction: discord.Interaction, tracker_id: int):
        ok = await database.remove_tracker(tracker_id, interaction.guild_id)
        em = discord.Embed(
            title="✅  Removed" if ok else "❌  Not Found",
            description=f"Tracker `{tracker_id}`",
            color=C_DONE if ok else C_FAIL,
        )
        await interaction.response.send_message(embed=em, ephemeral=True)


    # ── manga_panel ────────────────────────────────────────────────────────
    @app_commands.command(name="manga_panel", description="[VIP] لوحة تحكم شاملة لتصفح وتحميل فصول المانجا")
    @app_commands.describe(url="رابط المانجا/المانهوا الرئيسي")
    @vip_only()
    async def manga_panel_cmd(self, interaction: discord.Interaction, url: str):
        # defer فوري لتجنب انتهاء صلاحية الـ interaction (3 ثواني)
        is_component = interaction.type == discord.InteractionType.component
        if not interaction.response.is_done():
            await interaction.response.defer()

        try:
            prov_name = self.provider_manager.get_provider_name(url)

            # جلب الفصول + صورة الغلاف بالتوازي
            chs_task   = self.provider_manager.get_chapters_with_lock_info(url)
            cover_task = self.provider_manager.get_series_cover(url)
            chs_rich, cover_url = await asyncio.gather(
                chs_task, cover_task, return_exceptions=True
            )

            if isinstance(chs_rich, Exception):
                chs_rich = {}
            if isinstance(cover_url, Exception):
                cover_url = None

            # فصل الـ URL عن معلومات الإقفال
            chs        = {}
            locked_set = set()
            for num, info in chs_rich.items():
                if isinstance(info, dict):
                    chs[num] = info["url"]
                    if info.get("locked"):
                        locked_set.add(num)
                else:
                    chs[num] = info

            if not chs:
                em_fail = discord.Embed(
                    title="❌ لم يُعثر على فصول",
                    description=(
                        f"```yaml\n"
                        f"  Site     : {_domain(url)}\n"
                        f"  Provider : {prov_name}\n"
                        f"  Error    : تعذّر جلب الفصول\n"
                        f"             تحقق من الرابط أو حاول لاحقاً\n"
                        f"```"
                    ),
                    color=C_FAIL,
                )
                return await interaction.followup.send(embed=em_fail, ephemeral=True)

            view = MangaPanelView(
                self.bot, self.downloader, self.provider_manager,
                url, chs,
                requester=interaction.user,
                provider_name=prov_name,
                cover_url=cover_url,
                locked_chapters=locked_set,
            )
            em = view.build_embed(
                f"✅ وُجد {len(chs)} فصل  ·  "
                f"Ch.{_lbl(min(chs))} → Ch.{_lbl(max(chs))}"
                + (f"  ·  🔒 {len(locked_set)} مدفوع" if locked_set else "")
            )
            await interaction.followup.send(embed=em, view=view)

        except Exception as e:
            try:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ خطأ",
                        description=f"```\n{str(e)[:500]}\n```",
                        color=C_FAIL,
                    ),
                    ephemeral=True,
                )
            except Exception:
                pass
            import traceback
            traceback.print_exc()


async def setup(bot):
    await bot.add_cog(RadarCog(bot))
