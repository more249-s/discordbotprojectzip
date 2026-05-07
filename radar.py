import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import asyncio
import datetime
import cloudscraper
from bs4 import BeautifulSoup
import re
import database
import os
from typing import Optional, List
from manga_downloader import MangaDownloader

class MangaPanelView(ui.View):
    def __init__(self, bot, downloader, provider_manager, series_url, chapters_dict):
        super().__init__(timeout=900)
        self.bot = bot
        self.downloader = downloader
        self.provider_manager = provider_manager
        self.series_url = series_url
        self.chapters_dict = chapters_dict
        self.selected_chapters = []
        self.chapter_status = {}
        self.running = False
        
        sorted_nums = sorted(self.chapters_dict.keys(), reverse=True)[:25]
        self.chapter_options = sorted_nums
        
        self.select_menu = ui.Select(
            placeholder="اختر الفصول المطلوبة من آخر 25 فصل...",
            min_values=1,
            max_values=len(sorted_nums),
            options=self._build_select_options()
        )
        self.select_menu.callback = self.select_callback
        self.add_item(self.select_menu)

    def _chapter_label(self, num):
        return str(int(num)) if float(num).is_integer() else str(num)

    def _series_name(self):
        parts = [part for part in self.series_url.rstrip("/").split("/") if part]
        return parts[-1].replace("-", " ").replace("_", " ").title() if parts else "Manga"

    def _build_select_options(self):
        return [
            discord.SelectOption(
                label=f"فصل {self._chapter_label(num)}",
                value=str(num),
                description="جاهز للاختيار والتحميل كملف ZIP",
                default=num in self.selected_chapters,
            )
            for num in self.chapter_options
        ]

    def _sync_select(self):
        self.select_menu.options = self._build_select_options()
        if self.selected_chapters:
            self.select_menu.placeholder = f"تم اختيار {len(self.selected_chapters)} فصل"
        else:
            self.select_menu.placeholder = "اختر الفصول المطلوبة من آخر 25 فصل..."

    def _status_line(self, num):
        label = self._chapter_label(num)
        status = self.chapter_status.get(num, {"state": "selected", "progress": 0})
        state = status.get("state")
        progress = status.get("progress", 0)
        provider = status.get("provider", "")
        if state == "queued":
            return f"⏸️ فصل {label} · في الانتظار"
        if state == "downloading":
            return f"📥 فصل {label} · تحميل {progress}%"
        if state == "stitching":
            return f"🧵 فصل {label} · دمج وتجهيز"
        if state == "uploading":
            return f"☁️ فصل {label} · رفع {provider} {progress}%"
        if state == "done":
            return f"✅ فصل {label} · جاهز عبر {provider}"
        if state == "failed":
            return f"❌ فصل {label} · {status.get('detail', 'فشل')}"
        return f"▫️ فصل {label} · محدد"

    def build_panel_embed(self, current_note=None):
        selected_count = len(self.selected_chapters)
        embed = discord.Embed(
            title="📚 Cat-Bi Manga Control",
            description=(
                f"**العمل:** {self._series_name()}\n"
                f"**الفصول المكتشفة:** {len(self.chapters_dict)}\n"
                f"**المحدد الآن:** {selected_count}\n"
                "**الصيغة:** ZIP فقط"
            ),
            color=discord.Color.from_rgb(88, 166, 255),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        queue_source = self.selected_chapters or self.chapter_options[:8]
        if queue_source:
            lines = [self._status_line(num) for num in sorted(queue_source)[:18]]
            if len(queue_source) > 18:
                lines.append(f"… و {len(queue_source) - 18} فصل إضافي")
            embed.add_field(name="مسار التنفيذ", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="مسار التنفيذ", value="اختر فصل واحد على الأقل من القائمة.", inline=False)

        ready_links = []
        for num in sorted(self.selected_chapters):
            status = self.chapter_status.get(num, {})
            if status.get("state") == "done" and status.get("link"):
                ready_links.append(f"[فصل {self._chapter_label(num)}]({status['link']})")
        if ready_links:
            embed.add_field(name="الروابط الجاهزة", value=" · ".join(ready_links[:10]), inline=False)

        if current_note:
            embed.add_field(name="آخر تحديث", value=current_note, inline=False)

        embed.set_footer(text="Google Drive أولا، ثم Gofile كبديل تلقائي • بدون PDF")
        return embed

    async def select_callback(self, interaction: discord.Interaction):
        self.selected_chapters = [float(v) for v in self.select_menu.values]
        self._sync_select()
        await interaction.response.edit_message(embed=self.build_panel_embed("تم تحديث قائمة الفصول المحددة."), view=self)

    @ui.button(label="آخر فصل", emoji="⭐", style=discord.ButtonStyle.primary, custom_id="btn_latest_one")
    async def select_latest_one(self, interaction: discord.Interaction, button: ui.Button):
        self.selected_chapters = self.chapter_options[:1]
        self._sync_select()
        await interaction.response.edit_message(embed=self.build_panel_embed("تم اختيار آخر فصل."), view=self)

    @ui.button(label="آخر 5", emoji="📦", style=discord.ButtonStyle.secondary, custom_id="btn_latest_five")
    async def select_latest_five(self, interaction: discord.Interaction, button: ui.Button):
        self.selected_chapters = self.chapter_options[:5]
        self._sync_select()
        await interaction.response.edit_message(embed=self.build_panel_embed("تم اختيار آخر 5 فصول."), view=self)

    @ui.button(label="مسح", emoji="🧹", style=discord.ButtonStyle.secondary, custom_id="btn_clear")
    async def clear_selection(self, interaction: discord.Interaction, button: ui.Button):
        self.selected_chapters = []
        self.chapter_status = {}
        self._sync_select()
        await interaction.response.edit_message(embed=self.build_panel_embed("تم مسح الاختيار."), view=self)

    @ui.button(label="ابدأ التحميل", emoji="🚀", style=discord.ButtonStyle.success, custom_id="btn_start_download")
    async def start_download(self, interaction: discord.Interaction, button: ui.Button):
        if self.running:
            await interaction.response.send_message("العملية تعمل بالفعل.", ephemeral=True)
            return
        if not self.selected_chapters:
            await interaction.response.send_message("اختر فصل واحد على الأقل، أو اضغط زر آخر فصل.", ephemeral=True)
            return

        self.running = True
        self.selected_chapters.sort()
        self.chapter_status = {
            num: {"state": "queued", "progress": 0, "detail": "في الانتظار"}
            for num in self.selected_chapters
        }
        self._sync_select()
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            embed=self.build_panel_embed("بدأت قائمة التنفيذ. الفصول غير النشطة تظهر في الانتظار."),
            view=self,
        )
        panel_message = interaction.message

        for num in self.selected_chapters:
            url = self.chapters_dict[num]
            title = f"Ch_{num}"
            label = self._chapter_label(num)
            self.chapter_status[num] = {"state": "downloading", "progress": 0, "detail": "بدء التحميل"}
            await panel_message.edit(embed=self.build_panel_embed(f"الفصل {label}: بدء التحميل."))

            last_progress_edit = 0.0

            async def progress_cb(curr, tot, status_txt):
                nonlocal last_progress_edit
                total = max(tot, 1)
                percent = min(100, int(curr * 100 / total))
                state = "stitching" if "SmartStitch" in status_txt or "دمج" in status_txt else "downloading"
                if "رفع" in status_txt:
                    state = "uploading"
                provider = "Drive" if "Drive" in status_txt else ("Gofile" if "Gofile" in status_txt else "")
                self.chapter_status[num].update({
                    "state": state,
                    "progress": percent,
                    "detail": status_txt,
                    "provider": provider,
                })
                now = asyncio.get_running_loop().time()
                if now - last_progress_edit < 1.5 and percent < 100:
                    return
                last_progress_edit = now
                try:
                    await panel_message.edit(embed=self.build_panel_embed(f"الفصل {label}: {status_txt} ({percent}%)."))
                except Exception:
                    pass

            file_path = None
            try:
                file_path = await self.downloader.download_and_stitch(url, title, progress_callback=progress_cb)
                if not file_path:
                    self.chapter_status[num] = {"state": "failed", "progress": 0, "detail": "فشل التحميل"}
                    await panel_message.edit(embed=self.build_panel_embed(f"الفصل {label}: فشل التحميل."))
                    continue

                self.chapter_status[num] = {"state": "uploading", "progress": 0, "provider": "Drive", "detail": "رفع Drive"}
                await panel_message.edit(embed=self.build_panel_embed(f"الفصل {label}: رفع إلى Google Drive."))
                link = await self.downloader.upload_to_gdrive(file_path, os.path.basename(file_path), progress_callback=progress_cb)
                provider = "Google Drive"

                if not link:
                    self.chapter_status[num] = {"state": "uploading", "progress": 0, "provider": "Gofile", "detail": "رفع Gofile"}
                    await panel_message.edit(embed=self.build_panel_embed(f"الفصل {label}: Drive فشل، جاري Gofile."))
                    link = await self.downloader.upload_to_gofile(file_path, progress_callback=progress_cb)
                    provider = "Gofile"

                if link:
                    self.chapter_status[num] = {
                        "state": "done",
                        "progress": 100,
                        "provider": provider,
                        "link": link,
                        "detail": "جاهز",
                    }
                    await panel_message.edit(embed=self.build_panel_embed(f"الفصل {label}: اكتمل الرفع عبر {provider}."))
                else:
                    self.chapter_status[num] = {"state": "failed", "progress": 100, "detail": "فشل الرفع"}
                    await panel_message.edit(embed=self.build_panel_embed(f"الفصل {label}: فشل الرفع على Drive وGofile."))
            except Exception as e:
                self.chapter_status[num] = {"state": "failed", "progress": 0, "detail": str(e)[:80]}
                await panel_message.edit(embed=self.build_panel_embed(f"الفصل {label}: حدث خطأ."))
            finally:
                if file_path:
                    self.downloader.cleanup(file_path)

            await asyncio.sleep(0.5)

        self.running = False
        await panel_message.edit(embed=self.build_panel_embed("انتهت قائمة التنفيذ."), view=self)
        self.stop()

    @ui.button(label="إلغاء", emoji="✖️", style=discord.ButtonStyle.danger, custom_id="btn_cancel")
    async def cancel_panel(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=self.build_panel_embed("تم إغلاق البانل."), view=self)
        self.stop()

def is_admin():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

from providers.manager import ProviderManager

class RadarCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.downloader = MangaDownloader()
        self.provider_manager = ProviderManager()
        self.chapter_radar_loop.start()

    def cog_unload(self):
        self.chapter_radar_loop.cancel()

    async def fetch_latest_chapter(self, url: str, current_ch: float) -> Optional[float]:
        try:
            latest_chapter = await self.provider_manager.get_latest_chapter(url)
            
            if latest_chapter and latest_chapter > current_ch:
                # Filter out numbers that are suspiciously large compared to current
                if latest_chapter <= current_ch + 10:
                    return latest_chapter
                    
            return None
        except Exception as e:
            print(f"Provider Manager error for {url}: {e}")
            return None

    @tasks.loop(minutes=30)
    async def chapter_radar_loop(self):
        await self.bot.wait_until_ready()
        now = datetime.datetime.now(datetime.timezone.utc)
        trackers = await database.get_all_trackers()
        
        if not trackers:
            return

        print(f"--- [الرادار] جاري بدء فحص {len(trackers)} أعمال الآن ---")
        
        for tracker_id, guild_id, channel_id, url, last_chapter, custom_msg, interval_hours, last_checked_str, download_enabled in trackers:
            try:
                last_checked = datetime.datetime.fromisoformat(last_checked_str)
                if (now - last_checked) < datetime.timedelta(hours=interval_hours):
                    continue
                    
                print(f"🔍 [الرادار] فحص: {url}")
                
                latest_chapter = await self.fetch_latest_chapter(url, last_chapter)
                
                if latest_chapter and latest_chapter > last_chapter:
                    print(f"✅ [الرادار] فصل جديد! {latest_chapter} (القديم: {last_chapter})")
                    
                    gofile_link = None
                    if download_enabled:
                        print(f"📥 [الرادار] جاري تحميل الفصل {latest_chapter}...")
                        chapter_title = f"Ch_{latest_chapter}_{url.split('/')[-2]}"
                        zip_path = await self.downloader.download_and_stitch(url, chapter_title)
                        if zip_path:
                            print(f"📤 [الرادار] جاري الرفع إلى Google Drive...")
                            gofile_link = await self.downloader.upload_to_gdrive(zip_path, os.path.basename(zip_path))
                            if not gofile_link:
                                print(f"⚠️ فشل Google Drive، جاري محاولة Gofile...")
                                gofile_link = await self.downloader.upload_to_gofile(zip_path)
                            self.downloader.cleanup(zip_path)

                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        embed = discord.Embed(
                            title="🚨 فصل جديد متاح!", 
                            description=f"تم العثور على **الفصل {latest_chapter}**\n\n[رابط الموقع]({url})", 
                            color=discord.Color.red()
                        )
                        if gofile_link:
                            embed.add_field(name="📥 رابط تحميل مباشر (Gofile)", value=f"[اضغط هنا للتحميل]({gofile_link})")
                        
                        embed.set_footer(text="تم إيقاف متابعة هذا العمل تلقائياً.")
                        await channel.send(content=custom_msg, embed=embed)
                        print(f"📢 [الرادار] تم إرسال التنبيه!")
                    
                    await database.remove_tracker(tracker_id, guild_id)
                else:
                    await database.update_tracker_time(tracker_id, now.isoformat())
                    
            except Exception as e:
                print(f"❌ [الرادار] خطأ للآي دي {tracker_id}: {e}")

    @app_commands.command(name="track_add", description="[أدمن] إضافة عمل للمتابعة (رادار الفصول).")
    @app_commands.describe(
        url="رابط العمل (المانجا/الويبتون).", 
        channel="الروم التي سيتم إرسال الإشعار لها.", 
        custom_message="الرسالة أو المنشن (مثال: @everyone فصل جديد!).", 
        interval_hours="كل كم ساعة يتحقق البوت؟", 
        current_chapter="رقم الفصل الحالي بالموقع الآن (مثال: 21)",
        auto_download="هل تريد تحميل الفصل تلقائياً ورفعه على Drive ثم Gofile؟"
    )
    @is_admin()
    @app_commands.guild_only()
    async def track_add_command(self, interaction: discord.Interaction, url: str, channel: discord.TextChannel, custom_message: str, interval_hours: int, current_chapter: float, auto_download: bool = False):
        if interval_hours < 1:
            return await interaction.response.send_message("❌ أقل مدة للتحقق هي ساعة واحدة.", ephemeral=True)
            
        await database.add_tracker(interaction.guild_id, channel.id, url, custom_message, interval_hours, current_chapter, 1 if auto_download else 0)
        
        await interaction.response.send_message(
            f"✅ تم تفعيل الرادار بنجاح!\n"
            f"تم تعيين الفصل الحالي يدوياً على **(الفصل {current_chapter})**.\n"
            f"التحميل التلقائي: **{'مفعل' if auto_download else 'معطل'}**.\n"
            f"سيتم إرسال تنبيه في {channel.mention} بمجرد ظهور فصل جديد.", 
            ephemeral=True
        )

    @app_commands.command(name="track_list", description="[أدمن] عرض جميع الأعمال التي يتم متابعتها في السيرفر.")
    @is_admin()
    @app_commands.guild_only()
    async def track_list_command(self, interaction: discord.Interaction):
        trackers = await database.get_all_trackers()
        guild_trackers = [t for t in trackers if t[1] == interaction.guild_id]
        
        if not guild_trackers:
            return await interaction.response.send_message("لا يوجد أي أعمال قيد المتابعة في هذا السيرفر.", ephemeral=True)
            
        embed = discord.Embed(title="📡 قائمة الرادار (المتابعة)", color=discord.Color.blue())
        description = ""
        for t_id, g_id, c_id, url, last_ch, msg, interval, last_chk, download_enabled in guild_trackers:
            channel = self.bot.get_channel(c_id)
            ch_name = channel.mention if channel else "روم محذوفة"
            auto_state = "مفعل" if download_enabled else "معطل"
            description += f"**ID: `{t_id}`**\n- **الروم:** {ch_name}\n- **آخر فصل:** {last_ch}\n- **التحميل التلقائي:** {auto_state}\n- **الرابط:** [اضغط هنا]({url})\n\n"
        
        embed.description = description
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="track_remove", description="[أدمن] إزالة عمل من قائمة المتابعة باستخدام الـ ID الخاص به.")
    @app_commands.describe(tracker_id="رقم الـ ID (يمكنك معرفته من أمر track_list).")
    @is_admin()
    @app_commands.guild_only()
    async def track_remove_command(self, interaction: discord.Interaction, tracker_id: int):
        success = await database.remove_tracker(tracker_id, interaction.guild_id)
        if success:
            await interaction.response.send_message(f"✅ تمت إزالة الرادار رقم `{tracker_id}` بنجاح.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ لم يتم العثور على هذا الـ ID في سيرفرك.", ephemeral=True)

    @app_commands.command(name="download_chapter", description="تحميل فصل مانجا برابط مباشر كملف ZIP")
    @app_commands.describe(url="رابط الفصل")
    @is_admin()
    async def download_chapter_cmd(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()
        
        async def progress_callback(current, total, status_text):
            bar = self.downloader.create_progress_bar(current, total)
            try:
                await interaction.edit_original_response(content=f"⏳ **جاري المعالجة...**\n{status_text}: {bar}")
            except: pass

        try:
            chapter_title = f"Manual_Download_{url.split('/')[-2]}"
            file_path = await self.downloader.download_and_stitch(url, chapter_title, progress_callback=progress_callback)
            
            if not file_path:
                await interaction.edit_original_response(content="❌ فشل في تحميل الصور. تأكد من الرابط أو الحماية.")
                return
                
            await interaction.edit_original_response(content="📤 **جاري الرفع الآن...**")
            
            link = await self.downloader.upload_to_gdrive(file_path, os.path.basename(file_path), progress_callback=progress_callback)
            if not link:
                await interaction.edit_original_response(content="⚠️ فشل Drive، جاري الرفع إلى Gofile...")
                link = await self.downloader.upload_to_gofile(file_path, progress_callback=progress_callback)
            
            self.downloader.cleanup(file_path)
            
            if link:
                embed = discord.Embed(title="✅ تم تحميل الفصل (ZIP)", description=f"[📥 اضغط هنا للتحميل]({link})", color=discord.Color.green())
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send("❌ تم التحميل ولكن فشل الرفع إلى أي مركز تخزين.")
        except Exception as e:
            await interaction.followup.send(f"❌ حدث خطأ: {str(e)}")
    @app_commands.command(name="download_range", description="تحميل مجموعة فصول بشكل متسلسل (مثال: من 1 إلى 5)")
    @app_commands.describe(
        base_url="الرابط مع استبدال رقم الفصل بكلمة {num}. مثال: site.com/ch-{num}/",
        start_ch="أول فصل للتحميل",
        end_ch="آخر فصل للتحميل"
    )
    @is_admin()
    async def download_range_cmd(self, interaction: discord.Interaction, base_url: str, start_ch: int, end_ch: int):
        if "{num}" not in base_url:
            await interaction.response.send_message("❌ الرابط يجب أن يحتوي على `{num}` لكي يتمكن البوت من تغييره.", ephemeral=True)
            return
            
        if end_ch < start_ch or (end_ch - start_ch) > 20:
            await interaction.response.send_message("❌ النطاق غير صالح أو كبير جداً (الحد الأقصى 20 فصل في المرة الواحدة لحماية البوت).", ephemeral=True)
            return

        await interaction.response.send_message(f"⏳ **جاري بدء تحميل النطاق من الفصل {start_ch} إلى {end_ch}...**\n(سيتم إرسال الفصول تباعاً هنا)", ephemeral=False)
        
        for ch_num in range(start_ch, end_ch + 1):
            target_url = base_url.replace("{num}", str(ch_num))
            chapter_title = f"Ch_{ch_num}"
            
            try:
                # Add delay to avoid rate limits
                await asyncio.sleep(2)
                
                status_msg = await interaction.channel.send(f"⏳ **الفصل {ch_num}:** جاري البدء...")
                
                async def range_callback(current, total, status_text):
                    bar = self.downloader.create_progress_bar(current, total)
                    try:
                        await status_msg.edit(content=f"⏳ **الفصل {ch_num}:** {status_text}\n{bar}")
                    except: pass

                file_path = await self.downloader.download_and_stitch(target_url, chapter_title, progress_callback=range_callback)
                if not file_path:
                    await status_msg.edit(content=f"❌ **الفصل {ch_num}:** فشل في التحميل.")
                    continue
                    
                link = await self.downloader.upload_to_gdrive(file_path, os.path.basename(file_path), progress_callback=range_callback)
                if not link:
                    await status_msg.edit(content=f"⚠️ **الفصل {ch_num}:** Drive فشل، جاري Gofile...")
                    link = await self.downloader.upload_to_gofile(file_path, progress_callback=range_callback)
                
                self.downloader.cleanup(file_path)
                
                if link:
                    embed = discord.Embed(title=f"✅ الفصل {ch_num} (ZIP)", description=f"[📥 اضغط هنا للتحميل]({link})", color=discord.Color.green())
                    await status_msg.edit(content=None, embed=embed)
                else:
                    await status_msg.edit(content=f"❌ **الفصل {ch_num}:** تم التحميل لكن فشل الرفع.")
            except Exception as e:
                await interaction.channel.send(f"❌ **الفصل {ch_num}:** حدث خطأ: {str(e)}")
        
        await interaction.channel.send("🏁 **تم الانتهاء من تحميل النطاق المطلوب بالكامل.**")

    @app_commands.command(name="download_series", description="الاستخراج الذكي: وضع رابط السلسلة وسيقوم البوت باستخراج الفصول تلقائياً")
    @app_commands.describe(
        series_url="الرابط الرئيسي لصفحة المانجا/المانهوا",
        start_ch="أول فصل للتحميل",
        end_ch="آخر فصل للتحميل"
    )
    @is_admin()
    async def download_series_cmd(self, interaction: discord.Interaction, series_url: str, start_ch: float, end_ch: float):
        if end_ch < start_ch or (end_ch - start_ch) > 20:
            await interaction.response.send_message("❌ النطاق غير صالح أو كبير جداً (الحد الأقصى 20 فصل في المرة الواحدة).", ephemeral=True)
            return

        await interaction.response.send_message(f"🔍 **جاري تحليل الصفحة واستخراج الفصول...**", ephemeral=False)
        
        try:
            chapters_dict = await self.provider_manager.get_all_chapters(series_url)
            
            if not chapters_dict:
                await interaction.channel.send("❌ **فشل في استخراج الفصول.** جرب إعطاء رابط آخر أو تأكد من حماية الموقع.")
                return
                
            # Filter chapters within range
            target_chapters = {num: url for num, url in chapters_dict.items() if start_ch <= num <= end_ch}
            
            if not target_chapters:
                await interaction.channel.send(f"❌ **لم يتم العثور على أي فصول في النطاق ({start_ch} - {end_ch}).**\nالفصول المتاحة: من {min(chapters_dict.keys(), default=0)} إلى {max(chapters_dict.keys(), default=0)}")
                return
                
            # Sort by chapter number
            sorted_chapters = sorted(target_chapters.items(), key=lambda x: x[0])
            
            await interaction.channel.send(f"⏳ **تم العثور على {len(sorted_chapters)} فصل في هذا النطاق. جاري التحميل...**")
            
            for ch_num, target_url in sorted_chapters:
                chapter_title = f"Ch_{ch_num}"
                
                try:
                    await asyncio.sleep(2)
                    status_msg = await interaction.channel.send(f"⏳ **الفصل {ch_num}:** جاري البدء...")
                    
                    async def series_callback(current, total, status_text):
                        bar = self.downloader.create_progress_bar(current, total)
                        try:
                            await status_msg.edit(content=f"⏳ **الفصل {ch_num}:** {status_text}\n{bar}")
                        except: pass

                    file_path = await self.downloader.download_and_stitch(target_url, chapter_title, progress_callback=series_callback)
                    if not file_path:
                        await status_msg.edit(content=f"❌ **الفصل {ch_num}:** فشل في التحميل.")
                        continue
                        
                    link = await self.downloader.upload_to_gdrive(file_path, os.path.basename(file_path), progress_callback=series_callback)
                    if not link:
                        await status_msg.edit(content=f"⚠️ **الفصل {ch_num}:** Drive فشل، جاري Gofile...")
                        link = await self.downloader.upload_to_gofile(file_path, progress_callback=series_callback)
                        
                    self.downloader.cleanup(file_path)
                    
                    if link:
                        embed = discord.Embed(title=f"✅ الفصل {ch_num} (ZIP)", description=f"[📥 اضغط هنا للتحميل]({link})", color=discord.Color.green())
                        await status_msg.edit(content=None, embed=embed)
                    else:
                        await status_msg.edit(content=f"❌ **الفصل {ch_num}:** تم التحميل لكن فشل الرفع.")
                except Exception as e:
                    await interaction.channel.send(f"❌ **الفصل {ch_num}:** حدث خطأ: {str(e)}")
            
            await interaction.channel.send("🏁 **تم الانتهاء من سلسلة التحميلات بنجاح.**")
        except Exception as e:
            await interaction.channel.send(f"❌ **حدث خطأ فادح أثناء العملية:** {str(e)}")

    @app_commands.command(name="manga_panel", description="لوحة تحكم احترافية لتحميل الفصول كملفات ZIP")
    @app_commands.describe(url="الرابط الرئيسي لصفحة المانجا/المانهوا")
    @is_admin()
    async def download_panel_cmd(self, interaction: discord.Interaction, url: str):
        await interaction.response.send_message(f"🔍 **جاري تحليل الصفحة وجلب قائمة الفصول...**", ephemeral=False)
        
        try:
            chapters_dict = await self.provider_manager.get_all_chapters(url)
            if not chapters_dict:
                await interaction.edit_original_response(content="❌ فشل في استخراج الفصول. تأكد من الرابط.")
                return
                
            view = MangaPanelView(self.bot, self.downloader, self.provider_manager, url, chapters_dict)
            embed = view.build_panel_embed("اختر من القائمة أو استخدم أزرار آخر فصل / آخر 5.")
            await interaction.edit_original_response(content=None, embed=embed, view=view)
            
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ حدث خطأ: {str(e)}")

async def setup(bot):
    await bot.add_cog(RadarCog(bot))
