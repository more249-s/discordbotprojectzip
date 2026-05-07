import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import io
import os
import sys
import aiohttp

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from config import Config
import database
from gemini_client import GeminiClient
from binance_client import BinanceMonitor
import datetime
from keep_alive import keep_alive
from manga_downloader import MangaDownloader

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
gemini = GeminiClient()
binance_mon = BinanceMonitor(bot)
downloader = MangaDownloader()

async def setup_hook():
    await database.init_db()
    await bot.load_extension("radar")
bot.setup_hook = setup_hook

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="سوق العملات الرقمية 💰"))
    
    print("Syncing slash commands...")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    await binance_mon.start()
    binance_check_loop.start()
    print("Bot is ready and monitoring...")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 1. Check if it's the Gemini channel OR the bot is mentioned
    is_gemini_channel = message.channel.id == Config.GEMINI_CHANNEL_ID
    is_mentioned = bot.user.mentioned_in(message)
    
    if is_gemini_channel or is_mentioned:
        async with message.channel.typing():
            prompt = message.content.replace(f'<@!{bot.user.id}>', '').replace(f'<@{bot.user.id}>', '').strip()
            
            # Handle image if present
            image_data = None
            if message.attachments:
                for attachment in message.attachments:
                    if any(attachment.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'webp', 'gif']):
                        async with aiohttp.ClientSession() as session:
                            async with session.get(attachment.url) as resp:
                                if resp.status == 200:
                                    image_bytes = await resp.read()
                                    image_data = {
                                        'mime_type': attachment.content_type,
                                        'data': image_bytes
                                    }
                                    break # Handle the first valid image attachment
            
            response_text = await gemini.get_response(message.author.id, prompt, image_data)
            
            # Split message if it's too long for Discord (2000 chars)
            if len(response_text) > 2000:
                for i in range(0, len(response_text), 2000):
                    await message.reply(response_text[i:i+2000])
            else:
                await message.reply(response_text)

    await bot.process_commands(message)

# --- Binance Monitoring Loop ---
@tasks.loop(minutes=1)
async def binance_check_loop():
    # Check Deposits
    new_deposits = await binance_mon.check_deposits()
    for d in new_deposits:
        await notify_transaction(d, "إيداع جديد 💰", discord.Color.green())

    # Check Withdrawals
    new_withdrawals = await binance_mon.check_withdrawals()
    for w in new_withdrawals:
        await notify_transaction(w, "سحب جديد ⚠️", discord.Color.red())

    # Check Price Alerts
    active_alerts = await database.get_active_alerts()
    for alert_id, user_id, symbol, target_price, condition in active_alerts:
        current_price = await binance_mon.get_symbol_price(symbol)
        if current_price:
            current_price = float(current_price)
            triggered = False
            if condition == "above" and current_price >= target_price:
                triggered = True
            elif condition == "below" and current_price <= target_price:
                triggered = True
            
            if triggered:
                user = await bot.fetch_user(user_id)
                if user:
                    embed = discord.Embed(
                        title="🔔 تنبيه سعر باينانس", 
                        description=f"وصل سعر **{symbol}** إلى `${current_price:,.2f}`\n(تنبيهك كان: {condition} ${target_price:,.2f})", 
                        color=discord.Color.blue()
                    )
                    await user.send(embed=embed)
                await database.deactivate_alert(alert_id)


async def notify_transaction(data, title, color):
    # Mention allowed users (assuming the first one is the primary owner for notifications)
    owner_id = Config.ALLOWED_USER_IDS[0] if Config.ALLOWED_USER_IDS else None
    mention = f"<@{owner_id}>" if owner_id else ""
    
    embed = discord.Embed(title=title, color=color, timestamp=datetime.datetime.now())
    embed.add_field(name="المبلغ", value=f"{data['amount']} {data.get('coin', data.get('asset', ''))}", inline=True)
    embed.add_field(name="الحالة", value="مكتمل ✅", inline=True)
    if 'txId' in data or 'id' in data:
        embed.add_field(name="رقم العملية (TxID)", value=f"`{data.get('txId') or data.get('id')}`", inline=False)
    
    # Send to error channel or a specific log channel if we had one, 
    # but for now we send it to the Gemini channel or error channel
    target_channel_id = Config.ERROR_CHANNEL_ID or Config.GEMINI_CHANNEL_ID
    channel = bot.get_channel(target_channel_id)
    if channel:
        await channel.send(content=f"{mention} إشعار مالي جديد!", embed=embed)

# --- Commands ---
@bot.tree.command(name="price", description="Check current price of a crypto symbol (e.g. BTCUSDT)")
async def price(interaction: discord.Interaction, symbol: str):
    await interaction.response.defer()
    p = await binance_mon.get_symbol_price(symbol)
    if p:
        await interaction.followup.send(f"سعر **{symbol.upper()}** الحالي هو: `${float(p):,.2f}`")
    else:
        await interaction.followup.send("لم يتم العثور على العملة. تأكد من الرمز (مثال: BTCUSDT)")

@bot.tree.command(name="balance", description="Check your Binance account balances (Owner only)")
async def balance(interaction: discord.Interaction):
    if not Config.is_allowed(interaction.user.id):
        await interaction.response.send_message("عذراً، هذا الأمر مخصص لصاحب البوت فقط.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    balances = await binance_mon.get_account_balances()
    if balances is not None:
        if len(balances) == 0:
            await interaction.followup.send(embed=discord.Embed(title="محفظة باينانس", description="محفظتك حالياً فارغة (0) في جميع العملات.", color=discord.Color.orange()))
        else:
            embed = discord.Embed(title="💰 رصيد حساب باينانس الخاص بك", color=discord.Color.gold(), timestamp=datetime.datetime.now())
            for b in balances:
                wallet_type = b.get('type', 'Spot')
                embed.add_field(name=f"عملة {b['asset']} ({wallet_type})", value=f"**متاح:** `{b['free']}`\n**محجوز:** `{b['locked']}`", inline=False)
            await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(embed=discord.Embed(title="خطأ", description="فشل في جلب الرصيد. تأكد من إعدادات API.", color=discord.Color.red()))

@bot.tree.command(name="status", description="Check if the bot and APIs are alive")
async def status(interaction: discord.Interaction):
    embed = discord.Embed(title="📊 حالة النظام", color=discord.Color.blue())
    embed.add_field(name="البوت", value="🟢 يعمل", inline=True)
    embed.add_field(name="الذكاء الاصطناعي (Gemini)", value="🟢 متصل", inline=True)
    
    # Quick binance check
    p = await binance_mon.get_symbol_price("BTCUSDT")
    binance_status = "🟢 متصل" if p else "🔴 غير متصل"
    embed.add_field(name="حساب باينانس", value=binance_status, inline=True)
    
    await interaction.response.send_message(embed=embed)
    
@bot.tree.command(name="alert_add", description="إضافة تنبيه لسعر عملة معينة")
@app_commands.describe(symbol="رمز العملة (مثال: BTCUSDT)", price="السعر المستهدف", condition="نوع التنبيه: فوق أو تحت السعر")
@app_commands.choices(condition=[
    app_commands.Choice(name="فوق السعر (Above)", value="above"),
    app_commands.Choice(name="تحت السعر (Below)", value="below")
])
async def alert_add(interaction: discord.Interaction, symbol: str, price: float, condition: str):
    await database.add_price_alert(interaction.user.id, symbol, price, condition)
    await interaction.response.send_message(f"✅ تم إضافة التنبيه لـ **{symbol.upper()}** عند سعر **${price:,.2f}** ({condition}).", ephemeral=True)

@bot.tree.command(name="alert_list", description="عرض تنبيهاتك النشطة")
async def alert_list(interaction: discord.Interaction):
    alerts = await database.get_user_alerts(interaction.user.id)
    if not alerts:
        return await interaction.response.send_message("ليس لديك أي تنبيهات نشطة حالياً.", ephemeral=True)
    
    embed = discord.Embed(title="🔔 تنبيهاتك النشطة", color=discord.Color.blue())
    desc = ""
    for a_id, sym, price, cond in alerts:
        desc += f"**ID: `{a_id}`** | {sym} | {cond} `${price:,.2f}`\n"
    embed.description = desc
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="alert_remove", description="إزالة تنبيه باستخدام الـ ID")
async def alert_remove(interaction: discord.Interaction, alert_id: int):
    await database.remove_alert(alert_id, interaction.user.id)
    await interaction.response.send_message(f"✅ تم إزالة التنبيه رقم `{alert_id}`.", ephemeral=True)


@bot.command()
async def sync(ctx):
    if Config.is_allowed(ctx.author.id):
        await bot.tree.sync()
        await ctx.send("تم مزامنة أوامر السلاش بنجاح!")

@bot.tree.command(name="download", description="تحميل فصل مانجا مع الدمج التلقائي (SmartStitch)")
@app_commands.describe(url="رابط الفصل", title="عنوان المجلد (اختياري)")
async def download(interaction: discord.Interaction, url: str, title: str = "Manga_Chapter"):
    if not Config.is_allowed(interaction.user.id):
        return await interaction.response.send_message("❌ غير مسموح لك باستخدام هذا الأمر.", ephemeral=True)
    discord_limit_mb = 10.0

    await interaction.response.defer()
    state = {
        "phase": "تهيئة العملية",
        "progress": downloader.create_progress_bar(0, 1),
        "counter": "0/1",
        "detail": "جاري تجهيز مهمة التحميل...",
        "file_size": "-",
        "provider": "-",
        "link": None,
        "color": discord.Color.from_rgb(88, 166, 255),
    }

    def build_embed():
        embed = discord.Embed(
            title="📦 لوحة تحميل الفصل",
            description=f"**العنوان:** `{title}`\n**الصيغة:** ZIP + SmartStitch",
            color=state["color"],
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="الحالة الحالية", value=state["phase"], inline=False)
        embed.add_field(name="التقدم", value=f"`{state['progress']}`\n`{state['counter']}`", inline=False)
        embed.add_field(name="التفاصيل", value=state["detail"], inline=False)
        embed.add_field(name="حجم الملف", value=state["file_size"], inline=True)
        embed.add_field(name="وجهة الرفع", value=state["provider"], inline=True)
        if state["link"]:
            embed.add_field(name="الرابط", value=f"[اضغط هنا للتحميل]({state['link']})", inline=False)
        embed.set_footer(text="Cat-Bi Manga System • Download Dashboard")
        return embed

    def build_link_view(link):
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="فتح رابط التحميل", emoji="🔗", style=discord.ButtonStyle.link, url=link))
        return view

    msg = await interaction.followup.send(embed=build_embed())
    last_edit = 0.0

    async def update_progress(current, total, task_name):
        nonlocal last_edit
        state["phase"] = task_name
        state["progress"] = downloader.create_progress_bar(current, total)
        state["counter"] = f"{current}/{total}"
        state["detail"] = "العملية تعمل الآن. سيتم تحديث هذه اللوحة تلقائياً."
        now = asyncio.get_running_loop().time()
        if now - last_edit < 1.25 and current < total:
            return
        last_edit = now
        try:
            await msg.edit(embed=build_embed())
        except Exception:
            pass

    try:
        final_file = await downloader.download_and_stitch(
            url=url, 
            chapter_title=title, 
            progress_callback=update_progress
        )

        if final_file and os.path.exists(final_file):
            file_size = os.path.getsize(final_file) / (1024 * 1024)
            state["file_size"] = f"{file_size:.2f} MB"
            
            if file_size <= discord_limit_mb:
                state["phase"] = "إرسال مباشر إلى Discord"
                state["progress"] = downloader.create_progress_bar(1, 1)
                state["counter"] = "1/1"
                state["provider"] = "Discord"
                state["detail"] = f"الحجم لا يتجاوز {discord_limit_mb:.0f} MB، سيتم الإرسال مباشرة في الروم."
                await msg.edit(embed=build_embed())
                file = discord.File(final_file)
                await interaction.followup.send(file=file)
                state["phase"] = "اكتملت العملية"
                state["color"] = discord.Color.green()
                state["detail"] = "تم تحميل الفصل ودمجه وإرساله كملف ZIP."
                await msg.edit(embed=build_embed())
            else:
                state["phase"] = "رفع إلى Google Drive"
                state["provider"] = "Google Drive"
                state["progress"] = downloader.create_progress_bar(0, 100)
                state["counter"] = "0/100"
                state["detail"] = f"الحجم أكبر من {discord_limit_mb:.0f} MB، لذلك سيتم الرفع الخارجي بدل Discord."
                await msg.edit(embed=build_embed())
                drive_link = await downloader.upload_to_gdrive(final_file, os.path.basename(final_file), progress_callback=update_progress)
                
                if drive_link:
                    state["phase"] = "اكتملت العملية"
                    state["provider"] = "Google Drive"
                    state["link"] = drive_link
                    state["color"] = discord.Color.green()
                    state["progress"] = downloader.create_progress_bar(100, 100)
                    state["counter"] = "100/100"
                    state["detail"] = "تم تحميل الفصل ودمجه ورفعه بنجاح."
                    await msg.edit(embed=build_embed(), view=build_link_view(drive_link))
                else:
                    state["phase"] = "رفع إلى Gofile"
                    state["provider"] = "Gofile"
                    state["progress"] = downloader.create_progress_bar(0, 100)
                    state["counter"] = "0/100"
                    state["detail"] = "فشل Drive، جاري استخدام Gofile كبديل تلقائي."
                    state["color"] = discord.Color.orange()
                    await msg.edit(embed=build_embed())
                    gofile_link = await downloader.upload_to_gofile(final_file, progress_callback=update_progress)
                    if gofile_link:
                        state["phase"] = "اكتملت العملية"
                        state["provider"] = "Gofile"
                        state["link"] = gofile_link
                        state["color"] = discord.Color.green()
                        state["progress"] = downloader.create_progress_bar(100, 100)
                        state["counter"] = "100/100"
                        state["detail"] = "تم تحميل الفصل ودمجه ورفعه عبر Gofile."
                        await msg.edit(embed=build_embed(), view=build_link_view(gofile_link))
                    else:
                        state["phase"] = "فشل الرفع"
                        state["color"] = discord.Color.red()
                        state["detail"] = "تم تجهيز الملف، لكن فشل الرفع على Drive وGofile."
                        await msg.edit(embed=build_embed())
            
            downloader.cleanup(final_file)
        else:
            state["phase"] = "فشل التحميل"
            state["color"] = discord.Color.red()
            state["detail"] = "فشل تحميل الصور أو فشل SmartStitch. تأكد من الرابط أو حماية الموقع."
            await msg.edit(embed=build_embed())

    except Exception as e:
        state["phase"] = "حدث خطأ غير متوقع"
        state["color"] = discord.Color.red()
        state["detail"] = str(e)[:900]
        try:
            await msg.edit(embed=build_embed())
        except Exception:
            await interaction.followup.send(f"❌ حدث خطأ غير متوقع: {str(e)}")
        import traceback
        traceback.print_exc()

@bot.tree.command(name="clean", description="تبييض المانجا: مسح وتنظيف النصوص من الصورة المرفقة")
async def clean_image_cmd(interaction: discord.Interaction, image: discord.Attachment, prompt: str = "قم بمسح وتنظيف جميع النصوص من هذه الصورة وترك الفقاعات فارغة."):
    if not any(image.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'webp']):
        await interaction.response.send_message("يرجى إرفاق صورة بصيغة صحيحة (png, jpg, jpeg, webp).", ephemeral=True)
        return

    await interaction.response.defer()
    
    try:
        # تحميل الصورة
        async with aiohttp.ClientSession() as session:
            async with session.get(image.url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("فشل في تحميل الصورة من ديسكورد.")
                    return
                image_bytes = await resp.read()
                image_data = {
                    'mime_type': image.content_type,
                    'data': image_bytes
                }
        
        # إرسال للصورة للموديل المختص بالتعديل
        response = await gemini.clean_image(prompt, image_data)
        
        image_output = None
        text_output = ""
        
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    image_output = part.inline_data.data
                elif hasattr(part, 'text') and part.text:
                    text_output += part.text

        if image_output:
            file = discord.File(io.BytesIO(image_output), filename="clean_manga.png")
            await interaction.followup.send(content=text_output if text_output else "تم التنظيف بنجاح 🪄", file=file)
        else:
            await interaction.followup.send(content=response.text)

    except Exception as e:
        await interaction.followup.send(f"حدث خطأ أثناء التنظيف: {str(e)}")

if __name__ == "__main__":
    if not Config.DISCORD_TOKEN:
        print("❌ Error: DISCORD_TOKEN not found in .env")
    elif not Config.GEMINI_API_KEY:
        print("❌ Error: GEMINI_API_KEY not found in .env")
    else:
        try:
            print("Starting Web Server...")
            keep_alive()
            print("Starting Bot...")
            bot.run(Config.DISCORD_TOKEN)
        except Exception as e:
            print(f"FATAL ERROR during startup: {str(e)}")
            import traceback
            traceback.print_exc()
