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
CHAPTERS_PER_PAGE = 20          # فصول في كل صفحة (20 يعطي مساحة للـ embed)

# ── ألوان ─────────────────────────────────────────────────────────────────
C_IDLE    = discord.Color.from_rgb(88,  101, 242)
C_RUN     = discord.Color.from_rgb(255, 184,   0)
C_DONE    = discord.Color.from_rgb(87,  242, 135)
C_FAIL    = discord.Color.from_rgb(237,  66,  69)
C_RADAR   = discord.Color.from_rgb(32,  178, 170)
C_GREY    = discord.Color.greyple()


# ── مساعدات ───────────────────────────────────────────────────────────────
def _lbl(num) -> str:
    return str(int(num)) if float(num).is_integer() else str(num)

def _series_name(url: str) -> str:
    parts = [p for p in url.rstrip("/").split("/") if p]
    return parts[-1].replace("-", " ").replace("_", " ").title() if parts else "Manga"


# ─────────────────────────────────────────────────────────────────────────
#  Modal — اختيار نطاق الفصول
# ─────────────────────────────────────────────────────────────────────────
class RangeModal(ui.Modal, title="تحديد نطاق الفصول"):
    """
    المستخدم يكتب مثلاً:
      150-200     → فصول من 150 إلى 200
      1,5,10,50   → فصول محددة
      latest:10   → آخر 10 فصول
    """
    range_input = ui.TextInput(
        label="أدخل النطاق أو الفصول",
        placeholder="مثال: 150-200  أو  1,5,10  أو  latest:10",
        min_length=1,
        max_length=100,
    )

    def __init__(self, panel: "MangaPanelView"):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction):
        raw   = self.range_input.value.strip()
        nums  = set(self.panel.all_chapters)
        sel   = set()

        try:
            # latest:N
            if raw.lower().startswith("latest:"):
                n = int(raw.split(":")[1])
                sel = set(self.panel.all_chapters[:n])

            # range  A-B
            elif "-" in raw and "," not in raw:
                parts = raw.split("-")
                lo, hi = float(parts[0]), float(parts[1])
                sel = {n for n in nums if lo <= n <= hi}

            # قائمة مفصولة بفواصل
            else:
                for tok in raw.replace(" ", "").split(","):
                    try:
                        sel.add(float(tok))
                    except ValueError:
                        pass
                sel &= nums          # احتفظ فقط بما يوجد فعلاً
        except Exception:
            pass

        if not sel:
            await interaction.response.send_message(
                "❌ لم يُعثر على فصول بهذا النطاق، تأكد من الصيغة.", ephemeral=True
            )
            return

        # دمج مع الاختيار الحالي
        existing = set(self.panel.selected)
        existing.update(sel)
        self.panel.selected = sorted(existing, reverse=True)
        self.panel._rebuild()
        await interaction.response.edit_message(
            embed=self.panel.build_embed(f"✅ تم إضافة {len(sel)} فصل من النطاق."),
            view=self.panel
        )


# ─────────────────────────────────────────────────────────────────────────
#  MangaPanelView — اللوحة الرئيسية
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

        # ترتيب تنازلي (الأحدث أولاً)
        self.all_chapters  : list[float] = sorted(chapters_dict.keys(), reverse=True)
        self.chapters_dict = chapters_dict

        self.page          = 0
        self.selected      : list[float] = []
        self.ch_status     : dict        = {}
        self.running       = False

        self._rebuild()

    # ── صفحات ─────────────────────────────────────────────────────────────
    @property
    def total_pages(self) -> int:
        return max(1, (len(self.all_chapters) + CHAPTERS_PER_PAGE - 1) // CHAPTERS_PER_PAGE)

    @property
    def page_chs(self) -> list[float]:
        s = self.page * CHAPTERS_PER_PAGE
        return self.all_chapters[s: s + CHAPTERS_PER_PAGE]

    # ── بناء كل العناصر ───────────────────────────────────────────────────
    def _rebuild(self):
        self.clear_items()

        chs   = self.page_chs
        sel_s = set(self.selected)

        # ── صف 0: قائمة الاختيار ─────────────────────────────────────────
        if chs:
            opts = [
                discord.SelectOption(
                    label=f"Ch.{_lbl(n)}",
                    value=str(n),
                    emoji="✅" if n in sel_s else "🔲",
                    description="محدد" if n in sel_s else "اضغط للإضافة",
                    default=(n in sel_s),
                )
                for n in chs
            ]
            sel = ui.Select(
                placeholder=f"📖  صفحة {self.page+1}/{self.total_pages}  —  اختر فصولاً",
                min_values=1,
                max_values=len(opts),
                options=opts,
                row=0,
                disabled=self.running,
            )
            sel.callback = self._cb_select
            self.add_item(sel)

        # ── صف 1: تنقل الصفحات ───────────────────────────────────────────
        nav_dis = self.running

        # ⏮ أول صفحة
        btn_first = ui.Button(emoji="⏮️", style=discord.ButtonStyle.secondary,
                              row=1, disabled=(self.page == 0 or nav_dis),
                              custom_id="nav_first")
        btn_first.callback = self._cb_first
        self.add_item(btn_first)

        # ◀ سابق
        btn_prev = ui.Button(emoji="◀️", style=discord.ButtonStyle.secondary,
                             row=1, disabled=(self.page == 0 or nav_dis),
                             custom_id="nav_prev")
        btn_prev.callback = self._cb_prev
        self.add_item(btn_prev)

        # [n/total] — مؤشر مُعطَّل
        self.add_item(ui.Button(
            label=f"{self.page+1} / {self.total_pages}",
            style=discord.ButtonStyle.secondary,
            row=1, disabled=True, custom_id="nav_info"
        ))

        # ▶ تالي
        btn_next = ui.Button(emoji="▶️", style=discord.ButtonStyle.secondary,
                             row=1, disabled=(self.page >= self.total_pages - 1 or nav_dis),
                             custom_id="nav_next")
        btn_next.callback = self._cb_next
        self.add_item(btn_next)

        # ⏭ آخر صفحة
        btn_last = ui.Button(emoji="⏭️", style=discord.ButtonStyle.secondary,
                             row=1, disabled=(self.page >= self.total_pages - 1 or nav_dis),
                             custom_id="nav_last")
        btn_last.callback = self._cb_last
        self.add_item(btn_last)

        # ── صف 2: اختيار سريع ────────────────────────────────────────────
        b_l1 = ui.Button(label="⭐ آخر فصل", style=discord.ButtonStyle.primary,
                         row=2, disabled=self.running, custom_id="qs_l1")
        b_l1.callback = self._cb_l1
        self.add_item(b_l1)

        b_l5 = ui.Button(label="📦 آخر 5", style=discord.ButtonStyle.secondary,
                         row=2, disabled=self.running, custom_id="qs_l5")
        b_l5.callback = self._cb_l5
        self.add_item(b_l5)

        b_pg = ui.Button(label="📄 الصفحة", style=discord.ButtonStyle.secondary,
                         row=2, disabled=self.running, custom_id="qs_pg")
        b_pg.callback = self._cb_page_all
        self.add_item(b_pg)

        b_rng = ui.Button(label="✏️ نطاق", style=discord.ButtonStyle.secondary,
                          row=2, disabled=self.running, custom_id="qs_range")
        b_rng.callback = self._cb_range
        self.add_item(b_rng)

        b_clr = ui.Button(label="🧹 مسح", style=discord.ButtonStyle.danger,
                          row=2, disabled=self.running, custom_id="qs_clr")
        b_clr.callback = self._cb_clear
        self.add_item(b_clr)

        # ── صف 3: تحكم ───────────────────────────────────────────────────
        b_start = ui.Button(label="🚀  ابدأ التحميل", style=discord.ButtonStyle.success,
                            row=3, disabled=self.running, custom_id="ctrl_start")
        b_start.callback = self._cb_start
        self.add_item(b_start)

        b_close = ui.Button(label="✖  إغلاق", style=discord.ButtonStyle.danger,
                            row=3, disabled=self.running, custom_id="ctrl_close")
        b_close.callback = self._cb_close
        self.add_item(b_close)

    # ── بناء الـ Embed ─────────────────────────────────────────────────────
    def build_embed(self, note: str = None, color=None) -> discord.Embed:
        color = color or (C_RUN if self.running else C_IDLE)

        series = _series_name(self.series_url)
        title  = ("⚙️  جاري التحميل..." if self.running else "📚  لوحة تحكم المانجا")
        sel_s  = set(self.selected)

        em = discord.Embed(title=title, color=color,
                           timestamp=datetime.datetime.now(datetime.timezone.utc))

        # ── معلومات العمل
        em.description = (
            f"**📖 العمل:** `{series}`\n"
            f"**📊 إجمالي:** `{len(self.all_chapters)}` فصل  ·  "
            f"**☑️ محدد:** `{len(self.selected)}`  ·  "
            f"**📄 صفحة:** `{self.page+1}/{self.total_pages}`"
        )

        # ── قائمة فصول الصفحة الحالية (مرئية دائماً)
        chs = self.page_chs
        if chs:
            lines = []
            for n in chs:
                st    = self.ch_status.get(n, {})
                state = st.get("state", "")
                pct   = st.get("progress", 0)
                prov  = st.get("provider", "")
                link  = st.get("link", "")
                lbl   = _lbl(n)

                if state == "queued":
                    tick = "⏸️"; info = "في الانتظار"
                elif state == "downloading":
                    tick = "📥"; info = f"تحميل {pct}%"
                elif state == "stitching":
                    tick = "🧵"; info = "دمج SmartStitch"
                elif state == "uploading":
                    tick = "☁️"; info = f"رفع {prov} {pct}%"
                elif state == "done":
                    tick = "✅"; info = f"[{prov}]({link})" if link else f"جاهز"
                elif state == "failed":
                    tick = "❌"; info = st.get("detail", "فشل")[:40]
                elif n in sel_s:
                    tick = "🔵"; info = "محدد"
                else:
                    tick = "▫️"; info = ""

                line = f"{tick} `Ch.{lbl}`"
                if info:
                    line += f"  —  {info}"
                lines.append(line)

            # أعمدتان إذا كانت الصفحة كاملة
            half = len(lines) // 2
            if len(lines) > 10 and not self.running:
                col_a = "\n".join(lines[:half])
                col_b = "\n".join(lines[half:])
                em.add_field(name=f"📋 الفصول (صفحة {self.page+1})", value=col_a, inline=True)
                em.add_field(name="​", value=col_b, inline=True)
            else:
                em.add_field(name=f"📋 الفصول (صفحة {self.page+1})", value="\n".join(lines), inline=False)

        # ── روابط جاهزة
        ready = [
            f"[Ch.{_lbl(n)}]({self.ch_status[n]['link']})"
            for n in sorted(self.selected)
            if self.ch_status.get(n, {}).get("state") == "done"
            and self.ch_status[n].get("link")
        ]
        if ready:
            em.add_field(name="🔗 روابط جاهزة", value="  ·  ".join(ready[:12]), inline=False)

        if note:
            em.add_field(name="💬", value=note, inline=False)

        em.set_footer(text=f"Cat-Bi  •  Drive → Gofile → Catbox  •  صفحة {self.page+1}/{self.total_pages}")
        return em

    # ── callbacks التنقل ──────────────────────────────────────────────────
    async def _cb_select(self, interaction: discord.Interaction):
        sel     = interaction.data["values"]
        chosen  = {float(v) for v in sel}
        page_s  = set(self.page_chs)
        others  = {n for n in self.selected if n not in page_s}
        self.selected = sorted(others | chosen, reverse=True)
        self._rebuild()
        await interaction.response.edit_message(
            embed=self.build_embed(f"☑️ المحدد الآن: {len(self.selected)} فصل"), view=self
        )

    async def _cb_first(self, interaction: discord.Interaction):
        self.page = 0; self._rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _cb_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1); self._rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _cb_next(self, interaction: discord.Interaction):
        self.page = min(self.total_pages - 1, self.page + 1); self._rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _cb_last(self, interaction: discord.Interaction):
        self.page = self.total_pages - 1; self._rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    # ── callbacks اختيار سريع ────────────────────────────────────────────
    async def _cb_l1(self, interaction: discord.Interaction):
        self.selected = self.all_chapters[:1]; self._rebuild()
        await interaction.response.edit_message(embed=self.build_embed("تم اختيار آخر فصل."), view=self)

    async def _cb_l5(self, interaction: discord.Interaction):
        self.selected = self.all_chapters[:5]; self._rebuild()
        await interaction.response.edit_message(embed=self.build_embed("تم اختيار آخر 5 فصول."), view=self)

    async def _cb_page_all(self, interaction: discord.Interaction):
        pg  = set(self.page_chs)
        oth = {n for n in self.selected if n not in pg}
        self.selected = sorted(oth | pg, reverse=True); self._rebuild()
        await interaction.response.edit_message(
            embed=self.build_embed(f"تم تحديد كل فصول الصفحة ({len(self.page_chs)})."), view=self
        )

    async def _cb_range(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RangeModal(self))

    async def _cb_clear(self, interaction: discord.Interaction):
        self.selected = []; self.ch_status = {}; self._rebuild()
        await interaction.response.edit_message(embed=self.build_embed("تم مسح جميع الاختيارات."), view=self)

    async def _cb_close(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=self.build_embed("🔒 تم إغلاق اللوحة.", color=C_GREY), view=self
        )
        self.stop()

    # ── callback بدء التحميل ──────────────────────────────────────────────
    async def _cb_start(self, interaction: discord.Interaction):
        if self.running:
            return await interaction.response.send_message("⚠️ عملية جارية.", ephemeral=True)
        if not self.selected:
            return await interaction.response.send_message(
                "❗ اختر فصلاً واحداً على الأقل.\nاستخدم القائمة أو أزرار الاختيار السريع أو زر ✏️ نطاق.",
                ephemeral=True
            )

        self.running     = True
        to_dl            = sorted(self.selected)
        self.ch_status   = {n: {"state": "queued"} for n in to_dl}
        self._rebuild()
        await interaction.response.edit_message(
            embed=self.build_embed("🚀 بدأت قائمة التنفيذ...", color=C_RUN), view=self
        )
        panel_msg = interaction.message

        for num in to_dl:
            url   = self.chapters_dict[num]
            lbl   = _lbl(num)
            title = f"Ch_{lbl}"
            self.ch_status[num] = {"state": "downloading", "progress": 0}
            last_edit = 0.0

            async def pcb(cur, tot, txt, _n=num, _l=lbl):
                nonlocal last_edit
                pct   = min(100, int(cur * 100 / max(tot, 1)))
                state = "downloading"
                if any(k in txt for k in ("SmartStitch", "دمج", "🪡")):
                    state = "stitching"
                if "رفع" in txt or "☁️" in txt:
                    state = "uploading"
                prov = ("Drive" if "Drive" in txt
                        else "Gofile" if "Gofile" in txt
                        else "Catbox" if "Catbox" in txt else "")
                self.ch_status[_n].update({"state": state, "progress": pct, "provider": prov})
                now = asyncio.get_running_loop().time()
                if now - last_edit < 1.8 and pct < 100:
                    return
                last_edit = now
                try:
                    await panel_msg.edit(embed=self.build_embed(f"{_l}: {txt} ({pct}%)"))
                except Exception:
                    pass

            fp = None
            try:
                fp = await self.downloader.download_and_stitch(url, title, progress_callback=pcb)
                if not fp:
                    self.ch_status[num] = {"state": "failed", "detail": "فشل التحميل"}
                    await panel_msg.edit(embed=self.build_embed(f"❌ Ch.{lbl}: فشل التحميل."))
                    continue

                link = prov = None
                for pname, pfn in [
                    ("Drive",  lambda f: self.downloader.upload_to_gdrive(f, os.path.basename(f), progress_callback=pcb)),
                    ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=pcb)),
                    ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=pcb)),
                ]:
                    self.ch_status[num].update({"state": "uploading", "provider": pname, "progress": 0})
                    await panel_msg.edit(embed=self.build_embed(f"☁️ Ch.{lbl}: رفع → {pname}..."))
                    link = await pfn(fp)
                    if link:
                        prov = pname
                        break

                if link:
                    self.ch_status[num] = {"state": "done", "progress": 100,
                                           "provider": prov, "link": link}
                    await panel_msg.edit(embed=self.build_embed(
                        f"✅ Ch.{lbl} جاهز عبر {prov}!", color=C_DONE
                    ))
                    # ── منشن المستخدم
                    mention = self.requester.mention if self.requester else ""
                    notify  = discord.Embed(
                        title=f"✅  Ch.{lbl} جاهز!",
                        description=(
                            f"**العمل:** `{_series_name(self.series_url)}`\n"
                            f"**المزود:** {prov}\n"
                            f"[📥  اضغط هنا للتحميل]({link})"
                        ),
                        color=C_DONE,
                        timestamp=datetime.datetime.now(datetime.timezone.utc)
                    )
                    notify.set_footer(text="Cat-Bi Manga System")
                    await panel_msg.channel.send(content=mention, embed=notify)
                else:
                    self.ch_status[num] = {"state": "failed",
                                           "detail": "فشل الرفع (Drive/Gofile/Catbox)"}
                    await panel_msg.edit(embed=self.build_embed(f"❌ Ch.{lbl}: فشل الرفع.", color=C_FAIL))

            except Exception as e:
                self.ch_status[num] = {"state": "failed", "detail": str(e)[:80]}
                await panel_msg.edit(embed=self.build_embed(f"❌ Ch.{lbl}: خطأ.", color=C_FAIL))
            finally:
                if fp:
                    self.downloader.cleanup(fp)
            await asyncio.sleep(0.5)

        self.running = False
        done_n = sum(1 for s in self.ch_status.values() if s.get("state") == "done")
        fail_n = sum(1 for s in self.ch_status.values() if s.get("state") == "failed")
        fc     = C_DONE if fail_n == 0 else (C_FAIL if done_n == 0 else C_RUN)
        self._rebuild()
        await panel_msg.edit(
            embed=self.build_embed(f"🏁 انتهت — ✅ {done_n} نجح، ❌ {fail_n} فشل.", color=fc),
            view=self
        )
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

    # ── رادار الفصول ─────────────────────────────────────────────────────
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
                last = datetime.datetime.fromisoformat(last_str)
                if (now - last) >= datetime.timedelta(hours=interval):
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

                    print(f"[Radar] ✅ فصل جديد {latest} لـ {url}")
                    dl_link = None
                    if dl_en:
                        ch_url = self._build_ch_url(url, latest)
                        ch_ttl = f"Ch_{latest}_{url.rstrip('/').split('/')[-1]}"
                        zp     = await self.downloader.download_and_stitch(ch_url, ch_ttl)
                        if zp:
                            dl_link = (await self.downloader.upload_to_gdrive(zp, os.path.basename(zp))
                                       or await self.downloader.upload_to_gofile(zp)
                                       or await self.downloader.upload_to_catbox(zp))
                            self.downloader.cleanup(zp)

                    ch = self.bot.get_channel(cid)
                    if ch:
                        em = discord.Embed(
                            title="🚨 فصل جديد!",
                            description=(
                                f"**الفصل {_lbl(latest)}** متاح الآن\n"
                                f"*(السابق: {_lbl(last_ch)})*\n\n"
                                f"[🔗 رابط الموقع]({url})"
                            ),
                            color=C_RADAR,
                            timestamp=now,
                        )
                        if dl_link:
                            em.add_field(name="📥 تحميل مباشر", value=f"[اضغط هنا]({dl_link})", inline=False)
                        em.set_footer(text="Cat-Bi Radar")
                        await ch.send(content=msg, embed=em)

                    await database.update_tracker_chapter(tid, latest, now.isoformat())
                except Exception as e:
                    print(f"[Radar] ❌ {tid}: {e}")
                    await database.update_tracker_time(tid, now.isoformat())

        await asyncio.gather(*[check_one(r) for r in due])

    def _build_ch_url(self, series_url: str, num: float) -> str:
        ns = _lbl(num)
        nu = re.sub(r'(chapter[s]?[-/])(\d+(?:\.\d+)?)', rf'\g<1>{ns}', series_url, flags=re.I)
        return nu if nu != series_url else series_url

    # ── أوامر الأدمن ──────────────────────────────────────────────────────
    @app_commands.command(name="track_add", description="[أدمن] إضافة عمل لرادار الفصول.")
    @app_commands.describe(
        url="رابط العمل", channel="روم الإشعارات",
        custom_message="رسالة مرفقة (مثال: @everyone)",
        interval_hours="فحص كل كم ساعة",
        current_chapter="رقم الفصل الحالي",
        auto_download="تحميل ورفع تلقائي"
    )
    @is_admin()
    @app_commands.guild_only()
    async def track_add_cmd(self, interaction: discord.Interaction,
                            url: str, channel: discord.TextChannel,
                            custom_message: str, interval_hours: int,
                            current_chapter: float, auto_download: bool = False):
        if interval_hours < 1:
            return await interaction.response.send_message("❌ أقل مدة فحص: ساعة.", ephemeral=True)
        await database.add_tracker(interaction.guild_id, channel.id, url,
                                   custom_message, interval_hours, current_chapter,
                                   1 if auto_download else 0)
        em = discord.Embed(
            title="📡 تم تفعيل الرادار!",
            description=(
                f"**الرابط:** {url}\n**الروم:** {channel.mention}\n"
                f"**الفصل الحالي:** `{_lbl(current_chapter)}`\n"
                f"**فحص كل:** `{interval_hours}h`\n"
                f"**تحميل تلقائي:** {'✅' if auto_download else '❌'}"
            ),
            color=C_RADAR
        )
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="track_list", description="[أدمن] الأعمال المتتبعة.")
    @is_admin()
    @app_commands.guild_only()
    async def track_list_cmd(self, interaction: discord.Interaction):
        rows = [r for r in await database.get_all_trackers() if r[1] == interaction.guild_id]
        if not rows:
            return await interaction.response.send_message("لا توجد أعمال مُتابَعة.", ephemeral=True)
        em = discord.Embed(title="📡 قائمة الرادار", color=C_RADAR,
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
            title="✅ تمت الإزالة" if ok else "❌ لم يُعثر عليه",
            description=f"الرادار `{tracker_id}`" if ok else "تأكد من الـ ID.",
            color=C_DONE if ok else C_FAIL
        )
        await interaction.response.send_message(embed=em, ephemeral=True)

    # ── تحميل مباشر ───────────────────────────────────────────────────────
    @app_commands.command(name="download_chapter", description="تحميل فصل برابط مباشر (ZIP).")
    @app_commands.describe(url="رابط الفصل")
    @is_admin()
    async def dl_chapter_cmd(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()
        msg = await interaction.followup.send("⏳ جاري التجهيز...")

        async def pcb(cur, tot, txt):
            bar = self.downloader.create_progress_bar(cur, tot)
            try:
                await msg.edit(content=f"⏳ **{txt}**\n{bar}")
            except Exception:
                pass

        try:
            ttl = f"Manual_{url.rstrip('/').split('/')[-2]}"
            fp  = await self.downloader.download_and_stitch(url, ttl, progress_callback=pcb)
            if not fp:
                return await msg.edit(content="❌ فشل تحميل الصور.")
            link = prov = None
            for pname, pfn in [
                ("Drive",  lambda f: self.downloader.upload_to_gdrive(f, os.path.basename(f), progress_callback=pcb)),
                ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=pcb)),
                ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=pcb)),
            ]:
                await pcb(0, 1, f"☁️ رفع إلى {pname}...")
                link = await pfn(fp)
                if link:
                    prov = pname
                    break
            self.downloader.cleanup(fp)
            if link:
                em = discord.Embed(
                    title="✅ الفصل جاهز (ZIP)",
                    description=f"**المزود:** {prov}\n[📥 اضغط هنا]({link})",
                    color=C_DONE, timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                await msg.edit(content=None, embed=em)
            else:
                await msg.edit(content="❌ فشل الرفع على Drive/Gofile/Catbox.")
        except Exception as e:
            await msg.edit(content=f"❌ خطأ: {e}")

    # ── تحميل نطاق ─────────────────────────────────────────────────────────
    @app_commands.command(name="download_range", description="تحميل نطاق فصول — ضع {num} مكان رقم الفصل.")
    @app_commands.describe(base_url="رابط مع {num}", start_ch="أول فصل", end_ch="آخر فصل")
    @is_admin()
    async def dl_range_cmd(self, interaction: discord.Interaction,
                           base_url: str, start_ch: int, end_ch: int):
        if "{num}" not in base_url:
            return await interaction.response.send_message("❌ الرابط يجب أن يحتوي على `{num}`.", ephemeral=True)
        if end_ch < start_ch or (end_ch - start_ch) > 20:
            return await interaction.response.send_message("❌ النطاق غير صالح (الحد 20 فصل).", ephemeral=True)
        await interaction.response.send_message(f"⏳ بدء تحميل {start_ch}→{end_ch}...")

        for ch in range(start_ch, end_ch + 1):
            url  = base_url.replace("{num}", str(ch))
            smsg = await interaction.channel.send(f"⏳ **Ch.{ch}:** جاري...")
            await asyncio.sleep(2)

            async def rcb(cur, tot, txt, _s=smsg, _c=ch):
                try:
                    await _s.edit(content=f"⏳ **Ch.{_c}:** {txt}\n{self.downloader.create_progress_bar(cur,tot)}")
                except Exception:
                    pass

            try:
                fp = await self.downloader.download_and_stitch(url, f"Ch_{ch}", progress_callback=rcb)
                if not fp:
                    await smsg.edit(content=f"❌ **Ch.{ch}:** فشل."); continue
                link = prov = None
                for pname, pfn in [
                    ("Drive",  lambda f: self.downloader.upload_to_gdrive(f, os.path.basename(f), progress_callback=rcb)),
                    ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=rcb)),
                    ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=rcb)),
                ]:
                    link = await pfn(fp)
                    if link:
                        prov = pname; break
                self.downloader.cleanup(fp)
                if link:
                    await smsg.edit(content=None, embed=discord.Embed(
                        title=f"✅ Ch.{ch}", description=f"**{prov}**\n[📥 تحميل]({link})", color=C_DONE))
                else:
                    await smsg.edit(content=f"❌ **Ch.{ch}:** فشل الرفع.")
            except Exception as e:
                await interaction.channel.send(f"❌ **Ch.{ch}:** {e}")

        await interaction.channel.send("🏁 **اكتمل النطاق.**")

    # ── تحميل سلسلة ────────────────────────────────────────────────────────
    @app_commands.command(name="download_series", description="استخراج ذكي للسلسلة ثم تحميل النطاق.")
    @app_commands.describe(series_url="رابط صفحة المانجا", start_ch="أول فصل", end_ch="آخر فصل")
    @is_admin()
    async def dl_series_cmd(self, interaction: discord.Interaction,
                            series_url: str, start_ch: float, end_ch: float):
        if end_ch < start_ch or (end_ch - start_ch) > 20:
            return await interaction.response.send_message("❌ النطاق غير صالح (الحد 20).", ephemeral=True)
        await interaction.response.send_message("🔍 جاري تحليل الصفحة...")
        chs = await self.provider_manager.get_all_chapters(series_url)
        if not chs:
            return await interaction.channel.send("❌ فشل استخراج الفصول.")
        target = {n: u for n, u in chs.items() if start_ch <= n <= end_ch}
        if not target:
            return await interaction.channel.send(f"❌ لا فصول في هذا النطاق. المتاح: {min(chs)}→{max(chs)}")
        await interaction.channel.send(f"⏳ **{len(target)} فصول للتحميل...**")
        for ch_n, url in sorted(target.items()):
            smsg = await interaction.channel.send(f"⏳ **Ch.{_lbl(ch_n)}:** جاري...")
            await asyncio.sleep(2)

            async def scb(cur, tot, txt, _s=smsg, _n=ch_n):
                try:
                    await _s.edit(content=f"⏳ **Ch.{_lbl(_n)}:** {txt}\n{self.downloader.create_progress_bar(cur,tot)}")
                except Exception:
                    pass

            try:
                fp = await self.downloader.download_and_stitch(url, f"Ch_{ch_n}", progress_callback=scb)
                if not fp:
                    await smsg.edit(content=f"❌ **Ch.{_lbl(ch_n)}:** فشل."); continue
                link = prov = None
                for pname, pfn in [
                    ("Drive",  lambda f: self.downloader.upload_to_gdrive(f, os.path.basename(f), progress_callback=scb)),
                    ("Gofile", lambda f: self.downloader.upload_to_gofile(f, progress_callback=scb)),
                    ("Catbox", lambda f: self.downloader.upload_to_catbox(f, progress_callback=scb)),
                ]:
                    link = await pfn(fp)
                    if link:
                        prov = pname; break
                self.downloader.cleanup(fp)
                if link:
                    await smsg.edit(content=None, embed=discord.Embed(
                        title=f"✅ Ch.{_lbl(ch_n)}", description=f"**{prov}**\n[📥 تحميل]({link})", color=C_DONE))
                else:
                    await smsg.edit(content=f"❌ **Ch.{_lbl(ch_n)}:** فشل الرفع.")
            except Exception as e:
                await interaction.channel.send(f"❌ **Ch.{_lbl(ch_n)}:** {e}")
        await interaction.channel.send("🏁 **اكتملت السلسلة.**")

    # ── لوحة التحكم (manga_panel) ──────────────────────────────────────────
    @app_commands.command(name="manga_panel", description="لوحة تحكم للتصفح الكامل وتحميل الفصول.")
    @app_commands.describe(url="الرابط الرئيسي للمانجا/المانهوا")
    @is_admin()
    async def manga_panel_cmd(self, interaction: discord.Interaction, url: str):
        await interaction.response.send_message("🔍 جاري جلب قائمة الفصول...")
        try:
            chs = await self.provider_manager.get_all_chapters(url)
            if not chs:
                return await interaction.edit_original_response(content="❌ فشل استخراج الفصول. تأكد من الرابط.")
            view = MangaPanelView(
                self.bot, self.downloader, self.provider_manager,
                url, chs, requester=interaction.user
            )
            em = view.build_embed(
                f"✅ تم جلب **{len(chs)}** فصل. تصفح الصفحات واختر ما تريد، ثم اضغط 🚀 للبدء."
            )
            await interaction.edit_original_response(content=None, embed=em, view=view)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ خطأ: {e}")


async def setup(bot):
    await bot.add_cog(RadarCog(bot))
