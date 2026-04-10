# -*- coding: utf-8 -*-
"""
/start message handler.
"""
from ..db import ensure_user, notify_first_start_if_needed, get_user, setting_get, add_referral, get_referral_by_referee
from ..helpers import state_clear, is_admin, parse_int
from ..ui.helpers import check_channel_membership, channel_lock_message
from ..ui.menus import show_main_menu
from ..bot_instance import bot
from ..license_checker import is_licensed


@bot.message_handler(commands=["start"])
def start_handler(message):
    uid = message.from_user.id

    # License check — if not licensed, only admins can use the bot
    if not is_licensed() and not is_admin(uid):
        bot.send_message(
            message.chat.id,
            "🚨 <b>لایسنس ربات منقضی شده است</b>\n\n"
            "لطفاً برای تمدید یا بررسی، با مدیر ربات تماس بگیرید.\n"
            "📞 @license_Seamless_BOT",
            parse_mode="HTML"
        )
        return

    is_new = ensure_user(message.from_user)
    notify_first_start_if_needed(message.from_user)
    state_clear(message.from_user.id)
    uid = message.from_user.id

    # Handle referral link: /start ref_12345
    if is_new and message.text:
        parts = message.text.split()
        if len(parts) > 1 and parts[1].startswith("ref_"):
            try:
                referrer_id = int(parts[1][4:])
                if referrer_id != uid:
                    add_referral(referrer_id, uid)
                    # Check & give start reward, then log the join
                    from ..ui.notifications import check_and_give_referral_start_reward, notify_referral_join
                    check_and_give_referral_start_reward(referrer_id)
                    try:
                        notify_referral_join(referrer_id, uid)
                    except Exception:
                        pass
            except (ValueError, Exception):
                pass

    # Bot status check (before everything else for non-admins)
    if not is_admin(uid):
        bot_status = setting_get("bot_status", "on")
        if bot_status == "off":
            return
        if bot_status == "update":
            bot.send_message(
                message.chat.id,
                "�️ <b>ربات در حال بروزرسانی است</b>\n\n"
                "در حال حاضر یک آپدیت جدید در حال اعمال است؛ لطفاً کمی بعد دوباره تلاش کنید. 🙏\n\n"
                "اگر کار فوری دارید، می‌توانید با پشتیبانی در ارتباط باشید.",
                parse_mode="HTML"
            )
            return

    user = get_user(uid)
    if user and user["status"] == "restricted":
        bot.send_message(
            message.chat.id,
            "⛔️ <b>دسترسی شما محدود شده است</b>\n\n"
            "در حال حاضر امکان استفاده از ربات برای شما فعال نیست.\n"
            "در صورت نیاز با پشتیبانی تماس بگیرید.",
            parse_mode="HTML"
        )
        return
    if not check_channel_membership(uid):
        channel_lock_message(message)
        return
    show_main_menu(message)
