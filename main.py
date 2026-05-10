import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import io
import os
import sys
import aiohttp
import datetime
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from config import Config
import database
from gemini_client import GeminiClient
from keep_alive import keep_alive
from manga_downloader import MangaDownloader
from providers.manager import ProviderManager
from providers.lekmanga_provider import CloudflareBlockedError
from user_system import owner_only, vip_only, user_only, get_rank, RANK_LABELS, RANK_COLORS

C_BLUE   = discord.Color.from_rgb(88, 101, 242)
C_GREEN  = discord.Color.from_rgb(87, 242, 135)
C_RED    = discord.Color.from_rgb(237, 66, 69)
C_GOLD   = discord.Color.from_rgb(255, 184, 0)
C_TEAL   = discord.Color.from_rgb(32, 178, 170)
C_GREY   = discord.Color.from_rgb(153, 170, 181)
C_ORANGE = discord.Color.from_rgb(255, 127, 0)
C_INDIGO = discord.Color.from_rgb(99, 102, 241)
C_PURPLE = discord.Color.from_rgb(124, 92, 252)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot          = commands.Bot(command_prefix="!", intents=intents)
gemini       = GeminiClient()
downloader   = MangaDownloader()
provider_mgr = ProviderManager()

registered_cache: set = set()
BOT_START_TIME = datetime.datetime.now(datetime.timezone.utc)


async def setup_hook():
    await database.init_db()
    await bot.load_extension("radar")
    await database.log_event("OK", "Bot initialized and DB ready")

bot.setup_hook = setup_hook


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    await database.log_event("OK", f"Logged in as {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
        await database.log_event("OK", f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Failed to sync: {e}")
        await database.log_event("ERROR", f"Sync failed: {e}")
    print("Bot ready.")

    import web_panel
    web_panel.set_bot(bot, database)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # تسجيل تلقائي عند أول رسالة (بدون إيقاف المعالجة)
    if message.author.id not in registered_cache:
        await get_rank(message.author.id, auto_register=True)
        registered_cache.add(message.author.id)

    is_gemini_ch = message.channel.id == Config.GEMINI_CHANNEL_ID
    is_mentioned = bot.user.mentioned_in(message)

    if is_gemini_ch or is_mentioned:
        rank = await get_rank(message.author.id)
        if rank < 2:
            if is_mentioned:
                await message.reply(
                    "❌ ليس لديك صلاحية استخدام Gemini AI.\n"
                    "تواصل مع المالك للحصول على وصول.",
                    mention_author=False,
                )
            return

        async with message.channel.typing():
            prompt = (message.content
                      .replace(f"<@!{bot.user.id}>", "")
                      .replace(f"<@{bot.user.id}>", "")
                      .strip())

            image_data = None
            if message.attachments:
                for att in message.attachments:
                    if any(att.filename.lower().endswith(e)
                           for e in ["png", "jpg", "jpeg", "webp", "gif"]):
                        async with aiohttp.ClientSession() as s:
                            async with s.get(att.url) as r:
                                if r.status == 200:
                                    image_data = {
                                        "mime_type": att.content_type,
                                        "data": await r.read(),
                                    }
                                    break

            resp = await gemini.get_response(message.author.id, prompt, image_data)
            chunks = [resp[i: i + 2000] for i in range(0, len(resp), 2000)]
            for chunk in chunks:
                await message.reply(chunk, mention_author=False)

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    await database.log_event("WARN", f"Command error: {error}")


# ══════════════════════════════════════════════════════════════════════════
#  إدارة المستخدمين — Owner فقط
# ══════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="user_add", description="[Owner] إضافة مستخدم أو ترقيته")
@app_commands.describe(user="المستخدم", rank="الرتبة", note="ملاحظة (اختياري)")
@app_commands.choices(rank=[
    app_commands.Choice(name="1 — User  (بحث + قراءة)", value=1),
    app_commands.Choice(name="2 — VIP   (تحميل مانجا + SmartStitch)", value=2),
])
@owner_only()
async def user_add_cmd(
    interaction: discord.Interaction,
    user: discord.User,
    rank: int,
    note: str = "",
):
    await database.set_user_rank(user.id, rank, note)
    await database.log_event("OK", f"User {user.id} set to rank {rank} by {interaction.user.id}")
    em = discord.Embed(
        title="✅ تم إضافة المستخدم",
        color=RANK_COLORS.get(rank, C_BLUE),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    em.add_field(name="المستخدم", value=user.mention, inline=True)
    em.add_field(name="الرتبة",   value=RANK_LABELS.get(rank, str(rank)), inline=True)
    if note:
        em.add_field(name="ملاحظة", value=note, inline=False)
    em.set_thumbnail(url=user.display_avatar.url)
    await interaction.response.send_message(embed=em, ephemeral=True)


@bot.tree.command(name="user_remove", description="[Owner] إزالة مستخدم")
@app_commands.describe(user="المستخدم المراد إزالته")
@owner_only()
async def user_remove_cmd(interaction: discord.Interaction, user: discord.User):
    await database.remove_user(user.id)
    registered_cache.discard(user.id)
    await interaction.response.send_message(embed=discord.Embed(
        title="🗑️ تم إزالة المستخدم",
        description=f"{user.mention} لم يعد مسجلاً.",
        color=C_RED,
    ), ephemeral=True)


@bot.tree.command(name="user_list", description="[Owner] قائمة المستخدمين")
@owner_only()
async def user_list_cmd(interaction: discord.Interaction):
    rows = await database.get_all_users()
    em   = discord.Embed(
        title="👥 قائمة المستخدمين",
        color=C_INDIGO,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    owners_txt = "\n".join(f"<@{uid}>" for uid in Config.ALLOWED_USER_IDS) or "—"
    em.add_field(name="👑 Owner", value=owners_txt, inline=False)

    vip_lines, user_lines = [], []
    for uid, rank, note, added in rows:
        line = f"<@{uid}>"
        if note:
            line += f"  —  {note}"
        (vip_lines if rank >= 2 else user_lines).append(line)

    if vip_lines:
        em.add_field(name="⭐ VIP", value="\n".join(vip_lines), inline=False)
    if user_lines:
        em.add_field(name="👤 User", value="\n".join(user_lines), inline=False)
    if not rows:
        em.description = "لا يوجد مستخدمون مسجّلون."

    em.set_footer(text=f"المجموع: {len(rows)} مستخدم  ·  Cat-Bi")
    await interaction.response.send_message(embed=em, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════
#  أوامر Gemini AI
# ══════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="clear_history", description="مسح سجل محادثتك مع Gemini AI")
@user_only()
async def clear_history_cmd(interaction: discord.Interaction):
    await gemini.clear_history(interaction.user.id)
    await interaction.response.send_message(embed=discord.Embed(
        title="🗑️ تم مسح السجل",
        description="محادثتك مع Gemini AI تم حذفها. يمكنك البدء من جديد.",
        color=C_GREEN,
    ), ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════
#  أوامر إضافة المواقع الجديدة
# ══════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="add_site", description="[Owner] إضافة موقع مانجا جديد للبوت")
@app_commands.describe(
    url="رابط الموقع الجديد (مثال: https://manga-site.com)",
    force_type="نوع الموقع (اختياري — Gemini سيحدده تلقائياً إذا تركته فارغاً)",
)
@app_commands.choices(force_type=[
    app_commands.Choice(name="Madara (WordPress — الأكثر شيوعاً)", value="madara"),
    app_commands.Choice(name="Arabic (مواقع عربية)", value="arabic"),
    app_commands.Choice(name="Generic (أي موقع آخر)", value="generic"),
])
@owner_only()
async def add_site_cmd(
    interaction: discord.Interaction,
    url: str,
    force_type: str = "",
):
    await interaction.response.defer(ephemeral=True)

    from urllib.parse import urlparse
    parsed = urlparse(url if url.startswith("http") else f"https://{url}")
    domain = parsed.netloc.replace("www.", "") or url.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]

    if not domain:
        return await interaction.followup.send("❌ رابط غير صالح.", ephemeral=True)

    em = discord.Embed(title="🔍 تحليل الموقع...", color=C_BLUE)
    em.add_field(name="الدومين", value=f"`{domain}`", inline=True)

    if force_type:
        site_type  = force_type
        confidence = 100
        reason     = "محدد يدوياً"
    else:
        em.description = "⏳ Gemini AI يحلل الموقع..."
        await interaction.followup.send(embed=em, ephemeral=True)

        analysis = await gemini.analyze_site(url)

        if not analysis.get("is_manga_site"):
            return await interaction.edit_original_response(embed=discord.Embed(
                title="❌ ليس موقع مانجا",
                description=f"**السبب:** {analysis.get('reason', 'غير محدد')}\n"
                            f"**الثقة:** {analysis.get('confidence', 0)}%",
                color=C_RED,
            ))
        site_type  = analysis.get("site_type", "generic")
        confidence = analysis.get("confidence", 80)
        reason     = analysis.get("reason", "")

    await database.add_custom_site(domain, site_type, interaction.user.id, reason[:200])
    await database.log_event("OK", f"Custom site added: {domain} ({site_type}) by {interaction.user.id}")

    # أعد تحميل قوائم المواقع في ProviderManager
    await provider_mgr.reload_custom_sites()

    result_em = discord.Embed(
        title="✅ تم إضافة الموقع بنجاح!",
        color=C_GREEN,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    result_em.add_field(name="الدومين",  value=f"`{domain}`", inline=True)
    result_em.add_field(name="النوع",    value=f"`{site_type}`", inline=True)
    if not force_type:
        result_em.add_field(name="الثقة",   value=f"`{confidence}%`", inline=True)
        result_em.add_field(name="التحليل", value=reason[:300] or "—", inline=False)
    result_em.set_footer(text="استخدم /manga_panel لتجربة الموقع الجديد")

    try:
        await interaction.edit_original_response(embed=result_em)
    except Exception:
        await interaction.followup.send(embed=result_em, ephemeral=True)


@bot.tree.command(name="remove_site", description="[Owner] إزالة موقع مخصص")
@app_commands.describe(domain="الدومين المراد إزالته (مثال: manga-site.com)")
@owner_only()
async def remove_site_cmd(interaction: discord.Interaction, domain: str):
    await database.remove_custom_site(domain.lower().strip())
    await provider_mgr.reload_custom_sites()
    await interaction.response.send_message(embed=discord.Embed(
        title="🗑️ تم حذف الموقع",
        description=f"`{domain}` أُزيل من القائمة.",
        color=C_GREEN,
    ), ephemeral=True)


@bot.tree.command(name="list_sites", description="قائمة المواقع المخصصة المضافة")
@owner_only()
async def list_sites_cmd(interaction: discord.Interaction):
    sites = await database.get_custom_sites()
    em = discord.Embed(
        title="🌐 المواقع المخصصة",
        color=C_TEAL,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if not sites:
        em.description = "لم تُضف مواقع مخصصة بعد. استخدم `/add_site`."
    else:
        madara = [f"`{d[0]}`" for d in sites if d[1] == "madara"]
        arabic = [f"`{d[0]}`" for d in sites if d[1] == "arabic"]
        generic= [f"`{d[0]}`" for d in sites if d[1] == "generic"]
        if madara:  em.add_field(name="⚡ Madara", value="  ".join(madara)[:1020], inline=False)
        if arabic:  em.add_field(name="🇸🇦 Arabic", value="  ".join(arabic)[:1020], inline=False)
        if generic: em.add_field(name="🌐 Generic", value="  ".join(generic)[:1020], inline=False)
        em.set_footer(text=f"{len(sites)} موقع مضاف")
    await interaction.response.send_message(embed=em, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════
#  SmartStitch من Google Drive
# ══════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="stitch_drive", description="[VIP] SmartStitch لملف/مجلد Google Drive")
@app_commands.describe(
    drive_url="رابط Google Drive (مجلد صور أو ملف ZIP)",
    title="اسم الفصل (اختياري)",
    width="عرض الصورة بـ px (افتراضي: 800)",
    height="الحد الأقصى للارتفاع بـ px (افتراضي: 14500)",
    sensitivity="حساسية الدمج 1-100 (افتراضي: 90)",
)
@vip_only()
async def stitch_drive_cmd(
    interaction: discord.Interaction,
    drive_url: str,
    title: str = "chapter",
    width: int = 800,
    height: int = 14500,
    sensitivity: int = 90,
):
    # التحقق من الإعدادات
    width       = max(200, min(4000, width))
    height      = max(3000, min(50000, height))
    sensitivity = max(1,   min(100,   sensitivity))

    await interaction.response.defer()

    state = {
        "phase": "⏳ جاري التجهيز...",
        "pct":   0,
        "link":  None,
        "color": C_BLUE,
    }

    def build_em():
        em = discord.Embed(
            title="🧵 SmartStitch من Google Drive",
            color=state["color"],
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        from manga_downloader import MangaDownloader
        bar = MangaDownloader.create_progress_bar(state["pct"], 100)
        em.add_field(name="⚙️ الحالة",    value=state["phase"], inline=False)
        em.add_field(name="📊 التقدم",    value=f"`{bar}`", inline=False)
        em.add_field(name="📐 الإعدادات", value=f"`{width}×{height}px` | حساسية: `{sensitivity}%`", inline=False)
        if state["link"]:
            em.add_field(name="🔗 الرابط", value=f"[تحميل الملف]({state['link']})", inline=False)
        em.set_footer(text=f"العنوان: {title}  ·  Cat-Bi SmartStitch")
        return em

    msg      = await interaction.followup.send(embed=build_em())
    last_upd = 0.0

    async def pcb(cur, tot, txt):
        nonlocal last_upd
        pct = min(100, int(cur * 100 / max(tot, 1))) if tot else cur
        state["phase"] = txt
        state["pct"]   = pct
        now = asyncio.get_running_loop().time()
        if now - last_upd < 1.5 and pct < 100:
            return
        last_upd = now
        try:
            await msg.edit(embed=build_em())
        except Exception:
            pass

    try:
        from drive_stitch import stitch_from_drive
        final = await stitch_from_drive(
            drive_url=drive_url,
            title=title,
            target_height=height,
            target_width=width,
            sensitivity=sensitivity,
            progress_callback=pcb,
        )

        if not final or not os.path.exists(final):
            state["phase"] = "❌ فشل المعالجة"
            state["color"] = C_RED
            await msg.edit(embed=build_em())
            return

        size_mb = os.path.getsize(final) / (1024 * 1024)
        state["phase"] = f"📤 رفع الملف ({size_mb:.1f} MB)..."
        await msg.edit(embed=build_em())

        link = None
        # محاولة رفع إلى Gofile ثم Catbox
        for pname, pfn in [
            ("Gofile", lambda f: downloader.upload_to_gofile(f, progress_callback=pcb)),
            ("Catbox", lambda f: downloader.upload_to_catbox(f, progress_callback=pcb)),
        ]:
            state["phase"] = f"☁️ رفع إلى {pname}..."
            await msg.edit(embed=build_em())
            link = await pfn(final)
            if link:
                break

        downloader.cleanup(final)

        if link:
            state["phase"] = "✅ اكتمل SmartStitch!"
            state["pct"]   = 100
            state["link"]  = link
            state["color"] = C_GREEN
            await msg.edit(embed=build_em())
            await database.log_event("OK", f"DriveStitch done for user {interaction.user.id}: {title}")
            await interaction.followup.send(
                content=f"✅ {interaction.user.mention} جاهز! SmartStitch اكتمل لـ **{title}**\n🔗 {link}"
            )
        else:
            state["phase"] = "❌ فشل رفع الملف"
            state["color"] = C_RED
            await msg.edit(embed=build_em())

    except Exception as e:
        state["phase"] = f"❌ خطأ: {str(e)[:100]}"
        state["color"] = C_RED
        try:
            await msg.edit(embed=build_em())
        except Exception:
            pass
        await database.log_event("ERROR", f"DriveStitch error for {interaction.user.id}: {e}")
        import traceback
        traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════
#  البحث عن مانجا
# ══════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="search", description="بحث عن مانجا/مانهوا وفتح لوحة التحكم")
@app_commands.describe(query="اسم المانجا أو الكلمة المفتاحية")
@user_only()
async def search_manga(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    results = await provider_mgr.search_manga(query, limit=10)
    if not results:
        return await interaction.followup.send(embed=discord.Embed(
            title="🔍 لا نتائج",
            description=f"لم يُعثر على نتائج لـ `{query}`.",
            color=C_RED,
        ))

    em = discord.Embed(
        title=f"🔍 نتائج البحث: {query}",
        description="اختر مانجا لفتح لوحة التحكم:",
        color=C_BLUE,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )

    class SearchDropdown(discord.ui.Select):
        def __init__(self, items):
            options = [
                discord.SelectOption(
                    label=r["title"][:100],
                    description=f"Status: {r['status']}",
                    value=r["url"],
                    emoji="📖",
                )
                for r in items
            ]
            super().__init__(placeholder="اختر مانجا...", options=options)

        async def callback(self, i: discord.Interaction):
            await i.response.defer()
            radar_cog = bot.get_cog("RadarCog")
            if radar_cog:
                await radar_cog.manga_panel_cmd(i, self.values[0])
            else:
                await i.followup.send("❌ وحدة الرادار غير متاحة.", ephemeral=True)

    view = discord.ui.View()
    view.add_item(SearchDropdown(results))

    if results[0].get("cover"):
        em.set_thumbnail(url=results[0]["cover"])

    await interaction.followup.send(embed=em, view=view)


# ══════════════════════════════════════════════════════════════════════════
#  التحميل المباشر
# ══════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="download_direct", description="[VIP] تحميل فصل مباشرة برابطه")
@app_commands.describe(url="رابط الفصل", title="اسم الملف (اختياري)")
@vip_only()
async def download_cmd(
    interaction: discord.Interaction,
    url: str,
    title: str = "Manga_Chapter",
):
    DISCORD_LIMIT_MB = 10.0
    await interaction.response.defer()

    state = {
        "phase": "🔄 تهيئة",
        "progress": downloader.create_progress_bar(0, 1),
        "counter": "0/1",
        "size": "—",
        "provider": "—",
        "link": None,
        "color": C_BLUE,
    }

    def build_em():
        em = discord.Embed(
            title="📦 تحميل الفصل",
            color=state["color"],
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        em.description = f"**العنوان:** `{title}`\n**الصيغة:** ZIP + SmartStitch"
        em.add_field(name="⚙️ الحالة",  value=state["phase"],    inline=False)
        em.add_field(name="📊 التقدم",  value=f"`{state['progress']}`  `{state['counter']}`", inline=False)
        em.add_field(name="📁 الحجم",   value=state["size"],     inline=True)
        em.add_field(name="☁️ الوجهة",  value=state["provider"], inline=True)
        if state["link"]:
            em.add_field(name="🔗 الرابط", value=f"[اضغط هنا]({state['link']})", inline=False)
        em.set_footer(text="Cat-Bi Manga System")
        return em

    msg      = await interaction.followup.send(embed=build_em())
    last_upd = 0.0

    async def pcb(cur, tot, txt):
        nonlocal last_upd
        state["phase"]    = txt
        state["progress"] = downloader.create_progress_bar(cur, tot)
        state["counter"]  = f"{cur}/{tot}"
        now = asyncio.get_running_loop().time()
        if now - last_upd < 1.25 and cur < tot:
            return
        last_upd = now
        try:
            await msg.edit(embed=build_em())
        except Exception:
            pass

    try:
        final = await downloader.download_and_stitch(url, title, progress_callback=pcb)
        if final and os.path.exists(final):
            size_mb       = os.path.getsize(final) / (1024 * 1024)
            state["size"] = f"{size_mb:.2f} MB"

            if size_mb <= DISCORD_LIMIT_MB:
                state["phase"]    = "📤 إرسال إلى Discord"
                state["provider"] = "Discord"
                await msg.edit(embed=build_em())
                await interaction.followup.send(
                    content=f"✅ {interaction.user.mention} الفصل جاهز!",
                    file=discord.File(final),
                )
                state["phase"] = "✅ اكتملت"
                state["color"] = C_GREEN
                await msg.edit(embed=build_em())
            else:
                link = prov = None
                for pname, pfn in [
                    ("Gofile", lambda f: downloader.upload_to_gofile(f, progress_callback=pcb)),
                    ("Catbox", lambda f: downloader.upload_to_catbox(f, progress_callback=pcb)),
                ]:
                    state["phase"]    = f"☁️ رفع إلى {pname}..."
                    state["provider"] = pname
                    await msg.edit(embed=build_em())
                    link = await pfn(final)
                    if link:
                        prov = pname
                        break

                if link:
                    state["phase"]    = "✅ اكتملت"
                    state["provider"] = prov
                    state["link"]     = link
                    state["color"]    = C_GREEN
                else:
                    state["phase"] = "❌ فشل رفع الملف"
                    state["color"] = C_RED

                await msg.edit(embed=build_em())

            downloader.cleanup(final)
        else:
            state["phase"] = "❌ فشل التحميل — لم يُعثر على الصور"
            state["color"] = C_RED
            await msg.edit(embed=build_em())

    except CloudflareBlockedError:
        state["phase"] = "⛔ محجوب بـ Cloudflare"
        state["color"] = C_RED
        await msg.edit(embed=build_em())
        await interaction.followup.send(embed=discord.Embed(
            title="⛔ lekmanga.net — التحميل غير متاح",
            description=(
                "**lekmanga.net** يستخدم **Cloudflare Bot Management** الذي يحجب جميع "
                "الطلبات الآلية على صفحات القراءة، بما فيها المتصفحات المُحاكاة.\n\n"
                "✅ **ما يعمل بشكل طبيعي:**\n"
                "• تتبع الفصول الجديدة (`/track`)\n"
                "• إشعارات الفصول عبر الرادار\n\n"
                "❌ **ما لا يمكن تجاوزه حالياً:**\n"
                "• تحميل صور الفصول من lekmanga.net\n\n"
                "**بديل مقترح:** استخدم رابط المانجا من موقع آخر مدعوم "
                "(MangaDex, Asura, Vortex, Naver)."
            ),
            color=C_RED,
        ), ephemeral=True)

    except Exception as e:
        state["phase"] = f"❌ خطأ: {str(e)[:80]}"
        state["color"] = C_RED
        try:
            await msg.edit(embed=build_em())
        except Exception:
            pass
        import traceback
        traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════
#  أوامر عامة
# ══════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="status", description="حالة البوت والخدمات")
@user_only()
async def status_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    rank    = await get_rank(interaction.user.id)
    uptime  = str(datetime.datetime.now(datetime.timezone.utc) - BOT_START_TIME).split(".")[0]
    trackers = await database.get_tracker_count()
    users    = await database.get_user_count()

    em = discord.Embed(
        title="📊 حالة النظام",
        color=C_BLUE,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    em.add_field(name="🤖 البوت",       value="🟢 يعمل",                      inline=True)
    em.add_field(name="🧠 Gemini AI",   value="🟢 متصل",                      inline=True)
    em.add_field(name="📡 الرادار",     value=f"🟢 {trackers} متتبّع",        inline=True)
    em.add_field(name="⏱️ وقت التشغيل", value=f"`{uptime}`",                  inline=True)
    em.add_field(name="👥 المستخدمون",  value=f"`{users}` مستخدم",            inline=True)
    em.add_field(name="🎖️ رتبتك",      value=RANK_LABELS.get(rank, "?"),     inline=True)
    em.set_footer(text="Cat-Bi • Manga & Manhwa Bot")
    await interaction.followup.send(embed=em)


@bot.tree.command(name="help", description="قائمة الأوامر المتاحة")
@user_only()
async def help_cmd(interaction: discord.Interaction):
    rank = await get_rank(interaction.user.id)
    em = discord.Embed(
        title="📖 أوامر Cat-Bi",
        color=C_PURPLE,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    em.add_field(name="🔍 بحث", value="`/search` — بحث عن مانجا وفتح لوحة التحكم", inline=False)
    em.add_field(name="📊 حالة", value="`/status` — حالة البوت والخدمات", inline=False)
    em.add_field(name="🧠 Gemini AI", value=f"راسل في قناة <#{Config.GEMINI_CHANNEL_ID}> أو منشنني مباشرة", inline=False)
    em.add_field(name="🗑️ مسح السجل", value="`/clear_history` — مسح محادثتك مع Gemini AI", inline=False)

    if rank >= 2:
        em.add_field(name="📖 VIP — مانجا", value=(
            "`/manga_panel` — لوحة تحكم لتحميل الفصول\n"
            "`/download_direct` — تحميل فصل برابطه\n"
            "`/stitch_drive` — SmartStitch من Google Drive\n"
            "`/providers` — المواقع المدعومة"
        ), inline=False)

    if rank >= 3:
        em.add_field(name="👑 Owner", value=(
            "`/user_add` `/user_remove` `/user_list`\n"
            "`/track_add` `/track_list` `/track_remove`\n"
            "`/add_site` `/remove_site` `/list_sites`"
        ), inline=False)

    em.set_footer(text="Cat-Bi • Manga & Manhwa Bot")
    await interaction.response.send_message(embed=em, ephemeral=True)


@bot.tree.command(name="providers", description="[VIP] قائمة المواقع المدعومة")
@vip_only()
async def list_providers(interaction: discord.Interaction):
    await interaction.response.defer()
    custom_sites = await database.get_custom_sites()
    em = discord.Embed(
        title="🌐 المواقع المدعومة",
        color=C_TEAL,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    em.add_field(name="📚 API مخصص / رسمي", inline=False, value=(
        "MangaDex • Comick • MangaFire • MangaPlus • Bato\n"
        "Webtoons • Naver • AsuraScans • WeebCentral • TCBScans\n"
        "VortexScans • MangaPill • Manganato"
    ))
    em.add_field(name="🎌 RAW الأصلية", inline=False, value=(
        "Bilibili Manga • Kakao Page • LINE Manga\n"
        "AC.QQ • Kuaikan • Piccoma • iQiyi Manhua"
    ))
    em.add_field(name="🇸🇦 عربية", inline=False, value=(
        "**LekManga** • Mangalek • 3asq • Manga-ar • Gmanga • Arabsama • وغيرها"
    ))
    em.add_field(name="⚡ WordPress Madara (150+ موقع)", inline=False, value=(
        "Flamescans • Reaperscans • Toonily • Zinmanga • Manhwaclan\n"
        "Leviatanscans • Nightscans • وأكثر من 150 موقع آخر"
    ))
    em.add_field(name="🤖 Generic + Gemini AI", inline=False, value=(
        "أي موقع آخر → Generic أولاً → Gemini AI كخط دفاع أخير!"
    ))
    if custom_sites:
        custom_txt = "  ".join(f"`{d[0]}`" for d in custom_sites[:20])
        em.add_field(name=f"➕ مواقع مضافة ({len(custom_sites)})", value=custom_txt[:1020], inline=False)
    em.set_footer(text="Cat-Bi • يدعم أي رابط مانجا تقريباً!")
    await interaction.followup.send(embed=em)


# ══════════════════════════════════════════════════════════════════════════
#  Owner commands
# ══════════════════════════════════════════════════════════════════════════
@bot.command()
async def sync(ctx):
    if Config.is_allowed(ctx.author.id):
        synced = await bot.tree.sync()
        await ctx.send(f"✅ تمت مزامنة {len(synced)} أمر.")
        await database.log_event("OK", f"Commands synced by {ctx.author.id}")


if __name__ == "__main__":
    if not Config.DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN مفقود")
        sys.exit(1)
    if not Config.GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY مفقود")
        sys.exit(1)
    try:
        port = int(os.environ.get("PORT", 8080))
        print("Starting Web Panel...")
        keep_alive(bot=None, db=database, port=port)
        print("Starting Bot...")
        bot.run(Config.DISCORD_TOKEN)
    except Exception as e:
        import traceback
        print(f"FATAL: {e}")
        traceback.print_exc()
