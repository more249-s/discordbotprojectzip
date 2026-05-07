import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import asyncio
import datetime
import re
import os
from typing import Optional, List
import database
from manga_downloader import MangaDownloader

RADAR_CONCURRENT = 5
CHAPTERS_PER_PAGE = 25

# ── ألوان موحدة للبانل ───────────────────────────────────────────────────────
COLOR_IDLE    = discord.Color.from_rgb(88, 101, 242)   # بنفسجي Discord
COLOR_RUNNING = discord.Color.from_rgb(255, 184, 0)    # ذهبي نشط
COLOR_DONE    = discord.Color.from_rgb(87, 242, 135)   # أخضر نجاح
COLOR_FAIL    = discord.Color.from_rgb(237, 66, 69)    # أحمر فشل
COLOR_RADAR   = discord.Color.from_rgb(32, 178, 170)   # فيروزي للرادار


def _chapter_label(num) -> str:
    return str(int(num)) if float(num).is_integer() else str(num)


def _series_name(url: str) -> str:
    parts = [p for p in url.rstrip("/").split("/") if p]
    return parts[-1].replace("-", " ").replace("_", " ").title() if parts else "Manga"


# ─────────────────────────────────────────────────────────────────────────────
#  MangaPanelView — اللوحة الرئيسية
# ─────────────────────────────────────────────────────────────────────────────
class MangaPanelView(ui.View):
    """لوحة تحكم احترافية لتحميل فصول المانجا مع تقليب الصفحات."""

    def __init__(self, bot, downloader, provider_manager, series_url, chapters_dict, requester: discord.User = None):
        super().__init__(timeout=1200)
        self.bot             = bot
        self.downloader      = downloader
        self.provider_manager = provider_manager
        self.series_url      = series_url
        self.requester       = requester          # المستخدم الذي طلب اللوحة

        # كل الفصول مرتبة تنازلياً (الأحدث أولاً)
        self.all_chapters    = sorted(chapters_dict.keys(), reverse=True)
        self.chapters_dict   = chapters_dict

        self.page_index      = 0                  # الصفحة الحالية
        self.selected        : list[float] = []   # الفصول المحددة
        self.chapter_status  : dict       = {}    # حالة كل فصل
        self.running         = False

        self._rebuild_menu()

    # ── مساعدات الصفحات ───────────────────────────────────────────────────
    @property
    def total_pages(self) -> int:
        return max(1, (len(self.all_chapters) + CHAPTERS_PER_PAGE - 1) // CHAPTERS_PER_PAGE)

    @property
    def page_chapters(self) -> list[float]:
        start = self.page_index * CHAPTERS_PER_PAGE
        return self.all_chapters[start: start + CHAPTERS_PER_PAGE]

    # ── بناء قائمة الاختيار ────────────────────────────────────────────────
    def _rebuild_menu(self):
        """إزالة القائمة القديمة وإعادة بنائها بالصفحة الحالية."""
        # أزل كل العناصر ثم أضف القائمة والأزرار
        self.clear_items()

        opts = [
            discord.SelectOption(
                label=f"الفصل {_chapter_label(n)}",
                value=str(n),
                emoji="✅" if n in self.selected else "🔲",
                description=f"{'محدد' if n in self.selected else 'اضغط للتحديد'}",
                default=(n in self.selected),
            )
            for n in self.page_chapters
        ]
        self.select_menu = ui.Select(
            placeholder=f"📖 اختر فصولاً — صفحة {self.page_index+1}/{self.total_pages}",
            min_values=1,
            max_values=len(opts),
            options=opts,
        )
        self.select_menu.callback = self.select_callback
        self.add_item(self.select_menu)

        # صف أزرار التنقل
        self.add_item(self._btn_prev())
        self.add_item(self._btn_page_info())
        self.add_item(self._btn_next())

        # صف أزرار التحديد السريع
        self.add_item(self._btn_latest_one())
        self.add_item(self._btn_latest_five())
        self.add_item(self._btn_all_page())
        self.add_item(self._btn_clear())

        # صف أزرار التحكم
        self.add_item(self._btn_start())
        self.add_item(self._btn_cancel())

    # ── مصانع الأزرار (ديناميكية) ─────────────────────────────────────────
    def _btn_prev(self):
        btn = ui.Button(
            emoji="◀️", style=discord.ButtonStyle.secondary,
            disabled=(self.page_index == 0 or self.running),
            custom_id="btn_prev", row=1
        )
        btn.callback = self.cb_prev
        return btn

    def _btn_next(self):
        btn = ui.Button(
            emoji="▶️", style=discord.ButtonStyle.secondary,
            disabled=(self.page_index >= self.total_pages - 1 or self.running),
            custom_id="btn_next", row=1
        )
        btn.callback = self.cb_next
        return btn

    def _btn_page_info(self):
        btn = ui.Button(
            label=f"{self.page_index + 1} / {self.total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True, custom_id="btn_page_info", row=1
        )
        return btn

    def _btn_latest_one(self):
        btn = ui.Button(label="⭐ آخر فصل", style=discord.ButtonStyle.primary, custom_id="btn_l1", row=2, disabled=self.running)
        btn.callback = self.cb_latest_one
        return btn

    def _btn_latest_five(self):
        btn = ui.Button(label="📦 آخر 5", style=discord.ButtonStyle.secondary, custom_id="btn_l5", row=2, disabled=self.running)
        btn.callback = self.cb_latest_five
        return btn

    def _btn_all_page(self):
        btn = ui.Button(label="📄 هذه الصفحة", style=discord.ButtonStyle.secondary, custom_id="btn_page_all", row=2, disabled=self.running)
        btn.callback = self.cb_all_page
        return btn

    def _btn_clear(self):
        btn = ui.Button(label="🧹 مسح", style=discord.ButtonStyle.danger, custom_id="btn_clear", row=2, disabled=self.running)
        btn.callback = self.cb_clear
        return btn

    def _btn_start(self):
        btn = ui.Button(label="🚀 ابدأ التحميل", style=discord.ButtonStyle.success, custom_id="btn_start", row=3, disabled=self.running)
        btn.callback = self.cb_start
        return btn

    def _btn_cancel(self):
        btn = ui.Button(label="✖ إغلاق", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=3, disabled=self.running)
        btn.callback = self.cb_cancel
        return btn

    # ── بناء الـ Embed ─────────────────────────────────────────────────────
    def build_embed(self, note: str = None, color=None) -> discord.Embed:
        if color is None:
            color = COLOR_RUNNING if self.running else COLOR_IDLE

        title = f"{'⚙️ جاري التحميل...' if self.running else '📚'} لوحة تحكم المانجا"
        series = _series_name(self.series_url)

        embed = discord.Embed(title=title, color=color, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.description = (
            f"**العمل:** `{series}`\n"
            f"**إجمالي الفصول:** `{len(self.all_chapters)}`\n"
            f"**المحدد حالياً:** `{len(self.selected)}`\n"
            f"**الصفحة:** `{self.page_index+1} / {self.total_pages}`"
        )

        # ── قائمة الفصول المحددة مع حالاتها
        if self.selected:
            lines = []
            for num in sorted(self.selected):
                s = self.chapter_status.get(num, {"state": "selected"})
                state = s.get("state", "selected")
                pct   = s.get("progress", 0)
                prov  = s.get("provider", "")
                link  = s.get("link", "")
                lbl   = _chapter_label(num)

                if state == "queued":
                    icon = "⏸️"
                    detail = "في الانتظار"
                elif state == "downloading":
                    icon = "📥"
                    detail = f"تحميل `{pct}%`"
                elif state == "stitching":
                    icon = "🧵"
                    detail = "دمج SmartStitch"
                elif state == "uploading":
                    icon = "☁️"
                    detail = f"رفع {prov} `{pct}%`"
                elif state == "done":
                    icon = "✅"
                    detail = f"[تحميل — {prov}]({link})" if link else f"جاهز عبر {prov}"
                elif state == "failed":
                    icon = "❌"
                    detail = s.get("detail", "فشل")[:50]
                else:
                    icon = "🔲"
                    detail = "محدد"

                lines.append(f"{icon} **الفصل {lbl}** — {detail}")

            # تقسيم إذا كانت القائمة طويلة
            chunk = lines[:15]
            if len(lines) > 15:
                chunk.append(f"… و `{len(lines)-15}` فصل إضافي")
            embed.add_field(name="📋 قائمة التنفيذ", value="\n".join(chunk), inline=False)

        # روابط جاهزة
        ready = [
            f"[الفصل {_chapter_label(n)}]({self.chapter_status[n]['link']})"
            for n in sorted(self.selected)
            if self.chapter_status.get(n, {}).get("state") == "done" and self.chapter_status[n].get("link")
        ]
        if ready:
            embed.add_field(name="🔗 روابط جاهزة", value="  ·  ".join(ready[:10]), inline=False)

        if note:
            embed.add_field(name="💬 آخر تحديث", value=note, inline=False)

        embed.set_footer(
            text=f"Cat-Bi • Google Drive أولاً ثم Gofile • صفحة {self.page_index+1}/{self.total_pages}",
            icon_url="https://i.imgur.com/wXpPqgr.png"
        )
        return embed

    # ── ردود فعل الأزرار ──────────────────────────────────────────────────
    async def select_callback(self, interaction: discord.Interaction):
        chosen = [float(v) for v in self.select_menu.values]
        # دمج مع المحدد من صفحات أخرى
        page_set = set(self.page_chapters)
        others   = [n for n in self.selected if n not in page_set]
        self.selected = sorted(set(others + chosen), reverse=True)
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.build_embed(f"تم تحديث الاختيار: {len(self.selected)} فصل"), view=self)

    async def cb_prev(self, interaction: discord.Interaction):
        if self.page_index > 0:
            self.page_index -= 1
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def cb_next(self, interaction: discord.Interaction):
        if self.page_index < self.total_pages - 1:
            self.page_index += 1
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def cb_latest_one(self, interaction: discord.Interaction):
        self.selected = self.all_chapters[:1]
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.build_embed("تم اختيار آخر فصل."), view=self)

    async def cb_latest_five(self, interaction: discord.Interaction):
        self.selected = self.all_chapters[:5]
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.build_embed("تم اختيار آخر 5 فصول."), view=self)

    async def cb_all_page(self, interaction: discord.Interaction):
        page_set = set(self.page_chapters)
        others   = [n for n in self.selected if n not in page_set]
        self.selected = sorted(set(others + self.page_chapters), reverse=True)
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.build_embed(f"تم اختيار كل فصول الصفحة ({len(self.page_chapters)})."), view=self)

    async def cb_clear(self, interaction: discord.Interaction):
        self.selected      = []
        self.chapter_status = {}
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.build_embed("تم مسح جميع الاختيارات."), view=self)

    async def cb_cancel(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=self.build_embed("🔒 تم إغلاق اللوحة.", color=discord.Color.greyple()), view=self)
        self.stop()

    async def cb_start(self, interaction: discord.Interaction):
        if self.running:
            await interaction.response.send_message("⚠️ عملية جارية بالفعل.", ephemeral=True)
            return
        if not self.selected:
            await interaction.response.send_message("❗ اختر فصلاً واحداً على الأقل أولاً.", ephemeral=True)
            return

        self.running = True
        to_download  = sorted(self.selected)
        self.chapter_status = {n: {"state": "queued"} for n in to_download}
        self._rebuild_menu()

        await interaction.response.edit_message(
            embed=self.build_embed("🚀 بدأت قائمة التنفيذ...", color=COLOR_RUNNING),
            view=self
        )
        panel_msg = interaction.message

        # ──── حلقة التحميل ────────────────────────────────────────────────
        for num in to_download:
            url   = self.chapters_dict[num]
            lbl   = _chapter_label(num)
            title = f"Ch_{lbl}"

            self.chapter_status[num] = {"state": "downloading", "progress": 0}
            last_edit = 0.0

            async def progress_cb(curr, tot, txt, _num=num, _lbl=lbl):
                nonlocal last_edit
                pct   = min(100, int(curr * 100 / max(tot, 1)))
                state = "stitching" if any(k in txt for k in ("SmartStitch", "دمج", "🪡")) else "downloading"
                if "رفع" in txt or "☁️" in txt:
                    state = "uploading"
                prov = "Drive" if "Drive" in txt else ("Gofile" if "Gofile" in txt else "")
                self.chapter_status[_num].update({"state": state, "progress": pct, "provider": prov, "detail": txt})
                now = asyncio.get_running_loop().time()
                if now - last_edit < 1.5 and pct < 100:
                    return
                last_edit = now
                try:
                    await panel_msg.edit(embed=self.build_embed(f"الفصل {_lbl}: {txt} ({pct}%)"))
                except Exception:
                    pass

            file_path = None
            try:
                file_path = await self.downloader.download_and_stitch(url, title, progress_callback=progress_cb)
                if not file_path:
                    self.chapter_status[num] = {"state": "failed", "detail": "فشل التحميل"}
                    await panel_msg.edit(embed=self.build_embed(f"❌ الفصل {lbl}: فشل التحميل."))
                    continue

                # ── رفع Drive أولاً ────────────────────────────────────────
                self.chapter_status[num] = {"state": "uploading", "progress": 0, "provider": "Drive"}
                await panel_msg.edit(embed=self.build_embed(f"☁️ الفصل {lbl}: رفع إلى Google Drive..."))
                link     = await self.downloader.upload_to_gdrive(file_path, os.path.basename(file_path), progress_callback=progress_cb)
                provider = "Google Drive"

                if not link:
                    self.chapter_status[num] = {"state": "uploading", "progress": 0, "provider": "Gofile"}
                    await panel_msg.edit(embed=self.build_embed(f"☁️ الفصل {lbl}: Drive فشل، جاري Gofile..."))
                    link     = await self.downloader.upload_to_gofile(file_path, progress_callback=progress_cb)
                    provider = "Gofile"

                if not link:
                    self.chapter_status[num] = {"state": "uploading", "progress": 0, "provider": "Catbox"}
                    await panel_msg.edit(embed=self.build_embed(f"☁️ الفصل {lbl}: Gofile فشل، جاري Catbox..."))
                    link     = await self.downloader.upload_to_catbox(file_path, progress_callback=progress_cb)
                    provider = "Catbox"

                if link:
                    self.chapter_status[num] = {"state": "done", "progress": 100, "provider": provider, "link": link}
                    await panel_msg.edit(embed=self.build_embed(f"✅ الفصل {lbl}: اكتمل عبر {provider}.", color=COLOR_DONE))
                    # ── منشن المستخدم ─────────────────────────────────────
                    mention = self.requester.mention if self.requester else ""
                    notify_embed = discord.Embed(
                        title=f"✅ الفصل {lbl} جاهز!",
                        description=(
                            f"**العمل:** `{_series_name(self.series_url)}`\n"
                            f"**المزود:** {provider}\n"
                            f"[📥 اضغط هنا للتحميل]({link})"
                        ),
                        color=COLOR_DONE,
                        timestamp=datetime.datetime.now(datetime.timezone.utc)
                    )
                    notify_embed.set_footer(text="Cat-Bi Manga System")
                    await panel_msg.channel.send(content=mention, embed=notify_embed)
                else:
                    self.chapter_status[num] = {"state": "failed", "detail": "فشل الرفع على كلا الخدمتين"}
                    await panel_msg.edit(embed=self.build_embed(f"❌ الفصل {lbl}: فشل الرفع.", color=COLOR_FAIL))

            except Exception as e:
                self.chapter_status[num] = {"state": "failed", "detail": str(e)[:80]}
                await panel_msg.edit(embed=self.build_embed(f"❌ الفصل {lbl}: خطأ — {str(e)[:60]}", color=COLOR_FAIL))
            finally:
                if file_path:
                    self.downloader.cleanup(file_path)
            await asyncio.sleep(0.5)

        # ── انتهاء التحميل ─────────────────────────────────────────────────
        self.running = False
        done_count   = sum(1 for s in self.chapter_status.values() if s.get("state") == "done")
        fail_count   = sum(1 for s in self.chapter_status.values() if s.get("state") == "failed")
        final_color  = COLOR_DONE if fail_count == 0 else (COLOR_FAIL if done_count == 0 else COLOR_RUNNING)

        self._rebuild_menu()
        summary = f"🏁 انتهت العملية — ✅ {done_count} نجح، ❌ {fail_count} فشل."
        await panel_msg.edit(embed=self.build_embed(summary, color=final_color), view=self)
        self.stop()


# ─────────────────────────────────────────────────────────────────────────────
def is_admin():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)


from providers.manager import ProviderManager


# ─────────────────────────────────────────────────────────────────────────────
#  RadarCog
# ─────────────────────────────────────────────────────────────────────────────
class RadarCog(commands.Cog):
    def __init__(self, bot):
        self.bot              = bot
        self.downloader       = MangaDownloader()
        self.provider_manager = ProviderManager()
        self.chapter_radar_loop.start()

    def cog_unload(self):
        self.chapter_radar_loop.cancel()

    # ── فحص الرادار ───────────────────────────────────────────────────────
    async def fetch_latest_chapter(self, url: str, current_ch: float) -> Optional[float]:
        try:
            latest = await self.provider_manager.get_latest_chapter(url)
            if latest and latest > current_ch and latest <= current_ch + 15:
                return latest
        except Exception as e:
            print(f"[Radar] Provider error for {url}: {e}")
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
            tracker_id, guild_id, channel_id, url, last_chapter, custom_msg, interval_hours, last_checked_str, download_enabled = row
            try:
                last_checked = datetime.datetime.fromisoformat(last_checked_str)
                if (now - last_checked) >= datetime.timedelta(hours=interval_hours):
                    due.append(row)
            except Exception:
                due.append(row)

        if not due:
            return

        print(f"--- [الرادار] فحص {len(due)} من أصل {len(trackers)} ---")
        sem = asyncio.Semaphore(RADAR_CONCURRENT)

        async def check_one(row):
            tracker_id, guild_id, channel_id, url, last_chapter, custom_msg, interval_hours, _, download_enabled = row
            async with sem:
                try:
                    print(f"🔍 [الرادار] {url}")
                    latest = await self.fetch_latest_chapter(url, last_chapter)
                    if latest and latest > last_chapter:
                        print(f"✅ فصل جديد: {latest} (القديم: {last_chapter})")

                        download_link = None
                        if download_enabled:
                            chapter_url = self._build_chapter_url(url, latest)
                            ch_title    = f"Ch_{latest}_{url.rstrip('/').split('/')[-1]}"
                            zip_path    = await self.downloader.download_and_stitch(chapter_url, ch_title)
                            if zip_path:
                                download_link = await self.downloader.upload_to_gdrive(zip_path, os.path.basename(zip_path))
                                if not download_link:
                                    download_link = await self.downloader.upload_to_gofile(zip_path)
                                if not download_link:
                                    download_link = await self.downloader.upload_to_catbox(zip_path)
                                self.downloader.cleanup(zip_path)

                        channel = self.bot.get_channel(channel_id)
                        if channel:
                            embed = discord.Embed(
                                title="🚨 فصل جديد!",
                                description=(
                                    f"**الفصل {_chapter_label(latest)}** متاح الآن\n"
                                    f"*(الفصل السابق: {_chapter_label(last_chapter)})*\n\n"
                                    f"[🔗 رابط الموقع]({url})"
                                ),
                                color=COLOR_RADAR,
                                timestamp=now,
                            )
                            if download_link:
                                embed.add_field(name="📥 تحميل مباشر", value=f"[اضغط هنا]({download_link})", inline=False)
                            embed.set_footer(text="Cat-Bi Radar • يتابع الفصول تلقائياً")
                            await channel.send(content=custom_msg, embed=embed)

                        await database.update_tracker_chapter(tracker_id, latest, now.isoformat())
                    else:
                        await database.update_tracker_time(tracker_id, now.isoformat())

                except Exception as e:
                    print(f"❌ [الرادار] خطأ {tracker_id}: {e}")
                    await database.update_tracker_time(tracker_id, now.isoformat())

        await asyncio.gather(*[check_one(row) for row in due])

    def _build_chapter_url(self, series_url: str, chapter_num: float) -> str:
        num_str = _chapter_label(chapter_num)
        new_url = re.sub(r'(chapter[s]?[-/])(\d+(?:\.\d+)?)', rf'\g<1>{num_str}', series_url, flags=re.I)
        return new_url if new_url != series_url else series_url

    # ── أوامر الأدمن ──────────────────────────────────────────────────────
    @app_commands.command(name="track_add", description="[أدمن] إضافة عمل لرادار الفصول.")
    @app_commands.describe(
        url="رابط العمل.",
        channel="الروم لاستقبال التنبيهات.",
        custom_message="رسالة مرفقة (مثال: @everyone).",
        interval_hours="كم ساعة بين كل فحص.",
        current_chapter="رقم الفصل الحالي.",
        auto_download="تحميل الفصل تلقائياً ورفعه."
    )
    @is_admin()
    @app_commands.guild_only()
    async def track_add_command(
        self, interaction: discord.Interaction,
        url: str, channel: discord.TextChannel,
        custom_message: str, interval_hours: int,
        current_chapter: float, auto_download: bool = False
    ):
        if interval_hours < 1:
            return await interaction.response.send_message("❌ أقل مدة للفحص هي ساعة واحدة.", ephemeral=True)
        await database.add_tracker(interaction.guild_id, channel.id, url, custom_message, interval_hours, current_chapter, 1 if auto_download else 0)
        embed = discord.Embed(
            title="📡 تم تفعيل الرادار!",
            description=(
                f"**الرابط:** {url}\n"
                f"**الروم:** {channel.mention}\n"
                f"**الفصل الحالي:** `{_chapter_label(current_chapter)}`\n"
                f"**الفحص كل:** `{interval_hours}` ساعة\n"
                f"**التحميل التلقائي:** {'✅ مفعل' if auto_download else '❌ معطل'}"
            ),
            color=COLOR_RADAR,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="track_list", description="[أدمن] عرض الأعمال المتتبعة في السيرفر.")
    @is_admin()
    @app_commands.guild_only()
    async def track_list_command(self, interaction: discord.Interaction):
        trackers = await database.get_all_trackers()
        guild_trackers = [t for t in trackers if t[1] == interaction.guild_id]

        if not guild_trackers:
            return await interaction.response.send_message("لا توجد أعمال مُتابَعة في هذا السيرفر.", ephemeral=True)

        embed = discord.Embed(title="📡 قائمة الرادار", color=COLOR_RADAR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        desc = ""
        for t_id, g_id, c_id, url, last_ch, msg, interval, last_chk, dl_en in guild_trackers:
            ch   = self.bot.get_channel(c_id)
            name = ch.mention if ch else "روم محذوفة"
            desc += (
                f"**`ID:{t_id}`** — **{_series_name(url)}**\n"
                f"↳ الروم: {name} | آخر فصل: `{_chapter_label(last_ch)}` | كل `{interval}h` | تحميل: {'✅' if dl_en else '❌'}\n\n"
            )
        embed.description = desc[:3900]
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="track_remove", description="[أدمن] إزالة عمل من الرادار بالـ ID.")
    @app_commands.describe(tracker_id="رقم الـ ID من track_list.")
    @is_admin()
    @app_commands.guild_only()
    async def track_remove_command(self, interaction: discord.Interaction, tracker_id: int):
        success = await database.remove_tracker(tracker_id, interaction.guild_id)
        if success:
            await interaction.response.send_message(f"✅ تمت إزالة الرادار `{tracker_id}` بنجاح.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ لم يُعثر على هذا الـ ID في سيرفرك.", ephemeral=True)

    # ── تحميل مباشر ───────────────────────────────────────────────────────
    @app_commands.command(name="download_chapter", description="تحميل فصل برابط مباشر كملف ZIP.")
    @app_commands.describe(url="رابط الفصل")
    @is_admin()
    async def download_chapter_cmd(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()

        msg_obj = await interaction.followup.send("⏳ **جاري التجهيز...**")

        async def pcb(cur, tot, txt):
            bar = self.downloader.create_progress_bar(cur, tot)
            try:
                await msg_obj.edit(content=f"⏳ **{txt}**\n{bar}")
            except Exception:
                pass

        try:
            ch_title  = f"Manual_{url.rstrip('/').split('/')[-2]}"
            file_path = await self.downloader.download_and_stitch(url, ch_title, progress_callback=pcb)
            if not file_path:
                await msg_obj.edit(content="❌ فشل تحميل الصور. تأكد من الرابط.")
                return

            link = provider = None
            for pname, pfn in [
                ("Google Drive", lambda f: self.downloader.upload_to_gdrive(f, os.path.basename(f), progress_callback=pcb)),
                ("Gofile",       lambda f: self.downloader.upload_to_gofile(f, progress_callback=pcb)),
                ("Catbox",       lambda f: self.downloader.upload_to_catbox(f, progress_callback=pcb)),
            ]:
                await pcb(0, 1, f"☁️ رفع إلى {pname}...")
                link = await pfn(file_path)
                if link:
                    provider = pname
                    break

            self.downloader.cleanup(file_path)
            if link:
                embed = discord.Embed(
                    title="✅ تم تحميل الفصل (ZIP)",
                    description=f"**المزود:** {provider}\n[📥 اضغط هنا للتحميل]({link})",
                    color=COLOR_DONE,
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                await msg_obj.edit(content=None, embed=embed)
            else:
                await msg_obj.edit(content="❌ تم التحميل لكن فشل الرفع على Drive وGofile وCatbox.")
        except Exception as e:
            await msg_obj.edit(content=f"❌ خطأ: {str(e)}")

    # ── تحميل نطاق ─────────────────────────────────────────────────────────
    @app_commands.command(name="download_range", description="تحميل نطاق فصول — ضع {num} مكان رقم الفصل.")
    @app_commands.describe(
        base_url="رابط مع {num} مكان رقم الفصل.",
        start_ch="أول فصل", end_ch="آخر فصل"
    )
    @is_admin()
    async def download_range_cmd(self, interaction: discord.Interaction, base_url: str, start_ch: int, end_ch: int):
        if "{num}" not in base_url:
            return await interaction.response.send_message("❌ الرابط يجب أن يحتوي على `{num}`.", ephemeral=True)
        if end_ch < start_ch or (end_ch - start_ch) > 20:
            return await interaction.response.send_message("❌ النطاق غير صالح (الحد 20 فصل).", ephemeral=True)

        await interaction.response.send_message(f"⏳ بدء تحميل الفصول {start_ch}→{end_ch}...")

        for ch in range(start_ch, end_ch + 1):
            url  = base_url.replace("{num}", str(ch))
            smsg = await interaction.channel.send(f"⏳ **الفصل {ch}:** جاري البدء...")
            await asyncio.sleep(2)

            async def rcb(cur, tot, txt, _smsg=smsg, _ch=ch):
                bar = self.downloader.create_progress_bar(cur, tot)
                try:
                    await _smsg.edit(content=f"⏳ **الفصل {_ch}:** {txt}\n{bar}")
                except Exception:
                    pass

            try:
                fp = await self.downloader.download_and_stitch(url, f"Ch_{ch}", progress_callback=rcb)
                if not fp:
                    await smsg.edit(content=f"❌ **الفصل {ch}:** فشل التحميل.")
                    continue
                link = prov = None
                for pname, pfn in [
                    ("Google Drive", lambda f: self.downloader.upload_to_gdrive(f, os.path.basename(f), progress_callback=rcb)),
                    ("Gofile",       lambda f: self.downloader.upload_to_gofile(f, progress_callback=rcb)),
                    ("Catbox",       lambda f: self.downloader.upload_to_catbox(f, progress_callback=rcb)),
                ]:
                    link = await pfn(fp)
                    if link:
                        prov = pname
                        break
                self.downloader.cleanup(fp)
                if link:
                    em = discord.Embed(title=f"✅ الفصل {ch}", description=f"**{prov}**\n[📥 تحميل]({link})", color=COLOR_DONE)
                    await smsg.edit(content=None, embed=em)
                else:
                    await smsg.edit(content=f"❌ **الفصل {ch}:** فشل الرفع على Drive وGofile وCatbox.")
            except Exception as e:
                await interaction.channel.send(f"❌ **الفصل {ch}:** {str(e)}")

        await interaction.channel.send("🏁 **اكتمل تحميل النطاق بالكامل.**")

    # ── تحميل سلسلة ────────────────────────────────────────────────────────
    @app_commands.command(name="download_series", description="استخراج ذكي: ضع رابط السلسلة وسيجلب البوت الفصول تلقائياً.")
    @app_commands.describe(series_url="رابط صفحة المانجا", start_ch="أول فصل", end_ch="آخر فصل")
    @is_admin()
    async def download_series_cmd(self, interaction: discord.Interaction, series_url: str, start_ch: float, end_ch: float):
        if end_ch < start_ch or (end_ch - start_ch) > 20:
            return await interaction.response.send_message("❌ النطاق غير صالح (الحد 20 فصل).", ephemeral=True)

        await interaction.response.send_message("🔍 **جاري تحليل الصفحة...**")
        chapters_dict = await self.provider_manager.get_all_chapters(series_url)
        if not chapters_dict:
            return await interaction.channel.send("❌ فشل استخراج الفصول.")

        target = {n: u for n, u in chapters_dict.items() if start_ch <= n <= end_ch}
        if not target:
            rng = f"من {min(chapters_dict)} إلى {max(chapters_dict)}"
            return await interaction.channel.send(f"❌ لا فصول في هذا النطاق. المتاح: {rng}")

        await interaction.channel.send(f"⏳ **{len(target)} فصول جاهزة للتحميل...**")

        for ch_num, url in sorted(target.items()):
            smsg = await interaction.channel.send(f"⏳ **الفصل {_chapter_label(ch_num)}:** جاري البدء...")
            await asyncio.sleep(2)

            async def scb(cur, tot, txt, _smsg=smsg, _n=ch_num):
                bar = self.downloader.create_progress_bar(cur, tot)
                try:
                    await _smsg.edit(content=f"⏳ **الفصل {_chapter_label(_n)}:** {txt}\n{bar}")
                except Exception:
                    pass

            try:
                fp = await self.downloader.download_and_stitch(url, f"Ch_{ch_num}", progress_callback=scb)
                if not fp:
                    await smsg.edit(content=f"❌ **الفصل {_chapter_label(ch_num)}:** فشل.")
                    continue
                link = prov = None
                for pname, pfn in [
                    ("Google Drive", lambda f: self.downloader.upload_to_gdrive(f, os.path.basename(f), progress_callback=scb)),
                    ("Gofile",       lambda f: self.downloader.upload_to_gofile(f, progress_callback=scb)),
                    ("Catbox",       lambda f: self.downloader.upload_to_catbox(f, progress_callback=scb)),
                ]:
                    link = await pfn(fp)
                    if link:
                        prov = pname
                        break
                self.downloader.cleanup(fp)
                if link:
                    em = discord.Embed(title=f"✅ الفصل {_chapter_label(ch_num)}", description=f"**{prov}**\n[📥 تحميل]({link})", color=COLOR_DONE)
                    await smsg.edit(content=None, embed=em)
                else:
                    await smsg.edit(content=f"❌ **الفصل {_chapter_label(ch_num)}:** فشل الرفع على Drive وGofile وCatbox.")
            except Exception as e:
                await interaction.channel.send(f"❌ **الفصل {_chapter_label(ch_num)}:** {str(e)}")

        await interaction.channel.send("🏁 **اكتملت سلسلة التحميلات.**")

    # ── لوحة التحكم ─────────────────────────────────────────────────────────
    @app_commands.command(name="manga_panel", description="لوحة تحكم احترافية لتحميل الفصول (مع تقليب صفحات).")
    @app_commands.describe(url="الرابط الرئيسي لصفحة المانجا/المانهوا")
    @is_admin()
    async def download_panel_cmd(self, interaction: discord.Interaction, url: str):
        await interaction.response.send_message("🔍 **جاري تحليل الصفحة وجلب الفصول...**")

        try:
            chapters_dict = await self.provider_manager.get_all_chapters(url)
            if not chapters_dict:
                return await interaction.edit_original_response(content="❌ فشل استخراج الفصول. تأكد من الرابط.")

            view  = MangaPanelView(self.bot, self.downloader, self.provider_manager, url, chapters_dict, requester=interaction.user)
            embed = view.build_embed(f"✅ تم جلب {len(chapters_dict)} فصل. اختر من القائمة أو استخدم الأزرار.")
            await interaction.edit_original_response(content=None, embed=embed, view=view)

        except Exception as e:
            await interaction.edit_original_response(content=f"❌ حدث خطأ: {str(e)}")


async def setup(bot):
    await bot.add_cog(RadarCog(bot))
