"""
نظام صلاحيات المستخدمين — 3 رتب:
  3 = Owner  (من ALLOWED_USER_IDS — مدمج في الكود)
  2 = VIP    (تحميل مانجا + SmartStitch + Gemini AI)
  1 = User   (بحث + قراءة)
  0 = مرفوض  (لا يقدر يستعمل البوت)
"""

import functools
import discord
from discord import app_commands
from config import Config
import database


RANK_LABELS = {
    3: "👑 Owner",
    2: "⭐ VIP",
    1: "👤 User",
    0: "🚫 Blocked",
}

RANK_COLORS = {
    3: discord.Color.from_rgb(255, 184, 0),
    2: discord.Color.from_rgb(99, 102, 241),
    1: discord.Color.from_rgb(56, 189, 248),
    0: discord.Color.from_rgb(239, 68, 68),
}


# ── جلب رتبة المستخدم ──────────────────────────────────────────────────────
async def get_rank(user_id: int, auto_register: bool = True) -> int:
    """إرجاع رتبة المستخدم (0-3)."""
    if user_id in Config.ALLOWED_USER_IDS:
        return 3
    return await database.get_user_rank(user_id, auto_register=auto_register)


def is_owner(user_id: int) -> bool:
    return user_id in Config.ALLOWED_USER_IDS


# ── مساعد لإرسال رسائل ephemeral بأمان ─────────────────────────────────
async def _safe_reply(interaction: discord.Interaction, content: str):
    """إرسال رسالة إلى interaction بدون crash حتى لو انتهت صلاحيتها."""
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(content, ephemeral=True)
        else:
            await interaction.followup.send(content, ephemeral=True)
    except discord.NotFound:
        pass  # Interaction expired — لا يهم
    except Exception:
        pass


# ── فحص الصلاحية ───────────────────────────────────────────────────────────
async def check_rank(interaction: discord.Interaction, min_rank: int) -> bool:
    rank = await get_rank(interaction.user.id)
    if rank >= min_rank:
        return True

    if rank == 0:
        msg = "❌ ليس لديك صلاحية استخدام هذا البوت.\nتواصل مع المالك للحصول على وصول."
    else:
        msg = f"❌ هذا الأمر يحتاج رتبة **{RANK_LABELS.get(min_rank, str(min_rank))}** أو أعلى."

    await _safe_reply(interaction, msg)
    return False


# ── مزخرف (Decorator) لفحص الرتبة ─────────────────────────────────────────
def require_rank(min_rank: int):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            interaction = None
            for a in args:
                if isinstance(a, discord.Interaction):
                    interaction = a
                    break
            if interaction is None:
                return
            if not await check_rank(interaction, min_rank):
                return
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# ── ديكوراتورات app_commands.check ──────────────────────────────────────────
def owner_only():
    """يُرجع app_commands.check للأوامر التي تستخدم @bot.tree.command"""
    async def predicate(interaction: discord.Interaction) -> bool:
        ok = is_owner(interaction.user.id)
        if not ok:
            await _safe_reply(interaction, "❌ هذا الأمر للمالك فقط.")
        return ok
    return app_commands.check(predicate)


def vip_only():
    """يُرجع app_commands.check لأوامر VIP+"""
    async def predicate(interaction: discord.Interaction) -> bool:
        rank = await get_rank(interaction.user.id)
        ok   = rank >= 2
        if not ok:
            await _safe_reply(
                interaction,
                "❌ هذا الأمر يحتاج رتبة ⭐ VIP أو أعلى.\nتواصل مع المالك للترقية.",
            )
        return ok
    return app_commands.check(predicate)


def user_only():
    """يُرجع app_commands.check لأوامر User+ (أي مستخدم مسجّل)"""
    async def predicate(interaction: discord.Interaction) -> bool:
        rank = await get_rank(interaction.user.id)
        ok   = rank >= 1
        if not ok:
            await _safe_reply(
                interaction,
                "❌ ليس لديك صلاحية استخدام هذا البوت.\nتواصل مع المالك للحصول على وصول.",
            )
        return ok
    return app_commands.check(predicate)
