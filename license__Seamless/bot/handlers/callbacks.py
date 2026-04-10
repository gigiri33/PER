# -*- coding: utf-8 -*-
"""
Callback query handlers for the License Bot.
Admin-only license management — no payment flows.
"""
import time
import threading
from telebot import types

from ..bot_instance import bot, USER_STATE
from ..config import (
    ADMIN_IDS, TRIAL_HOURS,
    SUPPORT_USERNAME,
    AUTO_UPDATE_ENABLED, AUTO_UPDATE_INTERVAL,
)
from ..db import (
    ensure_user, get_user_licenses, get_license,
    create_license, update_license_status, extend_license, upgrade_license_plan,
    get_all_licenses, delete_license,
    get_stats, get_all_users, get_user,
    get_all_instances, get_instance, update_instance_status, delete_instance,
    get_instance_by_token,
    has_used_trial,
    create_donate_payment, get_donate_payment, confirm_donate_payment, cancel_donate_payment,
    setting_get, setting_set,
    create_discount_code, get_discount_code_by_code, get_all_discount_codes, delete_discount_code,
    create_subscription_order, get_subscription_order, confirm_subscription_order,
    reject_subscription_order,
)
from ..deployer import (
    start_instance, stop_instance, restart_instance, remove_instance,
    update_instance, update_all_instances, instance_status as deployer_status,
    list_all_instances, service_name as deployer_svc_name, instance_dir as deployer_inst_dir,
    repo_has_updates,
)
from .start import main_keyboard, show_admin_panel, get_start_text, esc

PAGE_SIZE = 10


def _fmt_time(ts):
    if not ts:
        return "—"
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _remaining(expires_at):
    diff = expires_at - time.time()
    if diff <= 0:
        return "❌ منقضی شده"
    hours = int(diff // 3600)
    mins = int((diff % 3600) // 60)
    if hours >= 24:
        days = hours // 24
        return f"{days} روز و {hours % 24} ساعت"
    return f"{hours} ساعت و {mins} دقیقه"


def _plan_label(plan):
    return {
        "trial": "🆓 تریال",
        "monthly": "📦 ماهانه",
        "premium": "💎 پرمیوم",
        "configflow_trial": "⚡ تریال ConfigFlow",
        "configflow_monthly": "📦 ماهانه ConfigFlow",
    }.get(plan, plan)


def _status_label(status):
    return {"active": "✅ فعال", "expired": "⏰ منقضی", "suspended": "🚫 معلق"}.get(status, status)


# ── Main Menu ──────────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "main_menu")
def cb_main_menu(call):
    uid = call.from_user.id
    USER_STATE.pop(uid, None)
    try:
        bot.edit_message_text(get_start_text(), uid, call.message.message_id,
                              reply_markup=main_keyboard(uid), parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        bot.send_message(uid, get_start_text(), reply_markup=main_keyboard(uid), parse_mode="HTML", disable_web_page_preview=True)
    bot.answer_callback_query(call.id)


# ── Trial: ConfigFlow ─────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "trial:configflow")
def cb_trial_configflow(call):
    uid = call.from_user.id
    if has_used_trial(uid, "configflow"):
        bot.answer_callback_query(call.id, "⚠️ شما قبلاً از تست رایگان ConfigFlow استفاده کرده‌اید!", show_alert=True)
        return
    USER_STATE[uid] = {"step": "cf_token", "type": "configflow"}
    text = """
⚡ <b>ران ربات ConfigFlow — 24 ساعت رایگان</b>

لطفاً اطلاعات زیر را ارسال کنید:

<b>مرحله ۱:</b> توکن ربات خود را از @BotFather بفرستید:
"""
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="main_menu"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(uid, text, reply_markup=kb)
    bot.answer_callback_query(call.id)


# ── Trial: Seamless ───────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "trial:seamless")
def cb_trial_seamless(call):
    uid = call.from_user.id
    if has_used_trial(uid, "seamless"):
        bot.answer_callback_query(call.id, "⚠️ شما قبلاً از تست رایگان Seamless استفاده کرده‌اید!", show_alert=True)
        return
    USER_STATE[uid] = {"step": "sm_token", "type": "seamless"}
    text = """
🌊 <b>ران ربات Seamless — 24 ساعت رایگان</b>

پس از 24 ساعت باید لایسنس پرمیوم تهیه کنید.

<b>مرحله ۱:</b> توکن ربات خود را از @BotFather بفرستید:
"""
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="main_menu"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(uid, text, reply_markup=kb)
    bot.answer_callback_query(call.id)


# ── My Bots (paginated) ──────────────────────────────────────────────────────
def _send_my_licenses(uid, msg_id, page=0):
    licenses = get_user_licenses(uid)
    total = len(licenses)
    if not licenses:
        try:
            bot.edit_message_text(
                "🤖 <b>شما هنوز ربات فعالی ندارید.</b>",
                uid, msg_id,
                reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]]),
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = licenses[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    text = f"🤖 <b>ربات‌های من ({total}):</b>\nصفحه {page+1} از {pages}"
    kb = types.InlineKeyboardMarkup()
    for lic in chunk:
        bot_name = f"@{lic['bot_username']}" if lic.get('bot_username') else f"#{lic['id']}"
        remaining = _remaining(lic['expires_at'])
        kb.row(
            types.InlineKeyboardButton(bot_name, callback_data=f"lic_detail:{lic['id']}:{page}"),
            types.InlineKeyboardButton(remaining, callback_data=f"lic_detail:{lic['id']}:{page}"),
            types.InlineKeyboardButton("⚙️ تنظیمات", callback_data=f"bot_manage:{lic['id']}:{page}"),
        )
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀ قبلی", callback_data=f"my_lic_pg:{page-1}"))
    if page < pages - 1:
        nav.append(types.InlineKeyboardButton("بعدی ▶", callback_data=f"my_lic_pg:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu"))

    try:
        bot.edit_message_text(text, uid, msg_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data == "my_licenses")
def cb_my_licenses(call):
    uid = call.from_user.id
    _send_my_licenses(uid, call.message.message_id, page=0)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("my_lic_pg:"))
def cb_my_lic_pg(call):
    uid = call.from_user.id
    page = int(call.data.split(":")[1])
    _send_my_licenses(uid, call.message.message_id, page=page)
    bot.answer_callback_query(call.id)


# ── My Bot Detail ────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("lic_detail:"))
def cb_lic_detail(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    lic_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    lic = get_license(lic_id)
    if not lic or lic["user_id"] != uid:
        bot.answer_callback_query(call.id, "❌ ربات پیدا نشد.", show_alert=True)
        return
    inst = get_instance_by_token(lic['bot_token'])
    live_st = deployer_status(inst["project"], inst["bot_token"]) if inst else "—"
    text = (
        f"🤖 <b>اطلاعات ربات @{esc(lic.get('bot_username') or '—')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 پلن: {_plan_label(lic['plan'])}\n"
        f"📊 وضعیت اشتراک: {_status_label(lic['status'])}\n"
        f"🖥 وضعیت سرور: <b>{live_st}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 آیدی ادمین: <code>{esc(lic.get('admin_id') or '—')}</code>\n"
        f"📞 پشتیبانی: @{esc(lic.get('support_user') or '—')}\n"
        f"🔑 توکن: <code>{esc(lic.get('bot_token') or '—')}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 تاریخ شروع: {_fmt_time(lic['created_at'])}\n"
        f"⏳ تاریخ انقضا: {_fmt_time(lic['expires_at'])}\n"
        f"⏱️ باقیمانده: {_remaining(lic['expires_at'])}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⚙️ مدیریت ربات", callback_data=f"bot_manage:{lic_id}:{page}"))
    kb.add(types.InlineKeyboardButton("🔙 ربات‌های من", callback_data=f"my_lic_pg:{page}"))
    kb.add(types.InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


# ── User Bot Management Menu ──────────────────────────────────────────────────
def _bot_manage_kb(lic_id, page, is_admin=False):
    """Build the management keyboard for a bot (shared between user and admin views)."""
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("▶️ روشن",    callback_data=f"bm:start:{lic_id}:{page}"),
        types.InlineKeyboardButton("⏹ خاموش",  callback_data=f"bm:stop:{lic_id}:{page}"),
        types.InlineKeyboardButton("🔁 ریستارت", callback_data=f"bm:restart:{lic_id}:{page}"),
    )
    kb.row(
        types.InlineKeyboardButton("🔄 آپدیت",          callback_data=f"bm:update:{lic_id}:{page}"),
        types.InlineKeyboardButton("📋 لاگ‌های ربات",   callback_data=f"bm:logs:{lic_id}:{page}"),
    )
    kb.row(
        types.InlineKeyboardButton("✏️ تغییر اطلاعات", callback_data=f"bm:edit:{lic_id}:{page}"),
        types.InlineKeyboardButton("🔃 اتوآپدیت",       callback_data=f"bm:autoupd:{lic_id}:{page}"),
    )
    if is_admin:
        kb.row(
            types.InlineKeyboardButton("⏳ تمدید",  callback_data=f"adm:extend:{lic_id}"),
            types.InlineKeyboardButton("🚫 معلق",   callback_data=f"adm:suspend:{lic_id}"),
            types.InlineKeyboardButton("🗑 حذف",    callback_data=f"adm:lic_delete:{lic_id}:{page}"),
        )
        kb.add(types.InlineKeyboardButton("📥 ری‌استور دیتابیس", callback_data=f"adm:lic_restore:{lic_id}:{page}"))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data=f"adm:all_lic:{page}"))
    else:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"lic_detail:{lic_id}:{page}"))
    return kb


def _bot_manage_text(lic, inst=None):
    live_st = deployer_status(inst["project"], inst["bot_token"]) if inst else "—"
    return (
        f"⚙️ <b>مدیریت ربات @{esc(lic.get('bot_username') or '—')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 پلن: {_plan_label(lic['plan'])}  |  📊 {_status_label(lic['status'])}\n"
        f"🖥 وضعیت سرور: <b>{live_st}</b>\n"
        f"⏱️ باقیمانده: {_remaining(lic['expires_at'])}"
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("bot_manage:"))
def cb_bot_manage(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    lic_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    lic = get_license(lic_id)
    is_admin = uid in ADMIN_IDS
    if not lic or (lic["user_id"] != uid and not is_admin):
        bot.answer_callback_query(call.id, "❌ دسترسی ندارید.", show_alert=True)
        return
    inst = get_instance_by_token(lic['bot_token'])
    text = _bot_manage_text(lic, inst)
    kb = _bot_manage_kb(lic_id, page, is_admin=is_admin)
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


# ── Bot Management Actions (start/stop/restart/update/logs/autoupdate) ─────────
def _bm_get_lic_inst(call):
    """Parse call data and return (uid, lic_id, page, lic, inst) or None on error."""
    uid = call.from_user.id
    parts = call.data.split(":")
    lic_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    lic = get_license(lic_id)
    is_admin = uid in ADMIN_IDS
    if not lic or (lic["user_id"] != uid and not is_admin):
        bot.answer_callback_query(call.id, "❌ دسترسی ندارید.", show_alert=True)
        return None
    inst = get_instance_by_token(lic['bot_token'])
    if not inst:
        bot.answer_callback_query(call.id, "❌ نمونه‌ای برای این ربات پیدا نشد.", show_alert=True)
        return None
    return uid, lic_id, page, lic, inst, is_admin


@bot.callback_query_handler(func=lambda c: c.data.startswith("bm:start:"))
def cb_bm_start(call):
    r = _bm_get_lic_inst(call)
    if not r: return
    uid, lic_id, page, lic, inst, is_admin = r
    ok, _ = start_instance(inst["project"], inst["bot_token"])
    if ok: update_instance_status(inst["id"], "running")
    bot.answer_callback_query(call.id, "▶️ روشن شد." if ok else "❌ خطا در روشن کردن", show_alert=not ok)
    call.data = f"bot_manage:{lic_id}:{page}"
    cb_bot_manage(call)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bm:stop:"))
def cb_bm_stop(call):
    r = _bm_get_lic_inst(call)
    if not r: return
    uid, lic_id, page, lic, inst, is_admin = r
    ok, _ = stop_instance(inst["project"], inst["bot_token"])
    if ok: update_instance_status(inst["id"], "stopped")
    bot.answer_callback_query(call.id, "⏹ خاموش شد." if ok else "❌ خطا در خاموش کردن", show_alert=not ok)
    call.data = f"bot_manage:{lic_id}:{page}"
    cb_bot_manage(call)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bm:restart:"))
def cb_bm_restart(call):
    r = _bm_get_lic_inst(call)
    if not r: return
    uid, lic_id, page, lic, inst, is_admin = r
    ok, _ = restart_instance(inst["project"], inst["bot_token"])
    if ok: update_instance_status(inst["id"], "running")
    bot.answer_callback_query(call.id, "🔁 ریستارت شد." if ok else "❌ خطا", show_alert=not ok)
    call.data = f"bot_manage:{lic_id}:{page}"
    cb_bot_manage(call)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bm:update:"))
def cb_bm_update(call):
    r = _bm_get_lic_inst(call)
    if not r: return
    uid, lic_id, page, lic, inst, is_admin = r
    bot.answer_callback_query(call.id, "🔄 در حال آپدیت...", show_alert=False)
    def _do():
        ok, msg = update_instance(inst["project"], inst["bot_token"])
        if ok: update_instance_status(inst["id"], "running")
        try:
            bot.send_message(uid,
                f"{'✅' if ok else '❌'} آپدیت ربات @{esc(lic.get('bot_username',''))}:\n{msg[:200]}",
                parse_mode="HTML")
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()


@bot.callback_query_handler(func=lambda c: c.data.startswith("bm:logs:"))
def cb_bm_logs(call):
    r = _bm_get_lic_inst(call)
    if not r: return
    uid, lic_id, page, lic, inst, is_admin = r
    bot.answer_callback_query(call.id)
    from ..deployer import _run, service_name as _svc
    svc = _svc(inst["project"], inst["bot_token"])
    ok, out = _run(f"journalctl -u {svc} -n 50 --no-pager 2>&1 | tail -c 3500")
    log_text = (out or "لاگی یافت نشد.").strip()[-3500:]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"bot_manage:{lic_id}:{page}"))
    bot.send_message(uid, f"📋 <b>لاگ‌های ربات @{esc(lic.get('bot_username',''))}:</b>\n\n<pre>{esc(log_text)}</pre>",
                     reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data.startswith("bm:autoupd:"))
def cb_bm_autoupd(call):
    r = _bm_get_lic_inst(call)
    if not r: return
    uid, lic_id, page, lic, inst, is_admin = r
    bot.answer_callback_query(call.id)
    from ..deployer import _run, service_name as _svc
    svc = _svc(inst["project"], inst["bot_token"])
    timer_svc = f"{svc}-autoupdate.timer"
    ok_check, status_out = _run(f"systemctl is-active {timer_svc}")
    is_active = (status_out.strip() == "active")
    if is_active:
        _run(f"systemctl stop {timer_svc} ; systemctl disable {timer_svc}")
        msg = "🔕 اتوآپدیت خاموش شد."
    else:
        _run(f"systemctl enable {timer_svc} ; systemctl start {timer_svc}")
        msg = "🔔 اتوآپدیت روشن شد."
    bot.send_message(uid, msg)
    call.data = f"bot_manage:{lic_id}:{page}"
    cb_bot_manage(call)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bm:edit:"))
def cb_bm_edit(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    lic_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    lic = get_license(lic_id)
    is_admin = uid in ADMIN_IDS
    if not lic or (lic["user_id"] != uid and not is_admin):
        bot.answer_callback_query(call.id, "❌ دسترسی ندارید.", show_alert=True)
        return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔑 تغییر توکن",          callback_data=f"bm:edit_field:token:{lic_id}:{page}"))
    kb.add(types.InlineKeyboardButton("🆔 تغییر آیدی ادمین",    callback_data=f"bm:edit_field:admin_id:{lic_id}:{page}"))
    kb.add(types.InlineKeyboardButton("🤖 تغییر یوزرنیم ربات", callback_data=f"bm:edit_field:username:{lic_id}:{page}"))
    kb.add(types.InlineKeyboardButton("📞 تغییر یوزرنیم پشتیبانی", callback_data=f"bm:edit_field:support:{lic_id}:{page}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"bot_manage:{lic_id}:{page}"))
    try:
        bot.edit_message_text(
            f"✏️ <b>تغییر اطلاعات ربات @{esc(lic.get('bot_username') or '—')}</b>\n\nکدام مورد را می‌خواهید تغییر دهید؟",
            uid, call.message.message_id, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(uid, "✏️ کدام مورد را تغییر دهید؟", reply_markup=kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bm:edit_field:"))
def cb_bm_edit_field(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    field = parts[2]
    lic_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 else 0
    lic = get_license(lic_id)
    is_admin = uid in ADMIN_IDS
    if not lic or (lic["user_id"] != uid and not is_admin):
        bot.answer_callback_query(call.id, "❌ دسترسی ندارید.", show_alert=True)
        return
    labels = {
        "token":    "🔑 توکن جدید را بفرستید (مثلاً <code>123456:ABC...</code>):",
        "admin_id": "🆔 آیدی عددی ادمین جدید را بفرستید:",
        "username": "🤖 یوزرنیم ربات جدید را بفرستید (مثلاً @MyBot):",
        "support":  "📞 یوزرنیم پشتیبانی جدید را بفرستید:",
    }
    USER_STATE[uid] = {"step": "bm_edit_field", "field": field, "lic_id": lic_id, "page": page,
                       "msg_id": call.message.message_id}
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data=f"bm:edit:{lic_id}:{page}"))
    try:
        bot.edit_message_text(labels.get(field, "مقدار جدید را بفرستید:"),
                              uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, labels.get(field, "مقدار جدید را بفرستید:"), reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


# ── Donate ────────────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "donate")
def cb_donate(call):
    uid = call.from_user.id
    USER_STATE[uid] = {"step": "donate_amount", "msg_id": call.message.message_id}
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="main_menu"))
    try:
        bot.edit_message_text(
            "💛 <b>دونیت و حمایت از دولوپر</b>\n\n"
            "ممنون که می‌خواهید از توسعه‌دهنده حمایت کنید! 🙏\n\n"
            "مبلغ دونیت را به <b>دلار (USDT)</b> وارد کنید:\n"
            "مثال: <code>5</code> یا <code>10</code>",
            uid, call.message.message_id, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(uid, "💛 مبلغ دونیت را به USDT وارد کنید:", reply_markup=kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("donate_gw:"))
def cb_donate_gw(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    gw = parts[1]
    amount = float(parts[2])

    from ..gateways.base import is_gateway_available, is_card_info_complete
    from ..db import setting_get as sg

    # Crypto: show coin selection directly (no IRT needed)
    if gw == "crypto":
        _show_donate_crypto(call, uid, amount)
        return

    # Convert USDT -> Toman for rial gateways
    rate = _get_usdt_to_toman()
    amount_irt = int(amount * rate) if rate else 0

    donate_id = create_donate_payment(uid, amount, "USDT", gw)

    # Card to card
    if gw == "card":
        card = sg("payment_card", "—")
        bank = sg("payment_bank", "—")
        owner = sg("payment_owner", "—")
        irt_line = f"\n💵 معادل: <b>{_fmt_toman(amount_irt)} تومان</b>" if amount_irt else ""
        text = (
            f"💳 <b>پرداخت کارت به کارت</b>\n\n"
            f"💰 مبلغ: <b>{amount} USDT</b>{irt_line}\n\n"
            f"🏦 بانک: <b>{esc(bank)}</b>\n"
            f"💳 شماره کارت: <code>{esc(card)}</code>\n"
            f"👤 به نام: <b>{esc(owner)}</b>\n\n"
            f"پس از پرداخت رسید خود را برای ادمین ارسال کنید:\n{SUPPORT_USERNAME}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="donate"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
        u = get_user(uid)
        uname = f"@{u['username']}" if u and u.get("username") else str(uid)
        for adm in ADMIN_IDS:
            try:
                bot.send_message(adm,
                    f"💛 <b>دونیت جدید (کارت)</b>\n"
                    f"👤 {esc(uname)} — <code>{uid}</code>\n"
                    f"💰 {amount} USDT\n🆔 #{donate_id}",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        bot.answer_callback_query(call.id)
        return

    if not amount_irt:
        bot.answer_callback_query(call.id, "قیمت تومان در دسترس نیست. لطفاً بعداً تلاش کنید.", show_alert=True)
        return

    if gw == "tetrapay":
        from ..gateways.tetrapay import create_tetrapay_order
        ok, result = create_tetrapay_order(amount_irt, f"donate_{donate_id}", f"donate {amount} USDT")
        if ok:
            pay_url = result.get("payment_url") or result.get("url") or ""
            text = (
                f"🏦 <b>پرداخت Tetrapay</b>\n\n"
                f"💰 {amount} USDT — {_fmt_toman(amount_irt)} تومان\n\n"
                f"🔗 لینک پرداخت:\n{pay_url}\n\n"
                f"🆔 #{donate_id}"
            )
        else:
            text = f"خطا در Tetrapay:\n{result.get('error', str(result))[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton("💳 پرداخت آنلاین", url=pay_url))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="donate"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
        bot.answer_callback_query(call.id)
        return

    if gw == "swc":
        from ..gateways.swapwallet_crypto import create_swapwallet_crypto_invoice
        ok, result = create_swapwallet_crypto_invoice(amount_irt, f"donate_{donate_id}")
        if ok:
            pay_url = result.get("payment_url") or result.get("url") or ""
            text = (
                f"🔄 <b>پرداخت SwapWallet</b>\n\n"
                f"💰 {amount} USDT — {_fmt_toman(amount_irt)} تومان\n\n"
                f"🔗 لینک پرداخت:\n{pay_url}\n\n"
                f"🆔 #{donate_id}"
            )
        else:
            text = f"خطا در SwapWallet:\n{str(result)[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton("💳 پرداخت آنلاین", url=pay_url))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="donate"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
        bot.answer_callback_query(call.id)
        return

    if gw == "tronpays":
        from ..gateways.tronpays_rial import create_tronpays_rial_invoice
        ok, result = create_tronpays_rial_invoice(amount_irt, f"donate_{donate_id}")
        if ok:
            pay_url = result.get("payment_url") or result.get("url") or ""
            text = (
                f"⚡ <b>پرداخت TronPays</b>\n\n"
                f"💰 {amount} USDT — {_fmt_toman(amount_irt)} تومان\n\n"
                f"🔗 لینک پرداخت:\n{pay_url}\n\n"
                f"🆔 #{donate_id}"
            )
        else:
            text = f"خطا در TronPays:\n{str(result)[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton("💳 پرداخت آنلاین", url=pay_url))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="donate"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
        bot.answer_callback_query(call.id)
        return

    bot.answer_callback_query(call.id, "درگاه پشتیبانی‌نشده", show_alert=True)


def _show_donate_gateways(call, uid, amount_usdt):
    from ..gateways.base import is_gateway_available, is_card_info_complete
    from ..db import setting_get as sg
    rate = _get_usdt_to_toman()
    amount_irt = int(amount_usdt * rate) if rate else 0
    irt_str = f" ({_fmt_toman(amount_irt)} تومان)" if amount_irt else ""
    kb = types.InlineKeyboardMarkup()
    if is_gateway_available("card") and is_card_info_complete():
        lbl = sg("gw_card_display_name", "").strip() or "💳 کارت به کارت"
        kb.add(types.InlineKeyboardButton(lbl + irt_str, callback_data=f"donate_gw:card:{amount_usdt}"))
    if is_gateway_available("tetrapay") and sg("tetrapay_api_key", ""):
        lbl = sg("gw_tetrapay_display_name", "").strip() or "🏦 Tetrapay"
        kb.add(types.InlineKeyboardButton(lbl + irt_str, callback_data=f"donate_gw:tetrapay:{amount_usdt}"))
    if is_gateway_available("swapwallet_crypto") and sg("swapwallet_api_key", ""):
        lbl = sg("gw_swapwallet_crypto_display_name", "").strip() or "🔄 SwapWallet"
        kb.add(types.InlineKeyboardButton(lbl + irt_str, callback_data=f"donate_gw:swc:{amount_usdt}"))
    if is_gateway_available("tronpays_rial") and sg("tronpays_api_key", ""):
        lbl = sg("gw_tronpays_rial_display_name", "").strip() or "⚡ TronPays"
        kb.add(types.InlineKeyboardButton(lbl + irt_str, callback_data=f"donate_gw:tronpays:{amount_usdt}"))
    if is_gateway_available("crypto"):
        lbl = sg("gw_crypto_display_name", "").strip() or "💎 ارز دیجیتال"
        kb.add(types.InlineKeyboardButton(lbl, callback_data=f"donate_gw:crypto:{amount_usdt}"))
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="main_menu"))
    toman_line = f"\n💵 معادل: <b>{_fmt_toman(amount_irt)} تومان</b>" if amount_irt else ""
    text = (
        f"💛 <b>دونیت — {amount_usdt} USDT</b>{toman_line}\n\n"
        "روش پرداخت را انتخاب کنید:"
    )
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")


def _show_donate_crypto(call, uid, amount_usdt):
    from ..config import CRYPTO_COINS
    from ..db import setting_get as sg
    kb = types.InlineKeyboardMarkup()
    for coin_key, coin_label in CRYPTO_COINS:
        addr = sg(f"crypto_{coin_key}", "")
        if addr:
            kb.add(types.InlineKeyboardButton(coin_label, callback_data=f"donate_crypto:{coin_key}:{amount_usdt}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="donate"))
    try:
        bot.edit_message_text(
            f"💎 <b>پرداخت با ارز دیجیتال</b>\n💰 {amount_usdt} USDT\nنوع ارز را انتخاب کنید:",
            uid, call.message.message_id, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(uid, "💎 نوع ارز را انتخاب کنید:", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("donate_crypto:"))
def cb_donate_crypto(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    coin_key = parts[1]
    amount_usdt = float(parts[2])
    from ..config import CRYPTO_COINS, CRYPTO_API_SYMBOLS
    from ..db import setting_get as sg
    addr = sg(f"crypto_{coin_key}", "")
    label = next((l for k, l in CRYPTO_COINS if k == coin_key), coin_key)
    if not addr:
        bot.answer_callback_query(call.id, "آدرس این ارز هنوز ثبت نشده.", show_alert=True)
        return
    api_symbol = CRYPTO_API_SYMBOLS.get(coin_key, coin_key.upper())
    coin_amount = _get_coin_amount(amount_usdt, api_symbol)
    coin_line = f"\n💱 معادل: <b>{_fmt_coin(coin_amount)} {api_symbol}</b>" if coin_amount else ""
    text = (
        f"💛 <b>دونیت با {label}</b>\n\n"
        f"💰 مبلغ: <b>{amount_usdt} USDT</b>{coin_line}\n\n"
        f"📬 آدرس:\n<code>{esc(addr)}</code>\n\n"
        f"پس از ارسال به {SUPPORT_USERNAME} اطلاع دهید."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="donate"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


# ── Admin Panel ───────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "admin_panel")
def cb_admin_panel(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید.", show_alert=True)
        return
    USER_STATE.pop(uid, None)
    show_admin_panel(uid)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "adm:emoji_id_tool")
def cb_emoji_id_tool(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید.", show_alert=True)
        return

    USER_STATE[uid] = {"step": "adm_extract_emoji_id"}
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_panel"))
    text = (
        "🆔 <b>دریافت آیدی ایموجی پریمیوم</b>\n\n"
        "یک یا چند ایموجی معمولی / Premium / Custom بفرست.\n"
        "ربات هر ایموجی را به صورت <b>خود ایموجی → آیدی پریمیوم</b> نمایش می‌دهد.\n\n"
        "💡 اگر موردی پریمیوم نباشد، جلوی آن <code>—</code> می‌گذارد."
    )
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


# ── Admin: All Licenses (paginated, searchable) ──────────────────────────────
def _send_lic_list(uid, msg_id, page=0, search_query=None):
    all_lics = get_all_licenses()
    if search_query:
        q = search_query.lower()
        all_lics = [l for l in all_lics if
                    q in str(l.get('user_id', '')).lower() or
                    q in (l.get('bot_token') or '').lower() or
                    q in (l.get('bot_username') or '').lower() or
                    q in (l.get('support_user') or '').lower() or
                    q in (l.get('admin_id') or '').lower()]
    total = len(all_lics)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = all_lics[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    search_label = f" | جستجو: {search_query}" if search_query else ""
    text = f"📋 <b>همه لایسنس‌ها ({total}){esc(search_label)}</b>\nصفحه {page+1} از {pages}"

    kb = types.InlineKeyboardMarkup()
    # Search button at top
    kb.add(types.InlineKeyboardButton("🔍 جستجو", callback_data=f"adm:lic_search_init:{page}"))
    for lic in chunk:
        bot_name = f"@{lic['bot_username']}" if lic.get('bot_username') else f"#{lic['id']}"
        remaining = _remaining(lic['expires_at'])
        kb.row(
            types.InlineKeyboardButton(bot_name, callback_data=f"adm:lic_detail:{lic['id']}:{page}"),
            types.InlineKeyboardButton(remaining, callback_data=f"adm:lic_detail:{lic['id']}:{page}"),
        )
    # Pagination
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀ قبلی", callback_data=f"adm:all_lic:{page-1}"))
    if page < pages - 1:
        nav.append(types.InlineKeyboardButton("بعدی ▶", callback_data=f"adm:all_lic:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_panel"))

    try:
        bot.edit_message_text(text, uid, msg_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data == "adm:all_lic")
def cb_adm_all_lic(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    _send_lic_list(uid, call.message.message_id, page=0)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:all_lic:"))
def cb_adm_all_lic_page(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    page = int(call.data.split(":")[2])
    sq = USER_STATE.get(uid, {}).get("lic_search")
    _send_lic_list(uid, call.message.message_id, page=page, search_query=sq)
    bot.answer_callback_query(call.id)


# ── Admin: License Search ─────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:lic_search_init:"))
def cb_adm_lic_search_init(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    page = int(call.data.split(":")[2])
    USER_STATE[uid] = {"step": "adm_lic_search", "lic_page": page, "msg_id": call.message.message_id}
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data=f"adm:all_lic:{page}"))
    try:
        bot.edit_message_text(
            "🔍 <b>جستجوی لایسنس</b>\n\nمتن جستجو را بفرستید:\n(آیدی عددی / توکن / یوزرنیم ربات / یوزرنیم پشتیبانی)",
            uid, call.message.message_id, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(uid, "🔍 متن جستجو را بفرستید:", reply_markup=kb)
    bot.answer_callback_query(call.id)


# ── Admin: License Detail ─────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:lic_detail:"))
def cb_adm_lic_detail(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    lic_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    lic = get_license(lic_id)
    if not lic:
        bot.answer_callback_query(call.id, "❌ لایسنس پیدا نشد.", show_alert=True)
        return

    # Find buyer
    owner = get_user(lic['user_id'])
    owner_name = ""
    if owner:
        owner_name = owner.get('first_name') or ""
        if owner.get('username'):
            owner_name += f" (@{owner['username']})"

    # Get instance for this license (to check live status)
    inst = get_instance_by_token(lic['bot_token'])
    live_st = "—"
    if inst:
        live_st = deployer_status(inst["project"], inst["bot_token"])

    text = (
        f"🔍 <b>جزئیات لایسنس #{lic['id']}</b>\n\n"
        f"🤖 یوزرنیم ربات: @{esc(lic.get('bot_username') or '—')}\n"
        f"🔑 توکن: <code>{esc(lic.get('bot_token') or '—')}</code>\n"
        f"🆔 آیدی ادمین: <code>{esc(lic.get('admin_id') or '—')}</code>\n"
        f"📞 یوزرنیم پشتیبانی: @{esc(lic.get('support_user') or '—')}\n"
        f"📌 پلن: {_plan_label(lic['plan'])}\n"
        f"📊 وضعیت: {_status_label(lic['status'])}\n"
        f"🖥 وضعیت سرویس: {live_st}\n"
        f"📅 ساخت: {_fmt_time(lic['created_at'])}\n"
        f"⏳ انقضا: {_fmt_time(lic['expires_at'])}\n"
        f"⏱ باقیمانده: {_remaining(lic['expires_at'])}\n\n"
        f"👤 خریدار: {esc(owner_name)} — <code>{lic['user_id']}</code>"
    )

    kb = types.InlineKeyboardMarkup()
    # Management actions (shared with user panel)
    kb.row(
        types.InlineKeyboardButton("▶ روشن",    callback_data=f"bm:start:{lic_id}:{page}"),
        types.InlineKeyboardButton("⏹ خاموش",  callback_data=f"bm:stop:{lic_id}:{page}"),
        types.InlineKeyboardButton("🔁 ریستارت", callback_data=f"bm:restart:{lic_id}:{page}"),
    )
    kb.row(
        types.InlineKeyboardButton("🔄 آپدیت",          callback_data=f"bm:update:{lic_id}:{page}"),
        types.InlineKeyboardButton("📋 لاگ‌های ربات",   callback_data=f"bm:logs:{lic_id}:{page}"),
    )
    kb.row(
        types.InlineKeyboardButton("✏️ تغییر اطلاعات", callback_data=f"bm:edit:{lic_id}:{page}"),
        types.InlineKeyboardButton("🔃 اتوآپدیت",       callback_data=f"bm:autoupd:{lic_id}:{page}"),
    )
    # Admin-only actions
    kb.row(
        types.InlineKeyboardButton("⏳ تمدید", callback_data=f"adm:extend:{lic_id}"),
        types.InlineKeyboardButton("🚫 معلق", callback_data=f"adm:suspend:{lic_id}"),
        types.InlineKeyboardButton("🗑 حذف", callback_data=f"adm:lic_delete:{lic_id}:{page}"),
    )
    kb.add(types.InlineKeyboardButton("📥 ری‌استور دیتابیس", callback_data=f"adm:lic_restore:{lic_id}:{page}"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data=f"adm:all_lic:{page}"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


# ── Admin: License Start/Stop/Restart/Update ──────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:lic_start:"))
def cb_adm_lic_start(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    lic_id, page = int(parts[2]), int(parts[3]) if len(parts) > 3 else 0
    lic = get_license(lic_id)
    if not lic:
        bot.answer_callback_query(call.id, "❌ لایسنس پیدا نشد.", show_alert=True)
        return
    inst = get_instance_by_token(lic['bot_token'])
    if not inst:
        bot.answer_callback_query(call.id, "❌ نمونه‌ای برای این لایسنس نیست.", show_alert=True)
        return
    ok, _ = start_instance(inst["project"], inst["bot_token"])
    if ok:
        update_instance_status(inst["id"], "running")
    bot.answer_callback_query(call.id, "▶ روشن شد." if ok else "❌ خطا در روشن کردن", show_alert=True)
    # Refresh detail view
    call.data = f"adm:lic_detail:{lic_id}:{page}"
    cb_adm_lic_detail(call)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:lic_stop:"))
def cb_adm_lic_stop(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    lic_id, page = int(parts[2]), int(parts[3]) if len(parts) > 3 else 0
    lic = get_license(lic_id)
    if not lic:
        bot.answer_callback_query(call.id, "❌ لایسنس پیدا نشد.", show_alert=True)
        return
    inst = get_instance_by_token(lic['bot_token'])
    if not inst:
        bot.answer_callback_query(call.id, "❌ نمونه‌ای برای این لایسنس نیست.", show_alert=True)
        return
    ok, _ = stop_instance(inst["project"], inst["bot_token"])
    if ok:
        update_instance_status(inst["id"], "stopped")
    bot.answer_callback_query(call.id, "⏹ خاموش شد." if ok else "❌ خطا در خاموش کردن", show_alert=True)
    call.data = f"adm:lic_detail:{lic_id}:{page}"
    cb_adm_lic_detail(call)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:lic_restart:"))
def cb_adm_lic_restart(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    lic_id, page = int(parts[2]), int(parts[3]) if len(parts) > 3 else 0
    lic = get_license(lic_id)
    if not lic:
        bot.answer_callback_query(call.id, "❌ لایسنس پیدا نشد.", show_alert=True)
        return
    inst = get_instance_by_token(lic['bot_token'])
    if not inst:
        bot.answer_callback_query(call.id, "❌ نمونه‌ای برای این لایسنس نیست.", show_alert=True)
        return
    ok, _ = restart_instance(inst["project"], inst["bot_token"])
    if ok:
        update_instance_status(inst["id"], "running")
    bot.answer_callback_query(call.id, "🔁 ری‌استارت شد." if ok else "❌ خطا", show_alert=True)
    call.data = f"adm:lic_detail:{lic_id}:{page}"
    cb_adm_lic_detail(call)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:lic_update:"))
def cb_adm_lic_update(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    lic_id, page = int(parts[2]), int(parts[3]) if len(parts) > 3 else 0
    lic = get_license(lic_id)
    if not lic:
        bot.answer_callback_query(call.id, "❌ لایسنس پیدا نشد.", show_alert=True)
        return
    inst = get_instance_by_token(lic['bot_token'])
    if not inst:
        bot.answer_callback_query(call.id, "❌ نمونه‌ای برای این لایسنس نیست.", show_alert=True)
        return
    bot.answer_callback_query(call.id, "🔄 در حال آپدیت...", show_alert=True)

    def _do():
        ok, msg = update_instance(inst["project"], inst["bot_token"])
        try:
            if ok:
                update_instance_status(inst["id"], "running")
                bot.send_message(uid, f"✅ آپدیت لایسنس #{lic_id} (@{esc(lic.get('bot_username',''))}) موفق بود.")
            else:
                bot.send_message(uid, f"❌ آپدیت لایسنس #{lic_id} ناموفق: {msg[:200]}")
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()


# ── Admin: Restore Instance DB ───────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:lic_restore:"))
def cb_adm_lic_restore(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    lic_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    lic = get_license(lic_id)
    if not lic:
        bot.answer_callback_query(call.id, "❌ لایسنس پیدا نشد.", show_alert=True)
        return
    inst = get_instance_by_token(lic["bot_token"])
    if not inst:
        bot.answer_callback_query(call.id, "❌ نمونه‌ای برای این لایسنس وجود ندارد.", show_alert=True)
        return
    USER_STATE[uid] = {
        "step": "restore_db",
        "lic_id": lic_id,
        "page": page,
        "project": inst["project"],
        "bot_token": lic["bot_token"],
        "bot_username": lic.get("bot_username", ""),
        "msg_id": call.message.message_id,
    }
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data=f"adm:lic_detail:{lic_id}:{page}"))
    try:
        bot.edit_message_text(
            f"📥 <b>ری‌استور دیتابیس — @{esc(lic.get('bot_username') or str(lic_id))}</b>\n\n"
            "⚠️ ربات موقتاً متوقف، دیتابیس جایگزین، و سپس دوباره روشن می‌شود.\n"
            "بکاپ فعلی نیز نگه داشته می‌شود و در صورت خطا خودکار برمی‌گردد.\n"
            "فقط بکاپ‌های اصلی <b>ConfigFlow / Seamless</b> پذیرفته می‌شوند.\n\n"
            "فایل <code>.db</code> بکاپ را ارسال کنید:",
            uid, call.message.message_id, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(uid, "📥 فایل .db بکاپ را ارسال کنید:", reply_markup=kb)
    bot.answer_callback_query(call.id)


# ── Admin: Extend License ────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:extend:"))
def cb_adm_extend(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    lic_id = int(call.data.split(":")[2])
    USER_STATE[uid] = {"step": "adm_extend_hours", "lic_id": lic_id}
    text = f"⏳ <b>تمدید لایسنس #{lic_id}</b>\n\nچند ساعت تمدید شود؟ (مثلاً <code>720</code> = 30 روز)"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="admin_panel"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(uid, text, reply_markup=kb)
    bot.answer_callback_query(call.id)


# ── Admin: Suspend License ───────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:suspend:"))
def cb_adm_suspend(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    lic_id = int(call.data.split(":")[2])
    update_license_status(lic_id, "suspended")
    lic = get_license(lic_id)
    if lic:
        try:
            bot.send_message(lic["user_id"], f"🚫 لایسنس #{lic_id} معلق شد.\nبرای اطلاعات بیشتر: {SUPPORT_USERNAME}")
        except Exception:
            pass
    bot.answer_callback_query(call.id, f"🚫 لایسنس #{lic_id} معلق شد.", show_alert=True)
    cb_adm_all_lic(call)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:lic_delete:"))
def cb_adm_lic_delete(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    lic_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    lic = get_license(lic_id)
    if not lic:
        bot.answer_callback_query(call.id, "❌ لایسنس پیدا نشد.", show_alert=True)
        return

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ تایید حذف", callback_data=f"adm:lic_delete_yes:{lic_id}:{page}"),
        types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"adm:lic_detail:{lic_id}:{page}"),
    )
    text = (
        f"⚠️ <b>حذف لایسنس #{lic_id}</b>\n\n"
        f"🤖 ربات: @{esc(lic.get('bot_username') or '—')}\n"
        "با تایید شما، سرویس ربات متوقف و پوشه/رکوردهای این لایسنس حذف می‌شود.\n"
        "این عملیات قابل بازگشت نیست."
    )
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:lic_delete_yes:"))
def cb_adm_lic_delete_yes(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    lic_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    lic = get_license(lic_id)
    if not lic:
        bot.answer_callback_query(call.id, "❌ لایسنس پیدا نشد.", show_alert=True)
        return

    inst = get_instance_by_token(lic["bot_token"])
    if inst:
        try:
            remove_instance(inst["project"], inst["bot_token"])
        except Exception:
            pass

    delete_license(lic_id)

    try:
        bot.send_message(
            lic["user_id"],
            f"🗑 لایسنس #{lic_id} (@{esc(lic.get('bot_username') or '—')}) توسط مدیریت حذف شد.\n"
            f"برای اطلاعات بیشتر: {SUPPORT_USERNAME}",
            parse_mode="HTML",
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id, f"🗑 لایسنس #{lic_id} حذف شد.", show_alert=True)
    call.data = f"adm:all_lic:{page}"
    cb_adm_all_lic(call)


# ── Admin: Stats ─────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm:stats")
def cb_adm_stats(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    show_admin_panel(uid)
    bot.answer_callback_query(call.id)


# ── Admin: Users (paginated) ──────────────────────────────────────────────────
def _send_user_list(uid, msg_id, page=0, selected_uid=None):
    users = get_all_users()
    total = len(users)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = users[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    header = ""
    if selected_uid:
        u = get_user(selected_uid)
        if u:
            import datetime
            reg_time = datetime.datetime.fromtimestamp(u['registered']).strftime("%Y-%m-%d %H:%M") if u.get('registered') else "—"
            uname = f"@{u['username']}" if u.get('username') else "—"
            header = (
                f"ℹ️ <b>اطلاعات کاربر:</b>\n"
                f"📛 نام: <b>{esc(u.get('first_name') or '—')}</b>\n"
                f"🔖 یوزرنیم: <b>{esc(uname)}</b>\n"
                f"🆔 آیدی: <code>{u['user_id']}</code>\n"
                f"📅 استارت ربات: <b>{reg_time}</b>\n\n"
            )

    text = f"{header}👥 <b>کاربران ({total}):</b>\nصفحه {page+1} از {pages}"

    kb = types.InlineKeyboardMarkup()
    for u in chunk:
        d_name = f"@{u['username']}" if u.get('username') else esc(u.get('first_name') or '—')
        kb.row(
            types.InlineKeyboardButton(d_name, callback_data=f"adm:user_info:{u['user_id']}:{page}"),
            types.InlineKeyboardButton(str(u['user_id']), callback_data=f"adm:user_info:{u['user_id']}:{page}"),
        )
        if selected_uid and selected_uid == u['user_id']:
            # sub-buttons for selected user
            kb.row(
                types.InlineKeyboardButton("✉️ پیام خصوصی", callback_data=f"adm:msg_user:{u['user_id']}:{page}"),
                types.InlineKeyboardButton("🤖 ربات‌های کاربر", callback_data=f"adm:user_bots:{u['user_id']}:{page}"),
            )

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀ قبلی", callback_data=f"adm:users_pg:{page-1}"))
    if page < pages - 1:
        nav.append(types.InlineKeyboardButton("بعدی ▶", callback_data=f"adm:users_pg:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_panel"))

    try:
        bot.edit_message_text(text, uid, msg_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data == "adm:users")
def cb_adm_users(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    _send_user_list(uid, call.message.message_id, page=0)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:users_pg:"))
def cb_adm_users_pg(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    page = int(call.data.split(":")[2])
    _send_user_list(uid, call.message.message_id, page=page)
    bot.answer_callback_query(call.id)


# ── Admin: User Info ──────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:user_info:"))
def cb_adm_user_info(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    target_uid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    _send_user_list(uid, call.message.message_id, page=page, selected_uid=target_uid)
    bot.answer_callback_query(call.id)


# ── Admin: Message user ───────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:msg_user:"))
def cb_adm_msg_user(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    target_uid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    USER_STATE[uid] = {"step": "adm_msg_user", "target_uid": target_uid, "page": page, "msg_id": call.message.message_id}
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data=f"adm:user_info:{target_uid}:{page}"))
    try:
        bot.edit_message_text(
            f"✉️ <b>ارسال پیام به کاربر <code>{target_uid}</code></b>\n\nمتن پیام را بفرستید:",
            uid, call.message.message_id, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(uid, "متن پیام را بفرستید:", reply_markup=kb)
    bot.answer_callback_query(call.id)


# ── Admin: User's bots ────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:user_bots:"))
def cb_adm_user_bots(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    target_uid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    lics = get_user_licenses(target_uid)
    if not lics:
        bot.answer_callback_query(call.id, "📋 این کاربر لایسنسی ندارد.", show_alert=True)
        return
    u = get_user(target_uid)
    uname = f"@{u['username']}" if u and u.get('username') else str(target_uid)
    text = f"🤖 <b>ربات‌های {esc(uname)}:</b>\n"
    kb = types.InlineKeyboardMarkup()
    for lic in lics:
        bot_name = f"@{lic['bot_username']}" if lic.get('bot_username') else f"#{lic['id']}"
        remaining = _remaining(lic['expires_at'])
        kb.row(
            types.InlineKeyboardButton(bot_name, callback_data=f"adm:lic_detail:{lic['id']}:{0}"),
            types.InlineKeyboardButton(remaining, callback_data=f"adm:lic_detail:{lic['id']}:{0}"),
        )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"adm:user_info:{target_uid}:{page}"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


# ── Admin: Manual License ────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm:manual_lic")
def cb_adm_manual(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    USER_STATE[uid] = {"step": "adm_manual_uid"}
    text = "➕ <b>صدور لایسنس دستی</b>\n\nآیدی عددی کاربر را بفرستید:"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="admin_panel"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(uid, text, reply_markup=kb)
    bot.answer_callback_query(call.id)


# ── Admin: Update All ─────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm:update_all")
def cb_adm_update_all(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    bot.answer_callback_query(call.id, "🔄 در حال آپدیت همه ربات‌ها...", show_alert=True)

    def _do():
        results = update_all_instances()
        if not results:
            try:
                bot.send_message(uid, "📋 هیچ نمونه‌ای برای آپدیت یافت نشد.")
            except Exception:
                pass
            return
        text = "🔄 <b>نتیجه آپدیت همه ربات‌ها</b>\n\n"
        for name, ok, msg in results:
            icon = "✅" if ok else "❌"
            text += f"{icon} {name}: {msg[:80]}\n"
        try:
            bot.send_message(uid, text, parse_mode="HTML")
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()


@bot.callback_query_handler(func=lambda c: c.data == "adm:auto_update_status")
def cb_adm_auto_update_status(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return

    cf_has, cf_local, cf_remote, cf_err = repo_has_updates("configflow")
    sm_has, sm_local, sm_remote, sm_err = repo_has_updates("seamless")

    def _fmt_line(label, has_update, local_rev, remote_rev, err):
        if err:
            return f"❌ {label}: {esc(err[:120])}"
        if has_update:
            return f"🟡 {label}: آپدیت جدید آماده است ({(local_rev or 'none')[:7]} → {(remote_rev or 'none')[:7]})"
        return f"✅ {label}: روی آخرین نسخه است ({(remote_rev or local_rev or 'none')[:7]})"

    status_text = (
        "🛰 <b>وضعیت اتوآپدیت</b>\n\n"
        f"{'✅ فعال' if AUTO_UPDATE_ENABLED else '❌ غیرفعال'} | بازه چک: <b>{AUTO_UPDATE_INTERVAL}</b> ثانیه\n\n"
        f"{_fmt_line('ConfigFlow', cf_has, cf_local, cf_remote, cf_err)}\n"
        f"{_fmt_line('Seamless', sm_has, sm_local, sm_remote, sm_err)}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("♻️ اجرای آپدیت همین حالا", callback_data="adm:update_all"))
    kb.add(types.InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_panel"))
    try:
        bot.edit_message_text(status_text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, status_text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "adm:broadcast")
def cb_adm_broadcast(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    USER_STATE[uid] = {"step": "adm_broadcast"}
    text = "📣 <b>ارسال پیام همگانی</b>\n\nمتن پیام خود را بفرستید:"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="admin_panel"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(uid, text, reply_markup=kb)
    bot.answer_callback_query(call.id)


# ── Admin: Gateways Settings ──────────────────────────────────────────────────
def _gw_show_main(uid, msg_id):
    """Show the main gateway settings panel."""
    card_en = setting_get("gw_card_enabled", "0") == "1"
    crypto_en = setting_get("gw_crypto_enabled", "0") == "1"
    tetrapay_en = setting_get("gw_tetrapay_enabled", "0") == "1"
    swcrypto_en = setting_get("gw_swapwallet_crypto_enabled", "0") == "1"
    tronpay_en = setting_get("gw_tronpays_rial_enabled", "0") == "1"

    text = (
        "💳 <b>تنظیمات درگاه‌های پرداخت</b>\n\n"
        f"{'✅' if card_en else '❌'} کارت به کارت\n"
        f"{'✅' if crypto_en else '❌'} ارز دیجیتال (دستی)\n"
        f"{'✅' if tetrapay_en else '❌'} Tetrapay\n"
        f"{'✅' if swcrypto_en else '❌'} Swapwallet Crypto\n"
        f"{'✅' if tronpay_en else '❌'} TronPays (ریال)\n"
    )
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(
            f"{'✅' if card_en else '❌'} کارت به کارت",
            callback_data="gw:card:main"
        ),
        types.InlineKeyboardButton(
            f"{'✅' if crypto_en else '❌'} ارز دیجیتال",
            callback_data="gw:crypto:main"
        ),
    )
    kb.row(
        types.InlineKeyboardButton(
            f"{'✅' if tetrapay_en else '❌'} Tetrapay",
            callback_data="gw:tetrapay:main"
        ),
        types.InlineKeyboardButton(
            f"{'✅' if swcrypto_en else '❌'} Swapwallet",
            callback_data="gw:swapwallet_crypto:main"
        ),
    )
    kb.add(
        types.InlineKeyboardButton(
            f"{'✅' if tronpay_en else '❌'} TronPays (ریال)",
            callback_data="gw:tronpays_rial:main"
        )
    )
    kb.add(types.InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_panel"))
    try:
        bot.edit_message_text(text, uid, msg_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data == "adm:gateways")
def cb_adm_gateways(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید.", show_alert=True)
        return
    _gw_show_main(uid, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("gw:") and c.data.endswith(":main"))
def cb_gw_sub_main(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    gw = call.data.split(":")[1]
    _gw_show_sub(uid, call.message.message_id, gw)
    bot.answer_callback_query(call.id)


def _gw_show_sub(uid, msg_id, gw):
    """Show settings page for a specific gateway."""
    enabled = setting_get(f"gw_{gw}_enabled", "0") == "1"
    toggle_label = "🔴 غیرفعال‌کردن" if enabled else "🟢 فعال‌کردن"
    status_text = "✅ فعال" if enabled else "❌ غیرفعال"

    GW_NAMES = {
        "card": "💳 کارت به کارت",
        "crypto": "💎 ارز دیجیتال (دستی)",
        "tetrapay": "⚡ Tetrapay",
        "swapwallet_crypto": "🌊 Swapwallet Crypto",
        "tronpays_rial": "🔵 TronPays (ریال)",
    }
    gw_name = GW_NAMES.get(gw, gw)

    from ..config import CRYPTO_COINS
    lines = [f"⚙️ <b>تنظیمات {gw_name}</b>", f"📊 وضعیت: {status_text}", ""]

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(toggle_label, callback_data=f"gw:{gw}:toggle"))

    if gw == "card":
        card = setting_get("payment_card", "—")
        bank = setting_get("payment_bank", "—")
        owner = setting_get("payment_owner", "—")
        lines += [
            f"💳 شماره کارت: <code>{esc(card)}</code>",
            f"🏦 بانک: {esc(bank)}",
            f"👤 به نام: {esc(owner)}",
        ]
        kb.row(
            types.InlineKeyboardButton("✏️ شماره کارت", callback_data="gw:card:set:payment_card"),
            types.InlineKeyboardButton("✏️ بانک", callback_data="gw:card:set:payment_bank"),
        )
        kb.add(types.InlineKeyboardButton("✏️ نام صاحب کارت", callback_data="gw:card:set:payment_owner"))

    elif gw == "crypto":
        lines.append("📬 آدرس‌های ارز دیجیتال:")
        for coin_key, coin_label in CRYPTO_COINS:
            addr = setting_get(f"crypto_{coin_key}", "—")
            lines.append(f"  {coin_label}: <code>{esc(addr)}</code>")
            kb.add(types.InlineKeyboardButton(f"✏️ {coin_label}", callback_data=f"gw:crypto:set:crypto_{coin_key}"))

    elif gw == "tetrapay":
        api_key = setting_get("tetrapay_api_key", "—")
        lines.append(f"🔑 API Key: <code>{esc(api_key)}</code>")
        kb.add(types.InlineKeyboardButton("✏️ API Key", callback_data="gw:tetrapay:set:tetrapay_api_key"))

    elif gw == "swapwallet_crypto":
        api_key = setting_get("swapwallet_api_key", "—")
        sw_user = setting_get("swapwallet_username", "—")
        lines += [
            f"🔑 API Key: <code>{esc(api_key)}</code>",
            f"👤 Username: {esc(sw_user)}",
        ]
        kb.row(
            types.InlineKeyboardButton("✏️ API Key", callback_data="gw:swapwallet_crypto:set:swapwallet_api_key"),
            types.InlineKeyboardButton("✏️ Username", callback_data="gw:swapwallet_crypto:set:swapwallet_username"),
        )

    elif gw == "tronpays_rial":
        api_key = setting_get("tronpays_api_key", "—")
        lines.append(f"🔑 API Key: <code>{esc(api_key)}</code>")
        kb.add(types.InlineKeyboardButton("✏️ API Key", callback_data="gw:tronpays_rial:set:tronpays_api_key"))

    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="adm:gateways"))
    text = "\n".join(lines)
    try:
        bot.edit_message_text(text, uid, msg_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data.startswith("gw:") and ":toggle" in c.data)
def cb_gw_toggle(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    gw = call.data.split(":")[1]
    current = setting_get(f"gw_{gw}_enabled", "0")
    new_val = "0" if current == "1" else "1"
    setting_set(f"gw_{gw}_enabled", new_val)
    _gw_show_sub(uid, call.message.message_id, gw)
    status = "فعال" if new_val == "1" else "غیرفعال"
    bot.answer_callback_query(call.id, f"✅ درگاه {status} شد.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("gw:") and ":set:" in c.data)
def cb_gw_set_value(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    parts = call.data.split(":")
    # format: gw:{gw_name}:set:{setting_key}
    gw = parts[1]
    setting_key = ":".join(parts[3:])
    USER_STATE[uid] = {
        "step": "adm_gw_set",
        "gw": gw,
        "setting_key": setting_key,
        "msg_id": call.message.message_id,
    }
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data=f"gw:{gw}:main"))
    try:
        bot.edit_message_text(
            f"✏️ <b>ویرایش تنظیم: <code>{esc(setting_key)}</code></b>\n\nمقدار جدید را بفرستید:",
            uid, call.message.message_id, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(uid, "مقدار جدید را بفرستید:", reply_markup=kb)
    bot.answer_callback_query(call.id)


# 
#  BUY SUBSCRIPTION 
# 

# Plan IDs and their labels/package tags
_PLAN_INFO = {
    "cf_hosted":  ("⚡ ConfigFlow روی سرور ما", "configflow", "price_cf_hosted",  10),
    "sm_premium": ("💎 Seamless پرمیوم",       "seamless",   "price_sm_premium", 25),
}


def _get_usdt_to_toman():
    """Fetch current USDT->IRT rate via SwapWallet API. Returns 0 on failure."""
    from ..gateways.crypto import fetch_crypto_prices
    prices = fetch_crypto_prices()
    data = prices.get("USDT", {})
    if isinstance(data, dict):
        return data.get("irt", 0)
    return float(data) if data else 0


def _get_coin_amount(amount_usdt, coin_symbol):
    """Return how many units of coin_symbol equal amount_usdt USDT. None on failure."""
    from ..gateways.crypto import fetch_crypto_prices
    prices = fetch_crypto_prices()
    coin_data = prices.get(coin_symbol, {})
    usdt_rate = coin_data.get("usdt", 0) if isinstance(coin_data, dict) else 0
    if not usdt_rate:
        return None
    return amount_usdt / usdt_rate


def _fmt_coin(amount):
    """Format coin amount with appropriate decimal precision."""
    if amount is None:
        return "?"
    if amount >= 100:
        return f"{amount:.2f}"
    elif amount >= 1:
        return f"{amount:.4f}"
    else:
        return f"{amount:.6f}"


def _fmt_toman(n):
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


@bot.callback_query_handler(func=lambda c: c.data == "buy_subscription")
def cb_buy_subscription(call):
    uid = call.from_user.id
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⚡ ConfigFlow — سرور ما", callback_data="buy_type:cf"))
    kb.add(types.InlineKeyboardButton("💎 Seamless — پرمیوم",   callback_data="buy_type:seamless"))
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu"))
    text = (
        "🛒 <b>خرید اشتراک</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "محصول مورد نظر خود را انتخاب کنید:\n\n"
        "⚡ <b>ConfigFlow</b> — ربات فروش کانفیگ، اجرا روی سرور ما\n"
        "💎 <b>Seamless</b> — نسخه پیشرفته با امکانات بیشتر"
    )
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_type:"))
def cb_buy_type(call):
    uid = call.from_user.id
    btype = call.data.split(":")[1]
    rate = _get_usdt_to_toman()

    kb = types.InlineKeyboardMarkup()
    if btype == "cf":
        plan_id = "cf_hosted"
        label, _, key, default_price = _PLAN_INFO[plan_id]
        price_usdt = float(setting_get(key, str(default_price)))
        price_toman = int(price_usdt * rate) if rate else 0
        toman_line = f"\n🇮🇷 معادل: <b>{_fmt_toman(price_toman)} تومان</b>" if price_toman else ""
        text = (
            "⚡ <b>ConfigFlow — سرور ما</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 قیمت ماهانه: <b>{price_usdt:.0f} USDT</b>{toman_line}\n\n"
            "✅ راه‌اندازی و اجرای کامل روی سرور ما\n"
            "✅ آپدیت خودکار رایگان\n"
            "✅ پشتیبانی فنی"
        )
        kb.add(types.InlineKeyboardButton(f"⚡ خرید ConfigFlow — {price_usdt:.0f} USDT", callback_data=f"buy_plan:{plan_id}"))
    else:
        sm_premium_price = float(setting_get("price_sm_premium", "25"))
        sm_premium_toman = int(sm_premium_price * rate) if rate else 0
        p_toman = f"\n🇮🇷 معادل: <b>{_fmt_toman(sm_premium_toman)} تومان</b>" if sm_premium_toman else ""
        text = (
            "💎 <b>Seamless — پرمیوم</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 قیمت: <b>{sm_premium_price:.0f} USDT</b>{p_toman}\n\n"
            "✅ تمام امکانات ConfigFlow\n"
            "✅ مدیریت چند ربات روی سرور شما\n"
            "✅ آپدیت خودکار سرور"
        )
        kb.add(types.InlineKeyboardButton(f"💎 خرید Seamless پرمیوم — {sm_premium_price:.0f} USDT", callback_data="buy_plan:sm_premium"))

    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="buy_subscription"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_plan:"))
def cb_buy_plan(call):
    uid = call.from_user.id
    plan_id = call.data.split(":")[1]
    if plan_id not in _PLAN_INFO:
        bot.answer_callback_query(call.id, " پلن نامعتبر", show_alert=True)
        return
    label, pkg, price_key, default_price = _PLAN_INFO[plan_id]
    price_usdt = float(setting_get(price_key, str(default_price)))
    rate = _get_usdt_to_toman()
    price_toman = int(price_usdt * rate) if rate else 0

    USER_STATE[uid] = {
        "buy_plan":         plan_id,
        "buy_usdt":         price_usdt,
        "buy_toman":        price_toman,
        "buy_rate":         rate,
        "buy_pkg":          pkg,
        "msg_id":           call.message.message_id,
    }

    toman_line = f"\n🇮🇷 معادل: <b>{_fmt_toman(price_toman)} تومان</b>" if price_toman else ""
    text = (
        f"🧾 <b>تأیید سفارش</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 پلن انتخابی: <b>{label}</b>\n"
        f"💰 مبلغ: <b>{price_usdt:.0f} USDT</b>{toman_line}\n\n"
        f"🎟 آیا کد تخفیف دارید؟"
    )
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ بله، دارم", callback_data="buy_disc:yes"),
        types.InlineKeyboardButton("➡️ خیر، ادامه", callback_data="buy_disc:no"),
    )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="buy_subscription"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_disc:"))
def cb_buy_disc_yn(call):
    uid = call.from_user.id
    choice = call.data.split(":")[1]
    state = USER_STATE.get(uid, {})
    if not state.get("buy_plan"):
        bot.answer_callback_query(call.id, " لطفاً از ابتدا شروع کنید.", show_alert=True)
        return
    if choice == "yes":
        state["step"] = "buy_discount_code"
        USER_STATE[uid] = state
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="buy_disc:no"))
        try:
            bot.edit_message_text(
                "🎟 <b>کد تخفیف</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "کد تخفیف خود را وارد کنید:",
                uid, call.message.message_id, reply_markup=kb, parse_mode="HTML"
            )
        except Exception:
            bot.send_message(uid, "🎟 کد تخفیف را وارد کنید:", reply_markup=kb)
    else:
        # No discount  show gateways
        state.pop("step", None)
        USER_STATE[uid] = state
        _show_buy_gateways(call, uid)
    bot.answer_callback_query(call.id)


def _show_buy_gateways(call, uid):
    """Show available payment gateways for the current order in USER_STATE."""
    state = USER_STATE.get(uid, {})
    plan_id = state.get("buy_plan", "")
    final_usdt = state.get("buy_final_usdt", state.get("buy_usdt", 0))
    final_toman = state.get("buy_final_toman", state.get("buy_toman", 0))
    disc_code = state.get("buy_disc_code", "")
    disc_pct = state.get("buy_disc_pct", 0)

    label = _PLAN_INFO.get(plan_id, (plan_id,))[0]
    toman_line = f"\n🇮🇷 معادل: <b>{_fmt_toman(final_toman)} تومان</b>" if final_toman else ""
    disc_line = f"\n🎟 تخفیف: <b>{disc_pct:.0f}%</b> — کد: <code>{esc(disc_code)}</code>" if disc_code else ""
    text = (
        f"💳 <b>انتخاب درگاه پرداخت</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 پلن: <b>{label}</b>\n"
        f"💰 مبلغ نهایی: <b>{final_usdt:.2f} USDT</b>{toman_line}{disc_line}\n\n"
        "روش پرداخت را انتخاب کنید:"
    )
    from ..gateways.base import is_gateway_available, is_card_info_complete
    kb = types.InlineKeyboardMarkup()
    if is_gateway_available("card") and is_card_info_complete():
        kb.add(types.InlineKeyboardButton("🏦 کارت به کارت", callback_data="buy_gw:card"))
    if is_gateway_available("tetrapay") and setting_get("tetrapay_api_key", ""):
        kb.add(types.InlineKeyboardButton("💸 Tetrapay", callback_data="buy_gw:tetrapay"))
    if is_gateway_available("swapwallet_crypto") and setting_get("swapwallet_api_key", ""):
        kb.add(types.InlineKeyboardButton("🔗 Swapwallet Crypto", callback_data="buy_gw:swc"))
    if is_gateway_available("tronpays_rial") and setting_get("tronpays_api_key", ""):
        kb.add(types.InlineKeyboardButton("🇮🇷 TronPays (ریال)", callback_data="buy_gw:tronpays"))
    if is_gateway_available("crypto"):
        kb.add(types.InlineKeyboardButton("📈 ارز دیجیتال (دستی)", callback_data="buy_gw:crypto"))
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="main_menu"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_gw:"))
def cb_buy_gateway(call):
    uid = call.from_user.id
    gw = call.data.split(":")[1]
    state = USER_STATE.get(uid, {})
    plan_id = state.get("buy_plan", "")
    if not plan_id:
        bot.answer_callback_query(call.id, " اطلاعات سفارش پیدا نشد. دوباره شروع کنید.", show_alert=True)
        return

    final_usdt = state.get("buy_final_usdt", state.get("buy_usdt", 0))
    final_toman = state.get("buy_final_toman", state.get("buy_toman", 0))
    orig_usdt = state.get("buy_usdt", 0)
    orig_toman = state.get("buy_toman", 0)
    disc_code = state.get("buy_disc_code", "")
    disc_pct = state.get("buy_disc_pct", 0)
    label = _PLAN_INFO.get(plan_id, (plan_id,))[0]

    # Create order record
    order_id = create_subscription_order(
        uid, plan_id, orig_usdt, orig_toman, final_usdt, final_toman,
        gw, disc_code, disc_pct
    )

    bot.answer_callback_query(call.id)

    if gw == "card":
        card = setting_get("payment_card", "")
        bank = setting_get("payment_bank", "")
        owner = setting_get("payment_owner", "")
        toman_line = f"\n معادل به تومان: <b>{_fmt_toman(final_toman)} تومان</b>" if final_toman else ""
        text = (
            f" <b>پرداخت کارت به کارت</b>\n\n"
            f" پلن: {label}\n"
            f" مبلغ: <b>{final_usdt:.2f} USDT</b>{toman_line}\n\n"
            f" بانک: <b>{esc(bank)}</b>\n"
            f" شماره کارت: <code>{esc(card)}</code>\n"
            f" به نام: <b>{esc(owner)}</b>\n\n"
            f"✅ پس از واریز، <b>رسید یا تصویر پرداخت</b> را همین‌جا در ربات ارسال کنید.\n"
            f" شماره سفارش: <code>#{order_id}</code>"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="main_menu"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
        # Notify admins of new order (no receipt yet)
        u = get_user(uid)
        uname = f"@{u['username']}" if u and u.get("username") else str(uid)
        for adm in ADMIN_IDS:
            try:
                bot.send_message(adm,
                    f" <b>سفارش جدید (کارت) — در انتظار رسید</b>\n"
                    f" {esc(uname)}  <code>{uid}</code>\n"
                    f" پلن: {label}\n"
                    f" {final_usdt:.2f} USDT / {_fmt_toman(final_toman)} تومان\n"
                    f" سفارش #{order_id}", parse_mode="HTML"
                )
            except Exception:
                pass
        USER_STATE[uid] = {
            "step": "sub_receipt_wait",
            "order_id": order_id,
            "plan_id": plan_id,
        }

    elif gw == "tetrapay":
        if not final_toman:
            bot.send_message(uid, " قیمت به تومان در دسترس نیست. لطفاً بعداً تلاش کنید.")
            return
        from ..gateways.tetrapay import create_tetrapay_order
        ok, result = create_tetrapay_order(final_toman, f"sub_{order_id}", f"خرید {label}")
        if ok:
            pay_url = result.get("payment_url") or result.get("url") or result.get("Authority", "")
            text = (
                f" <b>پرداخت Tetrapay</b>\n\n"
                f" پلن: {label}\n"
                f" {_fmt_toman(final_toman)} تومان\n\n"
                f" لینک پرداخت:\n{pay_url or ''}\n\n"
                f" سفارش #{order_id}"
            )
        else:
            text = f" خطا در ایجاد فاکتور Tetrapay:\n{result.get('error', str(result))[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton(" پرداخت آنلاین", url=pay_url))
        kb.add(types.InlineKeyboardButton(" منوی اصلی", callback_data="main_menu"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")

    elif gw == "swc":
        if not final_toman:
            bot.send_message(uid, " قیمت به تومان در دسترس نیست.")
            return
        from ..gateways.swapwallet_crypto import create_swapwallet_crypto_invoice
        ok, result = create_swapwallet_crypto_invoice(final_toman, f"sub_{order_id}")
        if ok:
            pay_url = result.get("payment_url") or result.get("url") or ""
            text = (
                f" <b>پرداخت Swapwallet Crypto</b>\n\n"
                f" پلن: {label}\n"
                f" {_fmt_toman(final_toman)} تومان\n\n"
                f" لینک پرداخت:\n{pay_url or ''}\n\n"
                f" سفارش #{order_id}"
            )
        else:
            text = f" خطا در ایجاد فاکتور Swapwallet:\n{str(result)[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton(" پرداخت آنلاین", url=pay_url))
        kb.add(types.InlineKeyboardButton(" منوی اصلی", callback_data="main_menu"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")

    elif gw == "tronpays":
        if not final_toman:
            bot.send_message(uid, " قیمت به تومان در دسترس نیست.")
            return
        from ..gateways.tronpays_rial import create_tronpays_rial_invoice
        ok, result = create_tronpays_rial_invoice(final_toman, f"sub_{order_id}")
        if ok:
            pay_url = result.get("payment_url") or result.get("url") or ""
            text = (
                f" <b>پرداخت TronPays</b>\n\n"
                f" پلن: {label}\n"
                f" {_fmt_toman(final_toman)} تومان\n\n"
                f" لینک پرداخت:\n{pay_url or ''}\n\n"
                f" سفارش #{order_id}"
            )
        else:
            text = f" خطا در ایجاد فاکتور TronPays:\n{str(result)[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton(" پرداخت آنلاین", url=pay_url))
        kb.add(types.InlineKeyboardButton(" منوی اصلی", callback_data="main_menu"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")

    elif gw == "crypto":
        from ..config import CRYPTO_COINS
        kb2 = types.InlineKeyboardMarkup()
        for coin_key, coin_label in CRYPTO_COINS:
            addr = setting_get(f"crypto_{coin_key}", "")
            if addr:
                kb2.add(types.InlineKeyboardButton(coin_label, callback_data=f"buy_crypto:{coin_key}:{order_id}"))
        kb2.add(types.InlineKeyboardButton("🔙 انصراف", callback_data="main_menu"))
        try:
            bot.edit_message_text(
                f"💎 <b>پرداخت با ارز دیجیتال</b>\n💰 {final_usdt:.2f} USDT\nنوع ارز را انتخاب کنید:",
                uid, call.message.message_id, reply_markup=kb2, parse_mode="HTML"
            )
        except Exception:
            bot.send_message(uid, "💎 نوع ارز را انتخاب کنید:", reply_markup=kb2)

    # Card state is set inside the card block; only pop for non-card gateways
    if gw != "card":
        USER_STATE.pop(uid, None)


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_crypto:"))
def cb_buy_crypto(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    coin_key = parts[1]
    order_id = parts[2]
    from ..config import CRYPTO_COINS, CRYPTO_API_SYMBOLS
    addr = setting_get(f"crypto_{coin_key}", "")
    label = next((l for k, l in CRYPTO_COINS if k == coin_key), coin_key)
    if not addr:
        bot.answer_callback_query(call.id, "آدرس این ارز ثبت نشده است.", show_alert=True)
        return
    order = get_subscription_order(order_id)
    amount_usdt = float(order["final_usdt"]) if order else 0
    api_symbol = CRYPTO_API_SYMBOLS.get(coin_key, coin_key.upper())
    coin_amount = _get_coin_amount(amount_usdt, api_symbol) if amount_usdt else None
    usdt_line = f"\n💰 مبلغ: <b>{amount_usdt:.2f} USDT</b>" if amount_usdt else ""
    coin_line = f"\n💱 معادل: <b>{_fmt_coin(coin_amount)} {api_symbol}</b>" if coin_amount else ""
    text = (
        f"💎 <b>پرداخت با {label}</b>{usdt_line}{coin_line}\n\n"
        f"📬 آدرس کیف پول:\n<code>{esc(addr)}</code>\n\n"
        f"🆔 سفارش #{order_id}\n\n"
        f"✅ پس از پرداخت، <b>هش تراکنش (TxID) یا رسید پرداخت</b> را همین‌جا در ربات ارسال کنید."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="main_menu"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    # Store state to await receipt from user
    order = get_subscription_order(order_id) or {}
    USER_STATE[uid] = {
        "step": "sub_receipt_wait",
        "order_id": int(order_id),
        "plan_id": order.get("plan", ""),
    }
    bot.answer_callback_query(call.id)


# 
#  ADMIN: PRICES 
# 

def _show_admin_prices(uid, msg_id):
    cf = float(setting_get("price_cf_hosted",  "10"))
    sp = float(setting_get("price_sm_premium", "25"))
    rate = _get_usdt_to_toman()
    def _t(n): return f" — {_fmt_toman(int(n * rate))} تومان" if rate else ""
    text = (
        "💰 <b>قیمت‌گذاری پلن‌ها</b>\n\n"
        f"⚡ ConfigFlow (سرور ما): <b>{cf:.0f} USDT</b>{_t(cf)}\n"
        f"💎 Seamless پرمیوم: <b>{sp:.0f} USDT</b>{_t(sp)}\n"
    )
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("⚡ ConfigFlow", callback_data="adm:price_set:price_cf_hosted"),
        types.InlineKeyboardButton("💎 Seamless پرمیوم", callback_data="adm:price_set:price_sm_premium"),
    )
    kb.add(types.InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_panel"))
    try:
        bot.edit_message_text(text, uid, msg_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data == "adm:prices")
def cb_adm_prices(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    _show_admin_prices(uid, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:price_set:"))
def cb_adm_price_set(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    key = ":".join(call.data.split(":")[2:])
    USER_STATE[uid] = {"step": "adm_set_price", "price_key": key, "msg_id": call.message.message_id}
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(" انصراف", callback_data="adm:prices"))
    try:
        bot.edit_message_text(
            f" <b>تنظیم قیمت: <code>{esc(key)}</code></b>\n\nقیمت جدید را به USDT وارد کنید (مثلاً <code>10</code>):",
            uid, call.message.message_id, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(uid, "قیمت جدید را به USDT وارد کنید:", reply_markup=kb)
    bot.answer_callback_query(call.id)


# 
#  ADMIN: DISCOUNT CODES 
# 

def _show_discount_codes(uid, msg_id):
    codes = get_all_discount_codes()
    text = f" <b>کدهای تخفیف ({len(codes)})</b>"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(" اضافه کردن", callback_data="adm:disc_add"))
    PKG_LABELS = {"all": "همه", "seamless": "Seamless", "configflow": "ConfigFlow"}
    for c in codes:
        pkg_label = PKG_LABELS.get(c["package"], c["package"])
        kb.row(
            types.InlineKeyboardButton(f" {c['code']}", callback_data=f"adm:disc_info:{c['id']}"),
            types.InlineKeyboardButton(f"{c['percent']:.0f}  {pkg_label}", callback_data=f"adm:disc_info:{c['id']}"),
            types.InlineKeyboardButton(" حذف", callback_data=f"adm:disc_del:{c['id']}"),
        )
    kb.add(types.InlineKeyboardButton(" پنل مدیریت", callback_data="admin_panel"))
    try:
        bot.edit_message_text(text, uid, msg_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data == "adm:discounts")
def cb_adm_discounts(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    _show_discount_codes(uid, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "adm:disc_add")
def cb_adm_disc_add(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    USER_STATE[uid] = {"step": "adm_disc_code", "msg_id": call.message.message_id}
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(" انصراف", callback_data="adm:discounts"))
    try:
        bot.edit_message_text(
            " <b>افزودن کد تخفیف</b>\n\nمرحله : متن کد تخفیف را وارد کنید:\n(مثلاً: <code>SUMMER20</code>)",
            uid, call.message.message_id, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(uid, " متن کد تخفیف را وارد کنید:", reply_markup=kb)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:disc_del:"))
def cb_adm_disc_del(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    code_id = int(call.data.split(":")[2])
    delete_discount_code(code_id)
    bot.answer_callback_query(call.id, " کد تخفیف حذف شد.")
    _show_discount_codes(uid, call.message.message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:disc_pkg:"))
def cb_adm_disc_pkg(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        return
    pkg = call.data.split(":")[2]
    state = USER_STATE.get(uid, {})
    code = state.get("disc_code", "")
    percent = state.get("disc_percent", 0)
    if not code:
        bot.answer_callback_query(call.id, " اطلاعات ناقص. دوباره شروع کنید.", show_alert=True)
        return
    create_discount_code(code, percent, pkg)
    USER_STATE.pop(uid, None)
    bot.answer_callback_query(call.id, " کد تخفیف اضافه شد!")
    _show_discount_codes(uid, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "buy_confirm_disc")
def cb_buy_confirm_disc(call):
    uid = call.from_user.id
    state = USER_STATE.get(uid, {})
    if not state.get("buy_plan"):
        bot.answer_callback_query(call.id, " اطلاعات سفارش پیدا نشد.", show_alert=True)
        return
    _show_buy_gateways(call, uid)
    bot.answer_callback_query(call.id)


# ── Subscription Receipt: Admin Approve / Reject ─────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data.startswith("sub_approve:"))
def cb_sub_approve(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید.", show_alert=True)
        return
    parts = call.data.split(":")
    order_id = int(parts[1])
    buyer_uid = int(parts[2])

    order = get_subscription_order(order_id)
    if not order:
        bot.answer_callback_query(call.id, "❌ سفارش پیدا نشد.", show_alert=True)
        return

    confirm_subscription_order(order_id)

    # Set state for buyer to start bot-info collection
    USER_STATE[buyer_uid] = {
        "step": "sub_bot_token",
        "order_id": order_id,
        "plan_id": order.get("plan", ""),
    }

    try:
        bot.send_message(
            buyer_uid,
            "✅ <b>رسید شما تایید شد!</b>\n\n"
            "لطفاً برای نصب ربات، اطلاعات زیر را وارد کنید:\n\n"
            "<b>مرحله ۱:</b> توکن ربات خود را از @BotFather بفرستید\n"
            "<code>مثال: 123456789:ABCdefGHI...</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id, "✅ رسید تایید شد، کاربر مطلع شد.")
    try:
        bot.edit_message_reply_markup(call.from_user.id, call.message.message_id,
                                      reply_markup=types.InlineKeyboardMarkup())
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("sub_reject:"))
def cb_sub_reject(call):
    uid = call.from_user.id
    if uid not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید.", show_alert=True)
        return
    parts = call.data.split(":")
    order_id = int(parts[1])
    buyer_uid = int(parts[2])

    reject_subscription_order(order_id)
    USER_STATE.pop(buyer_uid, None)

    try:
        bot.send_message(
            buyer_uid,
            "❌ <b>رسید شما تایید نشد.</b>\n\n"
            f"لطفاً با پشتیبانی تماس بگیرید: {SUPPORT_USERNAME}",
            parse_mode="HTML",
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id, "❌ رسید رد شد.")
    try:
        bot.edit_message_reply_markup(call.from_user.id, call.message.message_id,
                                      reply_markup=types.InlineKeyboardMarkup())
    except Exception:
        pass
