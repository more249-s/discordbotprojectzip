import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import io
import os
import sys
import aiohttp
import datetime

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from config import Config
import database
from gemini_client import GeminiClient
from binance_client import BinanceMonitor
from keep_alive import keep_alive
from manga_downloader import MangaDownloader
from providers.manager import ProviderManager

# ── ألوان موحدة ───────────────────────────────────────────────────────────
C_BLUE   = discord.Color.from_rgb(88, 101, 242)
C_GREEN  = discord.Color.from_rgb(87, 242, 135)
C_RED    = discord.Color.from_rgb(237, 66, 69)
C_GOLD   = discord.Color.from_rgb(255, 184, 0)
C_TEAL   = discord.Color.from_rgb(32, 178, 170)
C_GREY   = discord.Color.from_rgb(153, 170, 181)
C_ORANGE = discord.Color.from_rgb(255, 127, 0)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot          = commands.Bot(command_prefix="!", intents=intents)
gemini       = GeminiClient()
binance_mon  = BinanceMonitor(bot)
downloader   = MangaDownloader()
provider_mgr = ProviderManager()


async def setup_hook():
    await database.init_db()
    await bot.load_extension("radar")

bot.setup_hook = setup_hook


# ── جاهز ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="سوق العملات الرقمية 💰")
    )
    print("Syncing slash commands...")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync: {e}")
    await binance_mon.start()
    binance_check_loop.start()
    print("Bot ready.")


# ── رسائل Gemini ──────────────────────────────────────────────────────────
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id == Config.GEMINI_CHANNEL_ID or bot.user.mentioned_in(message):
        async with message.channel.typing():
            prompt = message.content.replace(f'<@!{bot.user.id}>', '').replace(f'<@{bot.user.id}>', '').strip()
            image_data = None
            if message.attachments:
                for att in message.attachments:
                    if any(att.filename.lower().endswith(e) for e in ['png','jpg','jpeg','webp','gif']):
                        async with aiohttp.ClientSession() as s:
                            async with s.get(att.url) as r:
                                if r.status == 200:
                                    image_data = {'mime_type': att.content_type, 'data': await r.read()}
                                    break
            resp = await gemini.get_response(message.author.id, prompt, image_data)
            if len(resp) > 2000:
                for i in range(0, len(resp), 2000):
                    await message.reply(resp[i:i+2000])
            else:
                await message.reply(resp)
    await bot.process_commands(message)


# ── مراقبة Binance ────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def binance_check_loop():
    for d in await binance_mon.check_deposits():
        await notify_transaction(d, "إيداع جديد 💰", C_GREEN)
    for w in await binance_mon.check_withdrawals():
        await notify_transaction(w, "سحب جديد ⚠️", C_RED)

    for alert_id, user_id, symbol, target_price, condition in await database.get_active_alerts():
        current = await binance_mon.get_symbol_price(symbol)
        if not current:
            continue
        current = float(current)
        triggered = (condition == "above" and current >= target_price) or (condition == "below" and current <= target_price)
        if triggered:
            user = await bot.fetch_user(user_id)
            if user:
                embed = discord.Embed(
                    title="🔔 تنبيه سعر وصل!",
                    description=(
                        f"وصل سعر **{symbol}** إلى `${current:,.2f}`\n"
                        f"كان تنبيهك: `{condition}` `${target_price:,.2f}`"
                    ),
                    color=C_GOLD,
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                embed.set_footer(text="Cat-Bi Binance Monitor")
                await user.send(embed=embed)
            await database.deactivate_alert(alert_id)


async def notify_transaction(data, title, color):
    owner_id = Config.ALLOWED_USER_IDS[0] if Config.ALLOWED_USER_IDS else None
    mention  = f"<@{owner_id}>" if owner_id else ""
    embed = discord.Embed(title=title, color=color, timestamp=datetime.datetime.now(datetime.timezone.utc))
    embed.add_field(name="المبلغ",  value=f"`{data['amount']} {data.get('coin', data.get('asset',''))}`",  inline=True)
    embed.add_field(name="الحالة",  value="✅ مكتمل", inline=True)
    tx_id = data.get('txId') or data.get('id')
    if tx_id:
        embed.add_field(name="TxID", value=f"`{tx_id}`", inline=False)
    embed.set_footer(text="Cat-Bi Binance Monitor")
    ch = bot.get_channel(Config.ERROR_CHANNEL_ID or Config.GEMINI_CHANNEL_ID)
    if ch:
        await ch.send(content=f"{mention}", embed=embed)


# ─────────────────────────────────────────────────────────────────────────────
#  أوامر Binance
# ─────────────────────────────────────────────────────────────────────────────
@bot.tree.command(name="price", description="سعر عملة رقمية الآن (مثال: BTCUSDT)")
@app_commands.describe(symbol="رمز العملة")
async def price(interaction: discord.Interaction, symbol: str):
    await interaction.response.defer()
    p = await binance_mon.get_symbol_price(symbol)
    if p:
        embed = discord.Embed(
            title=f"💹 {symbol.upper()}",
            description=f"**السعر الحالي:**  `${float(p):,.4f}`",
            color=C_TEAL,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_footer(text="Cat-Bi • Binance")
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(embed=discord.Embed(
            title="❌ لم يُعثر على العملة",
            description="تأكد من الرمز، مثال: `BTCUSDT`",
            color=C_RED
        ))


@bot.tree.command(name="balance", description="رصيد حساب Binance (Owner فقط)")
async def balance(interaction: discord.Interaction):
    if not Config.is_allowed(interaction.user.id):
        return await interaction.response.send_message("❌ هذا الأمر مخصص للمالك فقط.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    balances = await binance_mon.get_account_balances()
    if balances is None:
        return await interaction.followup.send(embed=discord.Embed(
            title="❌ فشل جلب الرصيد",
            description="تأكد من صحة بيانات API.",
            color=C_RED
        ))
    if not balances:
        return await interaction.followup.send(embed=discord.Embed(
            title="💼 المحفظة فارغة",
            description="لا توجد عملات بقيمة حالياً.",
            color=C_GREY
        ))
    embed = discord.Embed(
        title="💰 رصيد Binance",
        color=C_GOLD,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    for b in balances:
        embed.add_field(
            name=f"{b['asset']} ({b.get('type','Spot')})",
            value=f"متاح: `{b['free']}`\nمحجوز: `{b['locked']}`",
            inline=True
        )
    embed.set_footer(text="Cat-Bi • Binance Account")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="status", description="حالة البوت والخدمات")
async def status(interaction: discord.Interaction):
    await interaction.response.defer()
    p = await binance_mon.get_symbol_price("BTCUSDT")
    binance_ok = bool(p)
    embed = discord.Embed(
        title="📊 حالة النظام",
        color=C_BLUE,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="🤖 البوت",           value="🟢 يعمل",                        inline=True)
    embed.add_field(name="🧠 Gemini AI",        value="🟢 متصل",                        inline=True)
    embed.add_field(name="📈 Binance",          value="🟢 متصل" if binance_ok else "🔴 غير متصل", inline=True)
    embed.set_footer(text="Cat-Bi System Status")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="alert_add", description="إضافة تنبيه لسعر عملة")
@app_commands.describe(symbol="رمز العملة (مثال: BTCUSDT)", price="السعر المستهدف", condition="نوع التنبيه")
@app_commands.choices(condition=[
    app_commands.Choice(name="فوق السعر (Above)", value="above"),
    app_commands.Choice(name="تحت السعر (Below)", value="below"),
])
async def alert_add(interaction: discord.Interaction, symbol: str, price: float, condition: str):
    await database.add_price_alert(interaction.user.id, symbol, price, condition)
    embed = discord.Embed(
        title="🔔 تنبيه أضيف بنجاح",
        description=(
            f"**العملة:** `{symbol.upper()}`\n"
            f"**السعر:** `${price:,.2f}`\n"
            f"**النوع:** `{condition}`"
        ),
        color=C_GREEN
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="alert_list", description="تنبيهاتك النشطة")
async def alert_list(interaction: discord.Interaction):
    alerts = await database.get_user_alerts(interaction.user.id)
    if not alerts:
        return await interaction.response.send_message(embed=discord.Embed(
            title="📭 لا توجد تنبيهات", description="أضف تنبيهاً بـ `/alert_add`", color=C_GREY
        ), ephemeral=True)
    embed = discord.Embed(title="🔔 تنبيهاتك النشطة", color=C_BLUE, timestamp=datetime.datetime.now(datetime.timezone.utc))
    desc  = ""
    for a_id, sym, pr, cond in alerts:
        icon = "📈" if cond == "above" else "📉"
        desc += f"{icon} **`{a_id}`** — {sym} {cond} `${pr:,.2f}`\n"
    embed.description = desc
    embed.set_footer(text="استخدم /alert_remove لحذف تنبيه")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="alert_remove", description="حذف تنبيه بالـ ID")
@app_commands.describe(alert_id="رقم التنبيه من /alert_list")
async def alert_remove(interaction: discord.Interaction, alert_id: int):
    await database.remove_alert(alert_id, interaction.user.id)
    await interaction.response.send_message(embed=discord.Embed(
        title="🗑️ تم حذف التنبيه",
        description=f"تمت إزالة التنبيه رقم `{alert_id}`",
        color=C_GREEN
    ), ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
#  أوامر المانجا
# ─────────────────────────────────────────────────────────────────────────────
@bot.tree.command(name="download", description="تحميل فصل مانجا مع SmartStitch")
@app_commands.describe(url="رابط الفصل", title="اسم الملف (اختياري)")
async def download(interaction: discord.Interaction, url: str, title: str = "Manga_Chapter"):
    if not Config.is_allowed(interaction.user.id):
        return await interaction.response.send_message("❌ غير مسموح.", ephemeral=True)

    DISCORD_LIMIT_MB = 10.0
    await interaction.response.defer()

    state = {
        "phase":    "🔄 تهيئة",
        "progress": downloader.create_progress_bar(0, 1),
        "counter":  "0/1",
        "detail":   "جاري التجهيز...",
        "size":     "—",
        "provider": "—",
        "link":     None,
        "color":    C_BLUE,
    }

    def build_embed():
        em = discord.Embed(
            title="📦 لوحة تحميل الفصل",
            color=state["color"],
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        em.description = f"**العنوان:** `{title}`\n**الصيغة:** ZIP + SmartStitch"
        em.add_field(name="⚙️ الحالة",    value=state["phase"],    inline=False)
        em.add_field(name="📊 التقدم",    value=f"`{state['progress']}`  `{state['counter']}`", inline=False)
        em.add_field(name="📝 التفاصيل",  value=state["detail"],   inline=False)
        em.add_field(name="📁 الحجم",     value=state["size"],     inline=True)
        em.add_field(name="☁️ الوجهة",    value=state["provider"], inline=True)
        if state["link"]:
            em.add_field(name="🔗 الرابط", value=f"[اضغط هنا]({state['link']})", inline=False)
        em.set_footer(text="Cat-Bi Manga System")
        return em

    def link_view(link):
        v = discord.ui.View()
        v.add_item(discord.ui.Button(label="📥 تحميل", style=discord.ButtonStyle.link, url=link))
        return v

    msg      = await interaction.followup.send(embed=build_embed())
    last_upd = 0.0

    async def pcb(cur, tot, txt):
        nonlocal last_upd
        state["phase"]    = txt
        state["progress"] = downloader.create_progress_bar(cur, tot)
        state["counter"]  = f"{cur}/{tot}"
        state["detail"]   = "العملية جارية..."
        now = asyncio.get_running_loop().time()
        if now - last_upd < 1.25 and cur < tot:
            return
        last_upd = now
        try:
            await msg.edit(embed=build_embed())
        except Exception:
            pass

    try:
        final = await downloader.download_and_stitch(url, title, progress_callback=pcb)

        if final and os.path.exists(final):
            size_mb = os.path.getsize(final) / (1024 * 1024)
            state["size"] = f"{size_mb:.2f} MB"

            if size_mb <= DISCORD_LIMIT_MB:
                state["phase"]    = "📤 إرسال إلى Discord"
                state["provider"] = "Discord"
                state["progress"] = downloader.create_progress_bar(1, 1)
                state["counter"]  = "1/1"
                state["detail"]   = "الحجم صغير، يُرسل مباشرةً."
                await msg.edit(embed=build_embed())
                await interaction.followup.send(
                    content=f"✅ {interaction.user.mention} الفصل جاهز!",
                    file=discord.File(final)
                )
                state["phase"] = "✅ اكتملت"
                state["color"] = C_GREEN
                state["detail"] = "تم الإرسال مباشرة."
                await msg.edit(embed=build_embed())
            else:
                # Drive → Gofile → Catbox
                for provider_name, upload_fn in [
                    ("Google Drive", lambda f: downloader.upload_to_gdrive(f, os.path.basename(f), progress_callback=pcb)),
                    ("Gofile",       lambda f: downloader.upload_to_gofile(f, progress_callback=pcb)),
                    ("Catbox",       lambda f: downloader.upload_to_catbox(f, progress_callback=pcb)),
                ]:
                    state["phase"]    = f"☁️ رفع إلى {provider_name}"
                    state["provider"] = provider_name
                    state["progress"] = downloader.create_progress_bar(0, 100)
                    state["counter"]  = "0/100"
                    state["detail"]   = f"حجم الملف أكبر من {DISCORD_LIMIT_MB:.0f} MB، جاري الرفع..."
                    await msg.edit(embed=build_embed())
                    link = await upload_fn(final)
                    if link:
                        state["phase"]    = "✅ اكتملت"
                        state["provider"] = provider_name
                        state["link"]     = link
                        state["color"]    = C_GREEN
                        state["progress"] = downloader.create_progress_bar(100, 100)
                        state["counter"]  = "100/100"
                        state["detail"]   = "تم الرفع بنجاح."
                        await msg.edit(embed=build_embed(), view=link_view(link))
                        await interaction.followup.send(
                            content=f"✅ {interaction.user.mention} الفصل جاهز عبر **{provider_name}**!",
                            embed=discord.Embed(
                                title="📥 رابط التحميل",
                                description=f"[اضغط هنا للتحميل]({link})\n**المزود:** {provider_name}",
                                color=C_GREEN
                            )
                        )
                        break
                else:
                    state["phase"]  = "❌ فشل الرفع"
                    state["color"]  = C_RED
                    state["detail"] = "فشل الرفع على Drive وGofile وCatbox."
                    await msg.edit(embed=build_embed())

            downloader.cleanup(final)
        else:
            state["phase"]  = "❌ فشل التحميل"
            state["color"]  = C_RED
            state["detail"] = "فشل تحميل الصور أو SmartStitch. تأكد من الرابط."
            await msg.edit(embed=build_embed())

    except Exception as e:
        state["phase"]  = "❌ خطأ غير متوقع"
        state["color"]  = C_RED
        state["detail"] = str(e)[:900]
        try:
            await msg.edit(embed=build_embed())
        except Exception:
            await interaction.followup.send(f"❌ خطأ: {e}")
        import traceback; traceback.print_exc()


@bot.tree.command(name="clean", description="تبييض المانجا: إزالة النصوص من الصورة")
@app_commands.describe(image="الصورة المراد تنظيفها", prompt="تعليمات إضافية (اختياري)")
async def clean_image_cmd(interaction: discord.Interaction, image: discord.Attachment,
                          prompt: str = "قم بمسح وتنظيف جميع النصوص من هذه الصورة."):
    if not any(image.filename.lower().endswith(e) for e in ['png','jpg','jpeg','webp']):
        return await interaction.response.send_message("❌ يرجى إرفاق صورة بصيغة صحيحة.", ephemeral=True)
    await interaction.response.defer()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(image.url) as r:
                if r.status != 200:
                    return await interaction.followup.send("❌ فشل تحميل الصورة.")
                image_data = {'mime_type': image.content_type, 'data': await r.read()}

        response = await gemini.clean_image(prompt, image_data)
        image_out  = None
        text_out   = ""
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    image_out = part.inline_data.data
                elif hasattr(part, 'text') and part.text:
                    text_out += part.text

        if image_out:
            await interaction.followup.send(
                content=text_out or "✅ تم التنظيف!",
                file=discord.File(io.BytesIO(image_out), filename="clean_manga.png")
            )
        else:
            await interaction.followup.send(content=response.text)
    except Exception as e:
        await interaction.followup.send(f"❌ خطأ: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  أمر البحث عن المانجا
# ─────────────────────────────────────────────────────────────────────────────
@bot.tree.command(name="search", description="ابحث عن مانجا بالاسم")
@app_commands.describe(query="اسم المانجا أو الكلمة المفتاحية")
async def search_manga(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    results = await provider_mgr.search_manga(query, limit=8)
    if not results:
        return await interaction.followup.send(embed=discord.Embed(
            title="🔍 لا نتائج",
            description=f"لم يُعثر على نتائج لـ `{query}`.",
            color=C_RED
        ))

    embed = discord.Embed(
        title=f"🔍 نتائج البحث: {query}",
        color=C_BLUE,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.set_footer(text="المصدر: MangaDex • Cat-Bi Manga Search")

    view = discord.ui.View()
    for i, r in enumerate(results[:8]):
        status_icon = {"ongoing": "🟢", "completed": "✅", "hiatus": "🟡", "cancelled": "🔴"}.get(r["status"], "⚪")
        desc_text   = r["description"][:120] + "..." if len(r["description"]) > 120 else r["description"]
        embed.add_field(
            name=f"{i+1}. {r['title']} {status_icon}",
            value=f"{desc_text}\n[📖 اقرأ الآن]({r['url']})" if desc_text else f"[📖 اقرأ الآن]({r['url']})",
            inline=False
        )
        if i < 5:
            view.add_item(discord.ui.Button(
                label=f"{i+1}. {r['title'][:40]}",
                style=discord.ButtonStyle.link,
                url=r["url"],
                row=i // 2
            ))

    if results[0].get("cover"):
        embed.set_thumbnail(url=results[0]["cover"])

    await interaction.followup.send(embed=embed, view=view)


# ─────────────────────────────────────────────────────────────────────────────
#  أمر التحميل الجماعي (Batch)
# ─────────────────────────────────────────────────────────────────────────────
@bot.tree.command(name="batch", description="تحميل عدة فصول دفعة واحدة (مثال: 1-5 أو 1,3,5)")
@app_commands.describe(
    series_url="رابط صفحة المانجا الرئيسية",
    chapters="نطاق الفصول: مثال 1-5 أو 1,3,7 أو 1-10",
    title="اسم المانجا (اختياري)"
)
async def batch_download(interaction: discord.Interaction, series_url: str,
                         chapters: str, title: str = "Manga"):
    if not Config.is_allowed(interaction.user.id):
        return await interaction.response.send_message("❌ هذا الأمر مخصص للمالك فقط.", ephemeral=True)

    await interaction.response.defer()

    # تحليل نطاق الفصول
    chapter_nums = []
    try:
        if "-" in chapters and "," not in chapters:
            parts = chapters.split("-")
            start, end = int(parts[0].strip()), int(parts[1].strip())
            chapter_nums = list(range(start, end + 1))
        elif "," in chapters:
            chapter_nums = [int(x.strip()) for x in chapters.split(",")]
        else:
            chapter_nums = [int(chapters.strip())]
    except Exception:
        return await interaction.followup.send(embed=discord.Embed(
            title="❌ صيغة خاطئة",
            description="استخدم: `1-5` أو `1,3,5` أو `7`",
            color=C_RED
        ))

    if len(chapter_nums) > 20:
        return await interaction.followup.send(embed=discord.Embed(
            title="❌ عدد كبير جداً",
            description="الحد الأقصى 20 فصل في المرة الواحدة.",
            color=C_RED
        ))

    embed = discord.Embed(
        title=f"📦 تحميل جماعي: {title}",
        description=f"**الفصول المطلوبة:** `{chapters}`\n**العدد:** `{len(chapter_nums)}` فصل",
        color=C_BLUE,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="⚙️ الحالة", value="🔍 جاري جلب قائمة الفصول...", inline=False)
    embed.set_footer(text="Cat-Bi Batch Download")
    msg = await interaction.followup.send(embed=embed)

    # جلب كل الفصول
    all_chapters = await provider_mgr.get_all_chapters(series_url)
    if not all_chapters:
        embed.color = C_RED
        embed.set_field_at(0, name="❌ خطأ", value="فشل جلب قائمة الفصول. تأكد من الرابط.", inline=False)
        return await msg.edit(embed=embed)

    # تحديد الفصول المتاحة
    available = {int(k): v for k, v in all_chapters.items() if int(k) in chapter_nums}
    missing   = [n for n in chapter_nums if n not in available]

    embed.set_field_at(0, name="⚙️ الحالة",
        value=f"✅ وُجد `{len(available)}/{len(chapter_nums)}` فصل. بدء التحميل...", inline=False)
    if missing:
        embed.add_field(name="⚠️ غير متاح", value=f"الفصول: `{missing}`", inline=False)
    await msg.edit(embed=embed)

    # تحميل الفصول الواحدة تلو الأخرى
    success, failed = [], []
    for i, (ch_num, ch_url) in enumerate(sorted(available.items())):
        ch_title = f"{title}_Ch{ch_num:03.0f}"
        embed.set_field_at(0, name="⚙️ الحالة",
            value=f"📥 تحميل الفصل `{ch_num}` ({i+1}/{len(available)})...", inline=False)
        await msg.edit(embed=embed)
        try:
            final = await downloader.download_and_stitch(ch_url, ch_title)
            if final and os.path.exists(final):
                size_mb = os.path.getsize(final) / (1024 * 1024)
                if size_mb <= 10.0:
                    await interaction.followup.send(
                        content=f"✅ فصل `{ch_num}` جاهز!",
                        file=discord.File(final)
                    )
                else:
                    link = await downloader.upload_to_gofile(final)
                    if not link:
                        link = await downloader.upload_to_catbox(final)
                    if link:
                        await interaction.followup.send(
                            content=f"✅ فصل `{ch_num}` → [تحميل]({link})"
                        )
                    else:
                        failed.append(ch_num)
                        continue
                downloader.cleanup(final)
                success.append(ch_num)
            else:
                failed.append(ch_num)
        except Exception as e:
            failed.append(ch_num)
            print(f"[Batch] Ch{ch_num} error: {e}")

    # تقرير نهائي
    embed.color  = C_GREEN if not failed else C_GOLD
    embed.set_field_at(0, name="✅ اكتمل",
        value=f"نجح: `{success}`\nفشل: `{failed}`" if failed else f"نجح جميع الفصول: `{success}`",
        inline=False)
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await msg.edit(embed=embed)


# ─────────────────────────────────────────────────────────────────────────────
#  أمر قائمة المزودات المدعومة
# ─────────────────────────────────────────────────────────────────────────────
@bot.tree.command(name="providers", description="قائمة المواقع والمزودات المدعومة")
async def list_providers(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(
        title="🌐 المواقع المدعومة",
        color=C_TEAL,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="📚 API رسمي / مخصص", inline=False, value=(
        "• **MangaDex** — mangadex.org\n"
        "• **Comick** — comick.fun / comick.io\n"
        "• **MangaFire** — mangafire.to\n"
        "• **MangaPlus** — mangaplus.shueisha.co.jp\n"
        "• **Bato** — bato.to\n"
        "• **Webtoons** — webtoons.com\n"
        "• **Naver** — comic.naver.com\n"
        "• **Manganato** — manganato + mangakakalot + ...\n"
        "• **AsuraScans** — asurascans / asuratoon\n"
        "• **WeebCentral** — weebcentral.com\n"
        "• **TCBScans** — tcbscans.me\n"
        "• **VortexScans** — vortexscans.com\n"
        "• **MangaPill** — mangapill.com"
    ))
    embed.add_field(name="🇸🇦 المواقع العربية", inline=False, value=(
        "• Mangalek • 3asq • Manga-ar\n"
        "• Arabsama • Mangaae • Gmanga\n"
        "• Ozulscans • Mangat • وغيرها..."
    ))
    embed.add_field(name="⚡ Madara WordPress (100+ موقع)", inline=False, value=(
        "Flamescans • Reaperscans • Toonily • Zinmanga\n"
        "Manhuaplus • Manhwaclan • Leviatanscans\n"
        "Sushiscan • Nightscans • وأكثر من 100 موقع آخر..."
    ))
    embed.add_field(name="🤖 Generic + Gemini AI", inline=False, value=(
        "أي موقع آخر → يحاول Generic أولاً\n"
        "ثم Gemini AI كخط دفاع أخير!"
    ))
    embed.set_footer(text="Cat-Bi Manga System • يدعم أي رابط تقريباً!")
    await interaction.followup.send(embed=embed)


# ── مزامنة أوامر (أدمن) ──────────────────────────────────────────────────
@bot.command()
async def sync(ctx):
    if Config.is_allowed(ctx.author.id):
        await bot.tree.sync()
        await ctx.send("✅ تمت مزامنة الأوامر.")


if __name__ == "__main__":
    if not Config.DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN مفقود")
    elif not Config.GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY مفقود")
    else:
        try:
            print("Starting Web Server...")
            keep_alive()
            print("Starting Bot...")
            bot.run(Config.DISCORD_TOKEN)
        except Exception as e:
            import traceback
            print(f"FATAL: {e}")
            traceback.print_exc()
