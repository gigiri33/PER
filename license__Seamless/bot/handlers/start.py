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
from ..db import ensure_user, get_user_licenses, get_stats, get_all_licenses, setting_get


def esc(text):
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Start Message ──────────────────────────────────────────────────────────────
def get_start_text():
    monthly = float(setting_get("price_cf_hosted", str(PLAN_MONTHLY_HOSTED)))
    premium = float(setting_get("price_sm_premium", str(PLAN_PREMIUM_LICENSE)))
    return """
🌊 <b>به ربات مدیریت لایسنس Seamless خوش آمدید!</b>

━━━━━━━━━━━━━━━━━━━━

⚡ <b>ConfigFlow</b> — ربات فروش کانفیگ رایگان و اوپن‌سورس
💰 اشتراک ماهانه (سرور ما): <b>{monthly:.0f} USDT</b>
👉 <a href="https://t.me/EmadHabibnia/28">قابلیت‌ها و نصب سریع ConfigFlow</a>

━━━━━━━━━━━━━━━━━━━━

🌊 <b>Seamless</b> — نسخه پرمیوم و حرفه‌ای
💎 خرید لایسنس: <b>{premium:.0f} USDT</b>

━━━━━━━━━━━━━━━━━━━━

📞 پشتیبانی: {support}
📢 کانال: {channel}
""".format(
        monthly=monthly,
        premium=premium,
        support=SUPPORT_USERNAME,
        channel=CHANNEL_USERNAME,
    )

# backward-compat alias (for imports that reference START_TEXT directly)
START_TEXT = get_start_text


def main_keyboard(user_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(
        types.InlineKeyboardButton("💛 دونیت و حمایت از دولوپر", callback_data="donate"),
    )
    kb.row(
        types.InlineKeyboardButton("🌊 ربات نمونه Seamless", url=SEAMLESS_DEMO_BOT),
        types.InlineKeyboardButton("⚡ ربات نمونه ConfigFlow", url=CONFIGFLOW_DEMO_BOT),
    )
    kb.row(
        types.InlineKeyboardButton("⚡ نصب دمو ربات ConfigFlow (معمولی) 48 ساعت رایگان", callback_data="trial:configflow"),
        types.InlineKeyboardButton("🌊 نصب دمو ربات Seamless (پرمیوم) 24 ساعت رایگان", callback_data="trial:seamless"),
    )
    kb.row(
        types.InlineKeyboardButton("🛒 خرید اشتراک", callback_data="buy_subscription"),
    )
    if get_user_licenses(user_id):
        kb.row(
            types.InlineKeyboardButton("🤖 ربات‌های من", callback_data="my_licenses"),
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
    bot.send_message(uid, get_start_text(), reply_markup=main_keyboard(uid), parse_mode="HTML", disable_web_page_preview=True)


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
