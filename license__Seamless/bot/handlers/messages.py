# -*- coding: utf-8 -*-
"""
Message handlers for the License Bot.
Handles text input flows: bot registration, admin manual license, admin extend, broadcast.
After registration, automatically deploys the bot instance on the server.
"""
import re
import time
import threading
from telebot import types

from ..bot_instance import bot, USER_STATE
from ..config import (
    ADMIN_IDS, TRIAL_HOURS,
    SUPPORT_USERNAME,
)
from ..db import (
    ensure_user, create_license, extend_license, get_license,
    get_all_users, get_user_licenses, update_license_fields,
    create_instance, update_instance_status, get_instance_by_token,
    mark_trial_used,
    get_discount_code_by_code,
    setting_get, setting_set,
    get_subscription_order, get_user,
)
from ..deployer import (
    deploy_instance, instance_dir, service_name, _bot_id_from_token,
    update_repo_cache, instance_status as deployer_status,
    restore_instance_db,
)
from .start import main_keyboard, esc


def _cancel_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="main_menu"))
    return kb


def _get_license_api_url():
    """Build the license API URL for this server."""
    import os
    port = os.getenv("LICENSE_API_PORT", "8585")
    return f"http://127.0.0.1:{port}"


_EMOJI_RE = re.compile(
    r"(?:"
    r"[\U0001F1E6-\U0001F1FF]{2}"
    r"|"
    r"[#*0-9]\uFE0F?\u20E3"
    r"|"
    r"[\u00A9\u00AE\u203C-\u3299\U0001F300-\U0001FAFF]"
    r"(?:[\uFE0F\u200D][\u00A9\u00AE\u203C-\u3299\U0001F300-\U0001FAFF])*"
    r")",
    re.UNICODE,
)


def _extract_emoji_rows(message):
    raw_text = (message.text or message.caption or "").strip()
    entities = list(message.entities or [])
    if getattr(message, "caption_entities", None):
        entities.extend(message.caption_entities or [])

    rows = []
    seen = set()
    custom_ranges = []

    for ent in entities:
        if getattr(ent, "type", "") != "custom_emoji":
            continue
        custom_id = getattr(ent, "custom_emoji_id", None) or getattr(ent, "document_id", None)
        if not custom_id:
            continue
        start = int(getattr(ent, "offset", 0) or 0)
        end = start + int(getattr(ent, "length", 0) or 0)
        emoji_text = raw_text[start:end].strip() if raw_text else ""
        custom_ranges.append((start, end, emoji_text, str(custom_id)))

    for match in _EMOJI_RE.finditer(raw_text):
        emoji_text = match.group(0).strip()
        if not emoji_text:
            continue
        start, end = match.span()
        custom_id = ""
        for cstart, cend, centity_text, cid in custom_ranges:
            if start < cend and end > cstart:
                custom_id = cid
                if centity_text:
                    emoji_text = centity_text
                break
        key = (emoji_text, custom_id)
        if key not in seen:
            seen.add(key)
            rows.append({"emoji": emoji_text, "custom_id": custom_id})

    for _, _, emoji_text, cid in custom_ranges:
        emoji_text = (emoji_text or "▫️").strip()
        key = (emoji_text, cid)
        if key not in seen:
            seen.add(key)
            rows.append({"emoji": emoji_text, "custom_id": cid})

    return rows


def _deploy_background(args):
    """Background thread: deploys a bot instance and notifies user/admin."""
    uid = args["uid"]
    project = args["project"]
    bot_token = args["bot_token"]
    admin_id = args["admin_id"]
    bot_username = args["bot_username"]
    inst_id = args["inst_id"]
    lic_id = args["lic_id"]
    label = args["label"]

    license_api_url = _get_license_api_url() if project == "seamless" else ""

    ok, msg = deploy_instance(
        project=project,
        bot_token=bot_token,
        admin_id=admin_id,
        license_api_url=license_api_url,
        bot_username=bot_username,
    )

    if ok:
        update_instance_status(inst_id, "running")
        try:
            bot.send_message(uid,
                f"✅ <b>ربات @{bot_username} با موفقیت نصب و اجرا شد!</b>\n\n"
                f"🆔 لایسنس: #{lic_id}\n"
                f"📌 پروژه: {label}\n"
                f"🟢 وضعیت: فعال\n\n"
                "ربات شما الان آنلاین است. لطفاً تست کنید.\n\n"
                "♻️ آپدیت خودکار هم فعال است و هر ۱ دقیقه نسخه جدید گیت‌هاب بررسی می‌شود."
            )
        except Exception:
            pass
        for adm in ADMIN_IDS:
            try:
                bot.send_message(adm,
                    f"✅ دیپلوی موفق: @{bot_username}\n"
                    f"📌 {label} | لایسنس #{lic_id} | کاربر <code>{uid}</code>"
                )
            except Exception:
                pass
    else:
        update_instance_status(inst_id, "failed")
        try:
            bot.send_message(uid,
                f"❌ <b>خطا در نصب ربات @{bot_username}</b>\n\n"
                f"لطفاً با پشتیبانی تماس بگیرید: {SUPPORT_USERNAME}\n"
                f"کد خطا: {msg[:200]}"
            )
        except Exception:
            pass
        for adm in ADMIN_IDS:
            try:
                bot.send_message(adm,
                    f"❌ دیپلوی ناموفق: @{bot_username}\n"
                    f"👤 <code>{uid}</code>\n"
                    f"خطا: {msg[:300]}"
                )
            except Exception:
                pass


# ── Subscription Receipt Helpers ──────────────────────────────────────────────

def _receipt_approve_kb(order_id, buyer_uid):
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ تایید رسید", callback_data=f"sub_approve:{order_id}:{buyer_uid}"),
        types.InlineKeyboardButton("❌ رد کردن",   callback_data=f"sub_reject:{order_id}:{buyer_uid}"),
    )
    return kb


def _notify_admins_receipt(uid, order_id, order, caption_extra=""):
    u = get_user(uid)
    uname = f"@{u['username']}" if u and u.get("username") else str(uid)
    plan = order.get("plan", "—") if order else "—"
    amount = f"{order['final_usdt']:.2f} USDT" if order else "—"
    text = (
        f"📩 <b>رسید پرداخت دریافت شد</b>\n"
        f"👤 کاربر: {esc(uname)} — <code>{uid}</code>\n"
        f"📦 پلن: {esc(plan)}\n"
        f"💰 مبلغ: {amount}\n"
        f"🆔 سفارش: #{order_id}"
        + (f"\n{caption_extra}" if caption_extra else "")
    )
    return text


def _handle_sub_receipt_text(uid, state, receipt_text):
    """Handle a text receipt/hash sent by user in sub_receipt_wait state."""
    from ..config import ADMIN_IDS as _ADMIN_IDS
    order_id = state.get("order_id")
    order = get_subscription_order(order_id) if order_id else None
    caption = _notify_admins_receipt(uid, order_id, order, f"\n🔗 هش/رسید:\n<code>{esc(receipt_text)}</code>")
    kb = _receipt_approve_kb(order_id, uid)
    for adm in _ADMIN_IDS:
        try:
            bot.send_message(adm, caption, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    USER_STATE.pop(uid, None)
    bot.send_message(
        uid,
        "📩 <b>رسید شما دریافت شد.</b>\n\n"
        "ادمین در حال بررسی است. پس از تایید پیام دریافت خواهید کرد.",
        parse_mode="HTML",
    )


# ── Main text handler ────────────────────────────────────────────────────────
@bot.message_handler(content_types=["text"])
def handle_text(message):
    uid = message.from_user.id
    text = message.text.strip()
    state = USER_STATE.get(uid)
    if not state:
        return

    step = state.get("step")

    if step == "adm_extract_emoji_id" and uid in ADMIN_IDS:
        emoji_rows = _extract_emoji_rows(message)

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_panel"))

        if not emoji_rows:
            bot.send_message(
                uid,
                "❌ داخل این پیام هیچ ایموجی‌ای پیدا نشد.\n\n"
                "یک یا چند ایموجی معمولی / Premium / Custom بفرست تا کنار هرکدام، ID مرتبط هم نمایش داده شود.",
                reply_markup=kb,
            )
            return

        ids_text = "\n".join(
            f"{esc(row['emoji'])} → <code>{row['custom_id'] or '—'}</code>"
            for row in emoji_rows
        )
        bot.send_message(
            uid,
            "🆔 <b>ایموجی → ID پریمیوم</b>\n\n"
            f"{ids_text}\n\n"
            "ℹ️ خط تیره یعنی آن مورد در این پیام نسخه Premium/Custom نداشت.\n"
            "اگر خواستی ایموجی بعدی را هم بفرست.",
            reply_markup=kb,
            parse_mode="HTML",
        )
        return

    # ── Bot Registration Flow (Seamless / ConfigFlow) ────────────────────────
    if step in ("cf_token", "sm_token"):
        if not text or ":" not in text:
            bot.send_message(uid, "❌ توکن ربات نامعتبر است. فرمت درست:\n<code>123456789:ABCdefGHI...</code>", reply_markup=_cancel_kb())
            return
        state["bot_token"] = text
        state["step"] = "reg_admin_id"
        bot.send_message(uid, "<b>مرحله ۲:</b> آیدی عددی ادمین ربات را بفرستید:", reply_markup=_cancel_kb())
        return

    if step == "reg_admin_id":
        if not text.isdigit():
            bot.send_message(uid, "❌ آیدی عددی باید عدد باشد.", reply_markup=_cancel_kb())
            return
        state["admin_id"] = text
        state["step"] = "reg_bot_username"
        bot.send_message(uid, "<b>مرحله ۳:</b> یوزرنیم ربات را بفرستید (مثلاً @MyBot):", reply_markup=_cancel_kb())
        return

    if step == "reg_bot_username":
        username = text.lstrip("@")
        if not username:
            bot.send_message(uid, "❌ یوزرنیم نامعتبر.", reply_markup=_cancel_kb())
            return
        state["bot_username"] = username
        state["step"] = "reg_support_user"
        bot.send_message(uid, "<b>مرحله ۴:</b> یوزرنیم پشتیبانی را بفرستید:", reply_markup=_cancel_kb())
        return

    if step == "reg_support_user":
        support = text.lstrip("@")
        if not support:
            bot.send_message(uid, "❌ یوزرنیم نامعتبر.", reply_markup=_cancel_kb())
            return
        state["support_user"] = support

        reg_type = state.get("type", "configflow")
        plan = "trial" if reg_type == "seamless" else "configflow_trial"
        hours = TRIAL_HOURS

        lic_id = create_license(
            user_id=uid,
            bot_token=state["bot_token"],
            bot_username=state["bot_username"],
            admin_id=state["admin_id"],
            support_user=support,
            plan=plan,
            duration_hours=hours
        )

        # Mark trial as used so user can never request this type again
        project_type = "seamless" if reg_type == "seamless" else "configflow"
        mark_trial_used(uid, project_type)

        label = "Seamless" if reg_type == "seamless" else "ConfigFlow"
        project = "seamless" if reg_type == "seamless" else "configflow"

        # Record instance in DB
        bot_token = state["bot_token"]
        bot_id = _bot_id_from_token(bot_token)
        idir = instance_dir(project, bot_token)
        svc = service_name(project, bot_token)
        inst_id = create_instance(
            license_id=lic_id,
            user_id=uid,
            project=project,
            bot_token=bot_token,
            bot_id=bot_id,
            bot_username=state["bot_username"],
            admin_id=state["admin_id"],
            instance_dir=idir,
            service_name=svc,
        )

        text_msg = f"""
✅ <b>لایسنس {label} ساخته شد!</b>

🆔 شماره لایسنس: <b>#{lic_id}</b>
📌 پلن: 🆓 تریال ({hours} ساعت)
🤖 ربات: @{esc(state['bot_username'])}
👤 ادمین: <code>{esc(state['admin_id'])}</code>
📞 پشتیبانی: @{esc(support)}

⏳ اعتبار: {hours} ساعت

⏬ <b>در حال نصب و راه‌اندازی ربات شما روی سرور...</b>
لطفاً چند دقیقه صبر کنید. پس از اتمام نصب پیام دریافت خواهید کرد.
"""
        USER_STATE.pop(uid, None)
        bot.send_message(uid, text_msg, reply_markup=main_keyboard(uid))

        for admin in ADMIN_IDS:
            try:
                bot.send_message(admin,
                    f"🆕 لایسنس جدید #{lic_id}\n"
                    f"👤 کاربر: <code>{uid}</code>\n"
                    f"🤖 @{esc(state['bot_username'])}\n"
                    f"📌 {label} — تریال {hours}h\n"
                    f"⏬ در حال دیپلوی..."
                )
            except Exception:
                pass

        # Deploy in background thread
        _deploy_args = {
            "uid": uid,
            "project": project,
            "bot_token": bot_token,
            "admin_id": state["admin_id"],
            "bot_username": state["bot_username"],
            "inst_id": inst_id,
            "lic_id": lic_id,
            "label": label,
        }
        t = threading.Thread(target=_deploy_background, args=(_deploy_args,), daemon=True)
        t.start()
        return

    # ── Admin: Manual License ────────────────────────────────────────────────
    if step == "adm_manual_uid" and uid in ADMIN_IDS:
        if not text.isdigit():
            bot.send_message(uid, "❌ آیدی عددی باید عدد باشد.", reply_markup=_cancel_kb())
            return
        state["target_uid"] = int(text)
        state["step"] = "adm_manual_plan"
        bot.send_message(uid,
            f"👤 کاربر: <code>{text}</code>\n\n"
            "پلن را بنویسید:\n"
            "<code>configflow_monthly</code> یا <code>premium</code> یا <code>trial</code> یا <code>configflow_trial</code>",
            reply_markup=_cancel_kb()
        )
        return

    if step == "adm_manual_plan" and uid in ADMIN_IDS:
        valid = ("configflow_monthly", "premium", "trial", "configflow_trial")
        if text not in valid:
            bot.send_message(uid, f"❌ پلن نامعتبر. یکی از اینها: {', '.join(valid)}", reply_markup=_cancel_kb())
            return
        state["plan"] = text
        state["step"] = "adm_manual_token"
        bot.send_message(uid, "توکن ربات مقصد را بفرستید:", reply_markup=_cancel_kb())
        return

    if step == "adm_manual_token" and uid in ADMIN_IDS:
        if ":" not in text:
            bot.send_message(uid, "❌ توکن نامعتبر.", reply_markup=_cancel_kb())
            return
        state["bot_token"] = text
        state["step"] = "adm_manual_username"
        bot.send_message(uid, "یوزرنیم ربات:", reply_markup=_cancel_kb())
        return

    if step == "adm_manual_username" and uid in ADMIN_IDS:
        username = text.lstrip("@")
        state["bot_username"] = username
        state["step"] = "adm_manual_hours"
        bot.send_message(uid, "مدت اعتبار (ساعت) — مثلاً <code>720</code> برای 30 روز:", reply_markup=_cancel_kb())
        return

    if step == "adm_manual_hours" and uid in ADMIN_IDS:
        if not text.isdigit():
            bot.send_message(uid, "❌ عدد وارد کنید.", reply_markup=_cancel_kb())
            return
        hours = int(text)
        target_uid = state["target_uid"]
        ensure_user(target_uid, "")
        plan = state["plan"]
        project = "seamless" if plan in ("trial", "premium") else "configflow"
        lic_id = create_license(
            user_id=target_uid,
            bot_token=state["bot_token"],
            bot_username=state["bot_username"],
            admin_id=str(target_uid),
            support_user="",
            plan=plan,
            duration_hours=hours
        )

        # Record + deploy instance
        bot_token = state["bot_token"]
        bot_id = _bot_id_from_token(bot_token)
        idir = instance_dir(project, bot_token)
        svc = service_name(project, bot_token)
        inst_id = create_instance(
            license_id=lic_id,
            user_id=target_uid,
            project=project,
            bot_token=bot_token,
            bot_id=bot_id,
            bot_username=state["bot_username"],
            admin_id=str(target_uid),
            instance_dir=idir,
            service_name=svc,
        )

        USER_STATE.pop(uid, None)
        bot.send_message(uid,
            f"✅ لایسنس دستی #{lic_id} برای کاربر <code>{target_uid}</code> صادر شد.\n"
            f"📌 {plan} | {hours} ساعت | @{esc(state['bot_username'])}\n"
            f"⏬ در حال نصب ربات روی سرور...",
            reply_markup=main_keyboard(uid)
        )

        label = "Seamless" if project == "seamless" else "ConfigFlow"
        _deploy_args = {
            "uid": target_uid,
            "project": project,
            "bot_token": bot_token,
            "admin_id": str(target_uid),
            "bot_username": state["bot_username"],
            "inst_id": inst_id,
            "lic_id": lic_id,
            "label": label,
        }
        t = threading.Thread(target=_deploy_background, args=(_deploy_args,), daemon=True)
        t.start()

        try:
            bot.send_message(target_uid,
                f"🎉 لایسنس جدید #{lic_id} توسط ادمین برای شما فعال شد!\n"
                f"🤖 @{esc(state['bot_username'])}\n"
                f"⏳ اعتبار: {hours} ساعت\n"
                f"⏬ در حال نصب ربات..."
            )
        except Exception:
            pass
        return

    # ── Admin: Extend License Hours ──────────────────────────────────────────
    if step == "adm_extend_hours" and uid in ADMIN_IDS:
        if not text.isdigit():
            bot.send_message(uid, "❌ عدد وارد کنید.", reply_markup=_cancel_kb())
            return
        hours = int(text)
        lic_id = state.get("lic_id")
        extend_license(lic_id, hours)
        USER_STATE.pop(uid, None)
        bot.send_message(uid,
            f"✅ لایسنس #{lic_id} به مدت {hours} ساعت تمدید شد.",
            reply_markup=main_keyboard(uid)
        )
        return

    # ── Admin: Broadcast ─────────────────────────────────────────────────────
    if step == "adm_broadcast" and uid in ADMIN_IDS:
        broadcast_text = text
        users = get_all_users()
        sent = 0
        failed = 0
        for u in users:
            try:
                bot.send_message(u["user_id"], broadcast_text)
                sent += 1
            except Exception:
                failed += 1
        USER_STATE.pop(uid, None)
        bot.send_message(uid,
            f"📣 پیام ارسال شد.\n✅ موفق: {sent}\n❌ خطا: {failed}",
            reply_markup=main_keyboard(uid)
        )
        return

    # ── Admin: License Search ────────────────────────────────────────────────
    if step == "adm_lic_search" and uid in ADMIN_IDS:
        from .callbacks import _send_lic_list
        USER_STATE[uid]["lic_search"] = text
        msg_id = state.get("msg_id")
        page = state.get("lic_page", 0)
        USER_STATE[uid] = {"lic_search": text}
        _send_lic_list(uid, msg_id, page=page, search_query=text)
        return
    # ── Donate: Amount input ──────────────────────────────────────────────────
    if step == "donate_amount":
        try:
            amount = float(text.replace(",", "").strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="main_menu"))
            bot.send_message(uid, "❌ مبلغ نامعتبر است. یک عدد مثبت وارد کنید (مثلاً <code>5</code>):",
                             reply_markup=kb, parse_mode="HTML")
            return
        msg_id = state.get("msg_id")
        USER_STATE.pop(uid, None)
        from .callbacks import _show_donate_gateways

        class _FakeCall:
            def __init__(self, message_id, chat_id):
                class _Msg:
                    pass
                msg = _Msg()
                msg.message_id = message_id
                self.message = msg
                self.from_user = type("U", (), {"id": chat_id})()

        fake = _FakeCall(msg_id, uid)
        _show_donate_gateways(fake, uid, amount)
        return
    # ── Admin: Message user ──────────────────────────────────────────────────
    if step == "adm_msg_user" and uid in ADMIN_IDS:
        target_uid = state.get("target_uid")
        page = state.get("page", 0)
        try:
            bot.send_message(target_uid, text)
            bot.send_message(uid, f"✅ پیام به کاربر <code>{target_uid}</code> ارسال شد.")
        except Exception as e:
            bot.send_message(uid, f"❌ خطا در ارسال پیام: {e}")
        USER_STATE.pop(uid, None)
        from .callbacks import _send_user_list
        msg_id = state.get("msg_id")
        _send_user_list(uid, msg_id, page=page, selected_uid=target_uid)
        return

    # ── Admin: Gateway setting value ──────────────────────────────────────────
    if step == "adm_gw_set" and uid in ADMIN_IDS:
        gw = state.get("gw")
        setting_key = state.get("setting_key")
        msg_id = state.get("msg_id")
        from ..db import setting_set as ss
        ss(setting_key, text.strip())
        USER_STATE.pop(uid, None)
        from .callbacks import _gw_show_sub
        bot.send_message(uid, f"✅ تنظیم <code>{setting_key}</code> ذخیره شد.", parse_mode="HTML")
        _gw_show_sub(uid, msg_id, gw)

    #  Buy: Discount code input 
    if step == "buy_discount_code":
        from .callbacks import _show_buy_gateways, _PLAN_INFO
        code = text.strip().upper()
        disc = get_discount_code_by_code(code)
        plan_id = state.get("buy_plan", "")
        pkg = state.get("buy_pkg", "")
        if not disc:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(" بدون کد تخفیف ادامه بده", callback_data="buy_disc:no"))
            bot.send_message(uid, " کد تخفیف نامعتبر است. دوباره وارد کنید یا بدون تخفیف ادامه دهید:", reply_markup=kb)
            return
        # Check if code applies to this package
        if disc["package"] != "all" and disc["package"] != pkg:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(" بدون کد تخفیف ادامه بده", callback_data="buy_disc:no"))
            bot.send_message(uid, f" این کد تخفیف برای پلن انتخابی شما معتبر نیست.", reply_markup=kb)
            return
        # Apply discount
        orig_usdt = state.get("buy_usdt", 0)
        orig_toman = state.get("buy_toman", 0)
        pct = disc["percent"]
        final_usdt = orig_usdt * (1 - pct / 100)
        rate = state.get("buy_rate", 0)
        final_toman = int(final_usdt * rate) if rate else int(orig_toman * (1 - pct / 100))
        state["buy_disc_code"] = code
        state["buy_disc_pct"] = pct
        state["buy_final_usdt"] = final_usdt
        state["buy_final_toman"] = final_toman
        state.pop("step", None)
        USER_STATE[uid] = state

        label = _PLAN_INFO.get(plan_id, (plan_id,))[0]
        toman_line = f"  <b>{int(final_toman):,} تومان</b>" if final_toman else ""
        kb2 = types.InlineKeyboardMarkup()
        kb2.add(types.InlineKeyboardButton(" تایید و انتخاب درگاه", callback_data="buy_confirm_disc"))
        kb2.add(types.InlineKeyboardButton(" انصراف", callback_data="main_menu"))
        msg_id = state.get("msg_id")
        try:
            bot.edit_message_text(
                f" <b>کد تخفیف اعمال شد!</b>\n\n"
                f" پلن: {label}\n"
                f" تخفیف: <b>{pct:.0f}</b>\n"
                f" قیمت اصلی: {orig_usdt:.2f} USDT\n"
                f" قیمت نهایی: <b>{final_usdt:.2f} USDT</b>{toman_line}",
                uid, msg_id, reply_markup=kb2, parse_mode="HTML"
            )
        except Exception:
            bot.send_message(uid,
                f" کد تخفیف {pct:.0f} اعمال شد. قیمت نهایی: {final_usdt:.2f} USDT", reply_markup=kb2)
        return

    #  Admin: Set price 
    if step == "adm_set_price" and uid in ADMIN_IDS:
        price_key = state.get("price_key")
        msg_id = state.get("msg_id")
        try:
            val = float(text.replace(",", "").strip())
            if val <= 0:
                raise ValueError
        except ValueError:
            bot.send_message(uid, " مقدار نامعتبر. یک عدد مثبت وارد کنید:")
            return
        setting_set(price_key, str(val))
        USER_STATE.pop(uid, None)
        from .callbacks import _show_admin_prices
        bot.send_message(uid, f" قیمت <code>{esc(price_key)}</code> به <b>{val} USDT</b> تغییر یافت.", parse_mode="HTML")
        _show_admin_prices(uid, msg_id)
        return

    #  Admin: Discount code  enter code text 
    if step == "adm_disc_code" and uid in ADMIN_IDS:
        msg_id = state.get("msg_id")
        code_text = text.strip().upper()
        if not code_text:
            bot.send_message(uid, " کد نمی‌تواند خالی باشد.")
            return
        USER_STATE[uid] = {"step": "adm_disc_percent", "disc_code": code_text, "msg_id": msg_id}
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(" انصراف", callback_data="adm:discounts"))
        bot.send_message(uid,
            f" کد: <code>{esc(code_text)}</code>\n\n"
            "مرحله : درصد تخفیف را وارد کنید (مثلاً <code>20</code> یعنی ):",
            reply_markup=kb, parse_mode="HTML")
        return

    # ── User / Admin: Bot Info Edit Field ─────────────────────────────────────
    if step == "bm_edit_field":
        field   = state.get("field")
        lic_id  = state.get("lic_id")
        page    = state.get("page", 0)
        lic = get_license(lic_id)
        is_admin = uid in ADMIN_IDS
        if not lic or (lic["user_id"] != uid and not is_admin):
            USER_STATE.pop(uid, None)
            bot.send_message(uid, "❌ دسترسی ندارید.")
            return
        value = text.strip().lstrip("@")
        if field == "token":
            if ":" not in value:
                bot.send_message(uid, "❌ توکن نامعتبر است. فرمت: <code>123456:ABC...</code>", reply_markup=_cancel_kb(), parse_mode="HTML")
                return
            update_license_fields(lic_id, bot_token=value)
        elif field == "admin_id":
            if not value.lstrip("-").isdigit():
                bot.send_message(uid, "❌ آیدی عددی وارد کنید.", reply_markup=_cancel_kb())
                return
            update_license_fields(lic_id, admin_id=value)
        elif field == "username":
            update_license_fields(lic_id, bot_username=value.lstrip("@"))
        elif field == "support":
            update_license_fields(lic_id, support_user=value.lstrip("@"))
        USER_STATE.pop(uid, None)
        from telebot import types as _types
        kb = _types.InlineKeyboardMarkup()
        kb.add(_types.InlineKeyboardButton("⚙️ برگشت به مدیریت", callback_data=f"bot_manage:{lic_id}:{page}"))
        bot.send_message(uid, "✅ اطلاعات با موفقیت ذخیره شد.", reply_markup=kb)
        return

    #  Admin: Discount code  enter percent 
    if step == "adm_disc_percent" and uid in ADMIN_IDS:
        try:
            pct = float(text.replace(",", "").strip())
            if not (0 < pct <= 100):
                raise ValueError
        except ValueError:
            bot.send_message(uid, " درصد نامعتبر. عددی بین  تا  وارد کنید:")
            return
        state["disc_percent"] = pct
        state["step"] = "adm_disc_package_wait"
        USER_STATE[uid] = state
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("همه پلن‌ها",  callback_data="adm:disc_pkg:all"),
            types.InlineKeyboardButton("Seamless",     callback_data="adm:disc_pkg:seamless"),
        )
        kb.add(types.InlineKeyboardButton("ConfigFlow", callback_data="adm:disc_pkg:configflow"))
        kb.add(types.InlineKeyboardButton(" انصراف", callback_data="adm:discounts"))
        bot.send_message(uid,
            f" تخفیف: <b>{pct:.0f}</b>\n\n"
            "مرحله : این کد تخفیف برای کدام بسته است؟",
            reply_markup=kb, parse_mode="HTML")
        return

    # ── Subscription: Bot Info Collection (after receipt approved) ────────────
    if step == "sub_receipt_wait":
        _handle_sub_receipt_text(uid, state, text)
        return

    # ── Subscription: Bot Info Collection (after receipt approved) ────────────
    if step == "sub_bot_token":
        if not text or ":" not in text:
            bot.send_message(uid, "❌ توکن ربات نامعتبر است.\nفرمت درست: <code>123456789:ABCdefGHI...</code>",
                             reply_markup=_cancel_kb(), parse_mode="HTML")
            return
        state["bot_token"] = text.strip()
        state["step"] = "sub_admin_id"
        USER_STATE[uid] = state
        bot.send_message(uid,
            "<b>مرحله ۲:</b> آیدی عددی پشتیبانی را بفرستید:",
            reply_markup=_cancel_kb(), parse_mode="HTML")
        return

    if step == "sub_admin_id":
        if not text.strip().lstrip("-").isdigit():
            bot.send_message(uid, "❌ آیدی باید عدد باشد.", reply_markup=_cancel_kb())
            return
        state["admin_id"] = text.strip()
        state["step"] = "sub_bot_username"
        USER_STATE[uid] = state
        bot.send_message(uid,
            "<b>مرحله ۳:</b> یوزرنیم ربات را بفرستید (مثلاً @MyBot):",
            reply_markup=_cancel_kb(), parse_mode="HTML")
        return

    if step == "sub_bot_username":
        username = text.strip().lstrip("@")
        if not username:
            bot.send_message(uid, "❌ یوزرنیم نامعتبر.", reply_markup=_cancel_kb())
            return
        state["bot_username"] = username
        state["step"] = "sub_support_user"
        USER_STATE[uid] = state
        bot.send_message(uid,
            "<b>مرحله ۴:</b> یوزرنیم پشتیبانی ربات را بفرستید (مثلاً @support):",
            reply_markup=_cancel_kb(), parse_mode="HTML")
        return

    if step == "sub_support_user":
        support = text.strip().lstrip("@")
        if not support:
            bot.send_message(uid, "❌ یوزرنیم نامعتبر.", reply_markup=_cancel_kb())
            return
        state["support_user"] = support

        plan_id = state.get("plan_id", "")
        project = "seamless" if "sm" in plan_id else "configflow"
        plan = "premium" if project == "seamless" else "configflow_monthly"

        bot_token = state["bot_token"]
        lic_id = create_license(
            user_id=uid,
            bot_token=bot_token,
            bot_username=state["bot_username"],
            admin_id=state["admin_id"],
            support_user=support,
            plan=plan,
            duration_hours=720,  # 30 days
        )

        bot_id = _bot_id_from_token(bot_token)
        idir = instance_dir(project, bot_token)
        svc = service_name(project, bot_token)
        inst_id = create_instance(
            license_id=lic_id,
            user_id=uid,
            project=project,
            bot_token=bot_token,
            bot_id=bot_id,
            bot_username=state["bot_username"],
            admin_id=state["admin_id"],
            instance_dir=idir,
            service_name=svc,
        )

        label = "Seamless" if project == "seamless" else "ConfigFlow"
        USER_STATE.pop(uid, None)
        bot.send_message(
            uid,
            f"✅ <b>اشتراک {label} شما فعال شد!</b>\n\n"
            f"🆔 لایسنس: <b>#{lic_id}</b>\n"
            f"🤖 ربات: @{esc(state['bot_username'])}\n"
            f"👤 آیدی ادمین: <code>{esc(state['admin_id'])}</code>\n"
            f"📞 پشتیبانی: @{esc(support)}\n"
            f"⏳ اعتبار: ۳۰ روز\n\n"
            "⏬ <b>در حال نصب و راه‌اندازی ربات روی سرور...</b>\n"
            "لطفاً چند دقیقه صبر کنید. پس از اتمام نصب پیام دریافت خواهید کرد.",
            reply_markup=main_keyboard(uid),
            parse_mode="HTML",
        )

        for adm in ADMIN_IDS:
            try:
                bot.send_message(
                    adm,
                    f"🆕 لایسنس جدید #{lic_id}\n"
                    f"👤 کاربر: <code>{uid}</code>\n"
                    f"🤖 @{esc(state['bot_username'])}\n"
                    f"📌 {label} — 30 روز\n"
                    f"⏬ در حال دیپلوی...",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        _deploy_args = {
            "uid": uid,
            "project": project,
            "bot_token": bot_token,
            "admin_id": state["admin_id"],
            "bot_username": state["bot_username"],
            "inst_id": inst_id,
            "lic_id": lic_id,
            "label": label,
        }
        t = threading.Thread(target=_deploy_background, args=(_deploy_args,), daemon=True)
        t.start()
        return


@bot.message_handler(content_types=["document"])
def handle_document(message):
    uid = message.from_user.id
    state = USER_STATE.get(uid) or {}

    if uid not in ADMIN_IDS or state.get("step") != "restore_db":
        return

    file_name = (message.document.file_name or "").strip()
    if not file_name.lower().endswith((".db", ".sqlite", ".sqlite3")):
        bot.send_message(uid, "⚠️ فقط فایل‌های SQLite با پسوند <code>.db</code> یا <code>.sqlite</code> قابل قبول هستند.", parse_mode="HTML")
        return

    lic_id = state.get("lic_id")
    page = state.get("page", 0)
    project = state.get("project")
    bot_token = state.get("bot_token")

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
    except Exception as e:
        bot.send_message(uid, f"❌ خطا در دریافت فایل: {esc(str(e))}", parse_mode="HTML")
        return

    wait_msg = bot.send_message(uid, "⏳ در حال بررسی و ری‌استور دیتابیس... لطفاً صبر کنید.")
    ok, msg = restore_instance_db(project, bot_token, downloaded, file_name)
    USER_STATE.pop(uid, None)

    inst = get_instance_by_token(bot_token)
    if inst and ok:
        update_instance_status(inst["id"], "running")

    kb = types.InlineKeyboardMarkup()
    if lic_id:
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به جزئیات", callback_data=f"adm:lic_detail:{lic_id}:{page}"))
    else:
        kb.add(types.InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_panel"))

    try:
        bot.delete_message(uid, wait_msg.message_id)
    except Exception:
        pass

    bot.send_message(
        uid,
        ("✅ " if ok else "❌ ") + msg,
        reply_markup=kb,
        parse_mode="HTML"
    )


# ── Photo handler (subscription receipt) ─────────────────────────────────────

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    uid = message.from_user.id
    state = USER_STATE.get(uid) or {}
    if state.get("step") != "sub_receipt_wait":
        return

    order_id = state.get("order_id")
    order = get_subscription_order(order_id) if order_id else None
    caption = _notify_admins_receipt(uid, order_id, order)
    kb = _receipt_approve_kb(order_id, uid)

    photo_id = message.photo[-1].file_id
    for adm in ADMIN_IDS:
        try:
            bot.send_photo(adm, photo_id, caption=caption, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass

    USER_STATE.pop(uid, None)
    bot.send_message(
        uid,
        "📩 <b>رسید شما دریافت شد.</b>\n\n"
        "ادمین در حال بررسی است. پس از تایید پیام دریافت خواهید کرد.",
        parse_mode="HTML",
    )
