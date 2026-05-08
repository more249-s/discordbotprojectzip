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
from user_system import owner_only, vip_only, user_only, get_rank, RANK_LABELS, RANK_COLORS

# ── ألوان موحدة ───────────────────────────────────────────────────────────
C_BLUE   = discord.Color.from_rgb(88, 101, 242)
C_GREEN  = discord.Color.from_rgb(87, 242, 135)
C_RED    = discord.Color.from_rgb(237, 66, 69)
C_GOLD   = discord.Color.from_rgb(255, 184, 0)
C_TEAL   = discord.Color.from_rgb(32, 178, 170)
C_GREY   = discord.Color.from_rgb(153, 170, 181)
C_ORANGE = discord.Color.from_rgb(255, 127, 0)
C_INDIGO = discord.Color.from_rgb(99, 102, 241)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot          = commands.Bot(command_prefix="!", intents=intents)
gemini       = GeminiClient()
binance_mon  = BinanceMonitor(bot)
downloader   = MangaDownloader()
provider_mgr = ProviderManager()

# Cache for user registration to avoid DB hits on every message
registered_cache = set()


async def setup_hook():
    await database.init_db()
    await bot.load_extension("radar")

bot.setup_hook = setup_hook


# ── جاهز ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print("Syncing slash commands...")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync: {e}")
    await binance_mon.start()
    binance_check_loop.start()
    print("Bot ready.")


# ── Gemini AI — رسائل ─────────────────────────────────────────────────────
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # التسجيل التلقائي عند أول رسالة
    if message.author.id not in registered_cache:
        await get_rank(message.author.id, auto_register=True)
        registered_cache.add(message.author.id)

        return

    is_gemini_ch  = message.channel.id == Config.GEMINI_CHANNEL_ID
    is_mentioned  = bot.user.mentioned_in(message)
    if is_gemini_ch or is_mentioned:
        # فحص صلاحية المستخدم
        rank = await get_rank(message.author.id)
        if rank < 2:
            if is_mentioned:
                await message.reply(
                    "❌ ليس لديك صلاحية استخدام Gemini AI.\n"
                    "تواصل مع المالك للحصول على وصول.",
                    mention_author=False
                )
            return

        async with message.channel.typing():
            prompt = (message.content
                      .replace(f'<@!{bot.user.id}>', '')
                      .replace(f'<@{bot.user.id}>', '')
                      .strip())
            image_data = None
            if message.attachments:
                for att in message.attachments:
                    if any(att.filename.lower().endswith(e)
                           for e in ['png', 'jpg', 'jpeg', 'webp', 'gif']):
                        async with aiohttp.ClientSession() as s:
                            async with s.get(att.url) as r:
                                if r.status == 200:
                                    image_data = {
                                        'mime_type': att.content_type,
                                        'data': await r.read()
                                    }
                                    break
            resp = await gemini.get_response(message.author.id, prompt, image_data)
            if len(resp) > 2000:
                for i in range(0, len(resp), 2000):
                    await message.reply(resp[i:i + 2000])
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
        current   = float(current)
        triggered = ((condition == "above" and current >= target_price) or
                     (condition == "below" and current <= target_price))
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
    embed = discord.Embed(
        title=title, color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(
        name="المبلغ",
        value=f"`{data['amount']} {data.get('coin', data.get('asset',''))}`",
        inline=True
    )
    embed.add_field(name="الحالة", value="✅ مكتمل", inline=True)
    tx_id = data.get('txId') or data.get('id')
    if tx_id:
        embed.add_field(name="TxID", value=f"`{tx_id}`", inline=False)
    embed.set_footer(text="Cat-Bi Binance Monitor")
    ch = bot.get_channel(Config.ERROR_CHANNEL_ID or Config.GEMINI_CHANNEL_ID)
    if ch:
        await ch.send(content=mention, embed=embed)


# ═════════════════════════════════════════════════════════════════════════════
#  نظام إدارة المستخدمين — Owner فقط
# ═════════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="user_add", description="[Owner] إضافة مستخدم أو ترقيته")
@app_commands.describe(
    user="المستخدم",
    rank="الرتبة: 1=User  2=VIP",
    note="ملاحظة (اختياري)"
)
@app_commands.choices(rank=[
    app_commands.Choice(name="1 — User  (بحث فقط)", value=1),
    app_commands.Choice(name="2 — VIP   (تحميل مانجا + كريبتو)", value=2),
])
@owner_only()
async def user_add_cmd(
    interaction: discord.Interaction,
    user: discord.User,
    rank: int,
    note: str = ""
):
    await database.set_user_rank(user.id, rank, note)
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


@bot.tree.command(name="user_remove", description="[Owner] إزالة مستخدم من القائمة")
@app_commands.describe(user="المستخدم المراد إزالته")
@owner_only()
async def user_remove_cmd(interaction: discord.Interaction, user: discord.User):
    await database.remove_user(user.id)
    em = discord.Embed(
        title="🗑️ تم إزالة المستخدم",
        description=f"{user.mention} لم يعد مسجلاً في البوت.",
        color=C_RED,
    )
    await interaction.response.send_message(embed=em, ephemeral=True)


@bot.tree.command(name="user_list", description="[Owner] قائمة المستخدمين المسموح لهم")
@owner_only()
async def user_list_cmd(interaction: discord.Interaction):
    rows = await database.get_all_users()
    em   = discord.Embed(
        title="👥 قائمة المستخدمين",
        color=C_INDIGO,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    # صف الـ Owners
    owners_txt = "\n".join(f"<@{uid}>" for uid in Config.ALLOWED_USER_IDS) or "—"
    em.add_field(name="👑 Owner (مدمج)", value=owners_txt, inline=False)

    if rows:
        vip_lines  = []
        user_lines = []
        for uid, rank, note, added in rows:
            line = f"<@{uid}>"
            if note:
                line += f"  —  {note}"
            if rank >= 2:
                vip_lines.append(line)
            else:
                user_lines.append(line)
        if vip_lines:
            em.add_field(name="⭐ VIP", value="\n".join(vip_lines) or "—", inline=False)
        if user_lines:
            em.add_field(name="👤 User", value="\n".join(user_lines) or "—", inline=False)
    else:
        em.description = "لا يوجد مستخدمون مسجّلون غير الـ Owner."

    em.set_footer(text=f"المجموع: {len(rows)} مستخدم مسجّل  ·  Cat-Bi")
    await interaction.response.send_message(embed=em, ephemeral=True)


# ═════════════════════════════════════════════════════════════════════════════
#  أوامر عامة — User+
# ═════════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="status", description="حالة البوت والخدمات")
@user_only()
async def status_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    rank    = await get_rank(interaction.user.id)
    p       = await binance_mon.get_symbol_price("BTCUSDT")
    bin_ok  = bool(p)
    em = discord.Embed(
        title="📊 حالة النظام",
        color=C_BLUE,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    em.add_field(name="🤖 البوت",    value="🟢 يعمل",                             inline=True)
    em.add_field(name="🧠 Gemini",   value="🟢 متصل",                             inline=True)
    em.add_field(name="📈 Binance",  value="🟢 متصل" if bin_ok else "🔴 غير متصل", inline=True)
    em.add_field(name="🎖️ رتبتك",   value=RANK_LABELS.get(rank, "?"),             inline=True)
    em.set_footer(text="Cat-Bi System Status")
    await interaction.followup.send(embed=em)


@bot.tree.command(name="price", description="سعر عملة رقمية الآن (مثال: BTCUSDT)")
@app_commands.describe(symbol="رمز العملة")
@user_only()
async def price_cmd(interaction: discord.Interaction, symbol: str):
    await interaction.response.defer()
    p = await binance_mon.get_symbol_price(symbol.upper())
    if p:
        em = discord.Embed(
            title=f"💹 {symbol.upper()}",
            description=f"**السعر الحالي:**  `${float(p):,.4f}`",
            color=C_TEAL,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        em.set_footer(text="Cat-Bi • Binance")
        await interaction.followup.send(embed=em)
    else:
        await interaction.followup.send(embed=discord.Embed(
            title="❌ لم يُعثر على العملة",
            description="تأكد من الرمز، مثال: `BTCUSDT`",
            color=C_RED,
        ))


@bot.tree.command(name="search", description="Search for manga and open the control panel")
@app_commands.describe(query="Manga name or keyword")
@user_only()
async def search_manga(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    results = await provider_mgr.search_manga(query, limit=10)
    if not results:
        return await interaction.followup.send(embed=discord.Embed(
            title="🔍 No Results",
            description=f"No manga found for `{query}`.",
            color=C_RED,
        ))

    em = discord.Embed(
        title=f"🔍 Search Results: {query}",
        description="Choose a manga to open its control panel:",
        color=C_BLUE,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )

    class SearchDropdown(discord.ui.Select):
        def __init__(self, items):
            options = [
                discord.SelectOption(label=r['title'][:100], description=f"Status: {r['status']}", value=r['url'], emoji="📖")
                for r in items
            ]
            super().__init__(placeholder="Choose a manga...", options=options)

        async def callback(self, i: discord.Interaction):
            await i.response.defer()
            # استدعاء manga_panel_cmd من radar
            radar_cog = bot.get_cog("RadarCog")
            if radar_cog:
                await radar_cog.manga_panel_cmd(i, self.values[0])
            else:
                await i.followup.send("Radar module not found.", ephemeral=True)

    view = discord.ui.View()
    view.add_item(SearchDropdown(results))

    if results[0].get("cover"):
        em.set_thumbnail(url=results[0]["cover"])

    await interaction.followup.send(embed=em, view=view)


# ═════════════════════════════════════════════════════════════════════════════
#  أوامر Binance — VIP+
# ═════════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="alert_add", description="إضافة تنبيه لسعر عملة")
@app_commands.describe(
    symbol="رمز العملة (مثال: BTCUSDT)",
    price="السعر المستهدف",
    condition="نوع التنبيه"
)
@app_commands.choices(condition=[
    app_commands.Choice(name="فوق السعر (Above)", value="above"),
    app_commands.Choice(name="تحت السعر (Below)", value="below"),
])
@vip_only()
async def alert_add(interaction: discord.Interaction,
                    symbol: str, price: float, condition: str):
    await database.add_price_alert(interaction.user.id, symbol, price, condition)
    em = discord.Embed(
        title="🔔 تنبيه أضيف بنجاح",
        description=(
            f"**العملة:** `{symbol.upper()}`\n"
            f"**السعر:** `${price:,.2f}`\n"
            f"**النوع:** `{condition}`"
        ),
        color=C_GREEN,
    )
    await interaction.response.send_message(embed=em, ephemeral=True)


@bot.tree.command(name="alert_list", description="تنبيهاتك النشطة")
@vip_only()
async def alert_list(interaction: discord.Interaction):
    alerts = await database.get_user_alerts(interaction.user.id)
    if not alerts:
        return await interaction.response.send_message(embed=discord.Embed(
            title="📭 لا توجد تنبيهات",
            description="أضف تنبيهاً بـ `/alert_add`",
            color=C_GREY,
        ), ephemeral=True)
    em   = discord.Embed(title="🔔 تنبيهاتك النشطة", color=C_BLUE,
                         timestamp=datetime.datetime.now(datetime.timezone.utc))
    desc = ""
    for a_id, sym, pr, cond in alerts:
        icon  = "📈" if cond == "above" else "📉"
        desc += f"{icon} **`{a_id}`** — {sym} {cond} `${pr:,.2f}`\n"
    em.description = desc
    em.set_footer(text="استخدم /alert_remove لحذف تنبيه")
    await interaction.response.send_message(embed=em, ephemeral=True)


@bot.tree.command(name="alert_remove", description="حذف تنبيه بالـ ID")
@app_commands.describe(alert_id="رقم التنبيه من /alert_list")
@vip_only()
async def alert_remove(interaction: discord.Interaction, alert_id: int):
    await database.remove_alert(alert_id, interaction.user.id)
    await interaction.response.send_message(embed=discord.Embed(
        title="🗑️ تم حذف التنبيه",
        description=f"تمت إزالة التنبيه رقم `{alert_id}`",
        color=C_GREEN,
    ), ephemeral=True)


# ═════════════════════════════════════════════════════════════════════════════
#  أوامر Binance — Owner فقط
# ═════════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="balance", description="[Owner] رصيد حساب Binance")
@owner_only()
async def balance_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    balances = await binance_mon.get_account_balances()
    if balances is None:
        return await interaction.followup.send(embed=discord.Embed(
            title="❌ فشل جلب الرصيد",
            description="تأكد من صحة بيانات API.",
            color=C_RED,
        ))
    if not balances:
        return await interaction.followup.send(embed=discord.Embed(
            title="💼 المحفظة فارغة",
            description="لا توجد عملات بقيمة حالياً.",
            color=C_GREY,
        ))
    em = discord.Embed(
        title="💰 رصيد Binance",
        color=C_GOLD,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    for b in balances:
        em.add_field(
            name=f"{b['asset']} ({b.get('type','Spot')})",
            value=f"متاح: `{b['free']}`\nمحجوز: `{b['locked']}`",
            inline=True,
        )
    em.set_footer(text="Cat-Bi • Binance Account")
    await interaction.followup.send(embed=em)


# ═════════════════════════════════════════════════════════════════════════════
#  أوامر المانجا — VIP+
# ═════════════════════════════════════════════════════════════════════════════
@bot.tree.command(name="download_direct", description="Directly download a chapter via link")
@app_commands.describe(url="Chapter URL", title="Filename (Optional)")
@vip_only()
async def download_cmd(interaction: discord.Interaction,
                       url: str, title: str = "Manga_Chapter"):
    DISCORD_LIMIT_MB = 10.0
    await interaction.response.defer()

    state = {
        "phase": "🔄 تهيئة",
        "progress": downloader.create_progress_bar(0, 1),
        "counter": "0/1",
        "detail": "جاري التجهيز...",
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
        em.add_field(name="⚙️ الحالة",   value=state["phase"],    inline=False)
        em.add_field(name="📊 التقدم",   value=f"`{state['progress']}`  `{state['counter']}`", inline=False)
        em.add_field(name="📁 الحجم",    value=state["size"],     inline=True)
        em.add_field(name="☁️ الوجهة",   value=state["provider"], inline=True)
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
                for pname, pfn in [
                    ("Gofile", lambda f: downloader.upload_to_gofile(f, progress_callback=pcb)),
                    ("Catbox", lambda f: downloader.upload_to_catbox(f, progress_callback=pcb)),
                ]:
                    state["phase"]    = f"☁️ رفع إلى {pname}"
                    state["provider"] = pname
                    await msg.edit(embed=build_em())
                    link = await pfn(final)
                    if link:
                        state.update({"phase": "✅ اكتملت", "provider": pname,
                                      "link": link, "color": C_GREEN})
                        await msg.edit(embed=build_em())
                        await interaction.followup.send(
                            content=f"✅ {interaction.user.mention} الفصل جاهز!",
                            embed=discord.Embed(
                                title="📥 رابط التحميل",
                                description=f"[اضغط هنا للتحميل]({link})\n**المزود:** {pname}",
                                color=C_GREEN,
                            ),
                        )
                        break
                else:
                    state.update({"phase": "❌ فشل الرفع", "color": C_RED})
                    await msg.edit(embed=build_em())
            downloader.cleanup(final)
        else:
            state.update({"phase": "❌ فشل التحميل", "color": C_RED})
            await msg.edit(embed=build_em())
    except Exception as e:
        state.update({"phase": "❌ خطأ غير متوقع", "color": C_RED,
                      "detail": str(e)[:200]})
        try:
            await msg.edit(embed=build_em())
        except Exception:
            pass
        import traceback; traceback.print_exc()


@bot.tree.command(name="clean", description="[VIP] تبييض المانجا: إزالة النصوص من الصورة")
@app_commands.describe(image="الصورة", prompt="تعليمات إضافية (اختياري)")
@vip_only()
async def clean_image_cmd(interaction: discord.Interaction,
                          image: discord.Attachment,
                          prompt: str = "قم بمسح وتنظيف جميع النصوص من هذه الصورة."):
    if not any(image.filename.lower().endswith(e) for e in ['png','jpg','jpeg','webp']):
        return await interaction.response.send_message(
            "❌ يرجى إرفاق صورة بصيغة صحيحة.", ephemeral=True)
    await interaction.response.defer()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(image.url) as r:
                if r.status != 200:
                    return await interaction.followup.send("❌ فشل تحميل الصورة.")
                image_data = {'mime_type': image.content_type, 'data': await r.read()}

        response  = await gemini.clean_image(prompt, image_data)
        image_out = None
        text_out  = ""
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    image_out = part.inline_data.data
                elif hasattr(part, 'text') and part.text:
                    text_out += part.text

        if image_out:
            await interaction.followup.send(
                content=text_out or "✅ تم التنظيف!",
                file=discord.File(io.BytesIO(image_out), filename="clean_manga.png"),
            )
        else:
            await interaction.followup.send(content=response.text)
    except Exception as e:
        await interaction.followup.send(f"❌ خطأ: {e}")


@bot.tree.command(name="batch", description="[VIP] تحميل عدة فصول دفعة واحدة")
@app_commands.describe(
    series_url="رابط صفحة المانجا الرئيسية",
    chapters="نطاق الفصول: 1-5 أو 1,3,7",
    title="اسم المانجا (اختياري)"
)
@vip_only()
async def batch_download(interaction: discord.Interaction,
                         series_url: str, chapters: str, title: str = "Manga"):
    await interaction.response.defer()

    chapter_nums = []
    try:
        if "-" in chapters and "," not in chapters:
            s, e = chapters.split("-")
            chapter_nums = list(range(int(s.strip()), int(e.strip()) + 1))
        elif "," in chapters:
            chapter_nums = [int(x.strip()) for x in chapters.split(",")]
        else:
            chapter_nums = [int(chapters.strip())]
    except Exception:
        return await interaction.followup.send(embed=discord.Embed(
            title="❌ صيغة خاطئة",
            description="استخدم: `1-5` أو `1,3,5` أو `7`",
            color=C_RED,
        ))

    if len(chapter_nums) > 20:
        return await interaction.followup.send(embed=discord.Embed(
            title="❌ عدد كبير جداً",
            description="الحد الأقصى 20 فصل.",
            color=C_RED,
        ))

    em  = discord.Embed(
        title=f"📦 تحميل جماعي: {title}",
        description=f"**الفصول:** `{chapters}`  ─  **العدد:** `{len(chapter_nums)}`",
        color=C_BLUE,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    em.add_field(name="⚙️ الحالة", value="🔍 جلب قائمة الفصول...", inline=False)
    em.set_footer(text="Cat-Bi Batch Download")
    msg = await interaction.followup.send(embed=em)

    all_chapters = await provider_mgr.get_all_chapters(series_url)
    if not all_chapters:
        em.color = C_RED
        em.set_field_at(0, name="❌ خطأ", value="فشل جلب الفصول.", inline=False)
        return await msg.edit(embed=em)

    available = {int(k): v for k, v in all_chapters.items() if int(k) in chapter_nums}
    missing   = [n for n in chapter_nums if n not in available]
    em.set_field_at(0, name="⚙️ الحالة",
                    value=f"✅ وُجد `{len(available)}/{len(chapter_nums)}` فصل.", inline=False)
    if missing:
        em.add_field(name="⚠️ غير متاح", value=f"`{missing}`", inline=False)
    await msg.edit(embed=em)

    success, failed = [], []
    for i, (ch_num, ch_url) in enumerate(sorted(available.items())):
        ch_title = f"{title}_Ch{ch_num:03.0f}"
        em.set_field_at(0, name="⚙️ الحالة",
                        value=f"📥 تحميل فصل `{ch_num}` ({i+1}/{len(available)})...",
                        inline=False)
        await msg.edit(embed=em)
        try:
            final = await downloader.download_and_stitch(ch_url, ch_title)
            if final and os.path.exists(final):
                size_mb = os.path.getsize(final) / (1024 * 1024)
                if size_mb <= 10.0:
                    await interaction.followup.send(
                        content=f"✅ فصل `{ch_num}` جاهز!",
                        file=discord.File(final),
                    )
                else:
                    link = (await downloader.upload_to_gofile(final)
                            or await downloader.upload_to_catbox(final))
                    if link:
                        await interaction.followup.send(
                            content=f"✅ فصل `{ch_num}` → [تحميل]({link})"
                        )
                    else:
                        failed.append(ch_num); continue
                downloader.cleanup(final)
                success.append(ch_num)
            else:
                failed.append(ch_num)
        except Exception as e:
            failed.append(ch_num)
            print(f"[Batch] Ch{ch_num} error: {e}")

    em.color = C_GREEN if not failed else C_GOLD
    em.set_field_at(0, name="✅ اكتمل",
                    value=(f"نجح: `{success}`\nفشل: `{failed}`"
                           if failed else f"نجح جميع: `{success}`"),
                    inline=False)
    await msg.edit(embed=em)


@bot.tree.command(name="providers", description="قائمة المواقع المدعومة")
@user_only()
async def list_providers(interaction: discord.Interaction):
    await interaction.response.defer()
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
        "Mangalek • 3asq • Manga-ar • Gmanga • Arabsama • وغيرها"
    ))
    em.add_field(name="🇫🇷🇮🇩🇪🇸🇧🇷🇷🇺 متعددة اللغات", inline=False, value=(
        "**فرنسية:** Sushiscan • Phenixscans • Scan-VF • Scantrad\n"
        "**إندونيسية:** Komiku • Manhwaindo • Komikcast • Kiryuu\n"
        "**إسبانية:** TuMangaOnline • Lectortmo • Mangatigre\n"
        "**برتغالية:** MangaLivre • UnionMangas • BRMangas\n"
        "**روسية:** MangaLib • ReManga"
    ))
    em.add_field(name="⚡ WordPress Madara (150+ موقع)", inline=False, value=(
        "Flamescans • Reaperscans • Toonily • Zinmanga • Manhwaclan\n"
        "Leviatanscans • Nightscans • وأكثر من 150 موقع آخر"
    ))
    em.add_field(name="🤖 Generic + Gemini AI", inline=False, value=(
        "أي موقع آخر → Generic أولاً → Gemini AI كخط دفاع أخير!"
    ))
    em.set_footer(text="Cat-Bi • يدعم أي رابط مانجا تقريباً!")
    await interaction.followup.send(embed=em)


# ── مزامنة (Owner) ─────────────────────────────────────────────────────────
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
