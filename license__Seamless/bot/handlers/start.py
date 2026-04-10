# -*- coding: utf-8 -*-
"""
/start handler & main menu for Seamless License Bot.
"""
import time
from telebot import types

from ..bot_instance import bot, USER_STATE
from ..config import (
    ADMIN_IDS, SEAMLESS_DEMO_BOT, CONFIGFLOW_DEMO_BOT,
    CONFIGFLOW_INSTALL_CMD, CONFIGFLOW_GITHUB,
    SUPPORT_USERNAME, CHANNEL_USERNAME,
    PLAN_MONTHLY_HOSTED, PLAN_PREMIUM_LICENSE, TRIAL_HOURS,
)
from ..db import ensure_user, get_user_licenses, get_stats, get_all_licenses


def esc(text):
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Start Message ──────────────────────────────────────────────────────────────
START_TEXT = """
🌊 <b>به ربات مدیریت لایسنس Seamless خوش آمدید!</b>

<b>Seamless</b> نسخه پرمیوم و حرفه‌ای ربات فروش کانفیگ است.
<b>ConfigFlow</b> نسخه رایگان و اوپن‌سورس — برای شروع عالیه!

━━━━━━━━━━━━━━━━━━━━

🔹 <b>ConfigFlow (رایگان):</b>
اگر سرور خارج دارید، با یک دستور نصب کنید:
<code>{cmd}</code>

⭐️ لینک پروژه: <a href="{github}">GitHub</a>
اگر سرور ندارید، اشتراک ماهانه بگیرید — ما روی سرور خودمون براتون ران می‌کنیم.
💰 هزینه اشتراک ماهانه: <b>{monthly} USDT</b> (به عنوان دونیت)

━━━━━━━━━━━━━━━━━━━━

🔷 <b>Seamless (پرمیوم):</b>
نسخه حرفه‌ای با امکانات ویژه.
💎 خرید لایسنس: <b>{premium} USDT</b>

━━━━━━━━━━━━━━━━━━━━

📞 پشتیبانی: {support}
📢 کانال: {channel}
""".format(
    cmd=CONFIGFLOW_INSTALL_CMD,
    github=CONFIGFLOW_GITHUB,
    monthly=PLAN_MONTHLY_HOSTED,
    premium=PLAN_PREMIUM_LICENSE,
    support=SUPPORT_USERNAME,
    channel=CHANNEL_USERNAME,
)


def main_keyboard(user_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(
        types.InlineKeyboardButton("� خرید اشتراک", callback_data="buy_subscription"),
    )
    kb.row(
        types.InlineKeyboardButton("�💛 دونیت و حمایت از دولوپر", callback_data="donate"),
    )
    kb.row(
        types.InlineKeyboardButton("🌊 ربات نمونه Seamless", url=SEAMLESS_DEMO_BOT),
        types.InlineKeyboardButton("⚡ ربات نمونه ConfigFlow", url=CONFIGFLOW_DEMO_BOT),
    )
    kb.row(
        types.InlineKeyboardButton("⚡ ران ربات ConfigFlow (48 ساعت رایگان)", callback_data="trial:configflow"),
    )
    kb.row(
        types.InlineKeyboardButton("🌊 ران ربات Seamless (24 ساعت رایگان)", callback_data="trial:seamless"),
    )
    kb.row(
        types.InlineKeyboardButton("📋 لایسنس‌های من", callback_data="my_licenses"),
    )
    kb.row(
        types.InlineKeyboardButton("📞 پشتیبانی", url=SUPPORT_USERNAME),
    )
    if user_id in ADMIN_IDS:
        kb.row(
            types.InlineKeyboardButton("🔧 پنل مدیریت", callback_data="admin_panel"),
        )
    return kb


@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid = msg.from_user.id
    ensure_user(uid, msg.from_user.username or "", msg.from_user.first_name or "")
    USER_STATE.pop(uid, None)
    bot.send_message(uid, START_TEXT, reply_markup=main_keyboard(uid), disable_web_page_preview=True)


@bot.message_handler(commands=["admin"])
def cmd_admin(msg):
    uid = msg.from_user.id
    if uid not in ADMIN_IDS:
        return
    show_admin_panel(uid)


def show_admin_panel(uid):
    stats = get_stats()
    text = f"""
🔧 <b>پنل مدیریت لایسنس Seamless</b>

👥 کل کاربران: <b>{stats['total_users']}</b>
📜 کل لایسنس‌ها: <b>{stats['total_licenses']}</b>
✅ لایسنس‌های فعال: <b>{stats['active_licenses']}</b>
🆓 تریال فعال: <b>{stats['trial_licenses']}</b>
💎 پرمیوم فعال: <b>{stats['premium_licenses']}</b>
💰 درآمد کل: <b>{stats['total_revenue']:.1f} USDT</b>
🖥 کل نمونه‌ها: <b>{stats['total_instances']}</b>
🟢 نمونه‌های فعال: <b>{stats['active_instances']}</b>
"""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(
        types.InlineKeyboardButton("📋 همه لایسنس‌ها", callback_data="adm:all_lic"),
        types.InlineKeyboardButton("👥 لیست کاربران", callback_data="adm:users"),
    )
    kb.row(
        types.InlineKeyboardButton(" آمار", callback_data="adm:stats"),
        types.InlineKeyboardButton("➕ صدور لایسنس دستی", callback_data="adm:manual_lic"),
    )
    kb.row(
        types.InlineKeyboardButton("💳 درگاه‌های پرداخت", callback_data="adm:gateways"),
        types.InlineKeyboardButton("📣 ارسال پیام همگانی", callback_data="adm:broadcast"),
    )
    kb.row(
        types.InlineKeyboardButton("💰 قیمت‌ها", callback_data="adm:prices"),
        types.InlineKeyboardButton("🎟 کدهای تخفیف", callback_data="adm:discounts"),
    )
    kb.row(
        types.InlineKeyboardButton("🆔 آیدی ایموجی پریمیوم", callback_data="adm:emoji_id_tool"),
    )
    kb.row(
        types.InlineKeyboardButton("♻️ آپدیت همه ربات‌ها", callback_data="adm:update_all"),
        types.InlineKeyboardButton("🛰 وضعیت اتوآپدیت", callback_data="adm:auto_update_status"),
    )
    kb.row(
        types.InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu"),
    )
    bot.send_message(uid, text, reply_markup=kb)
