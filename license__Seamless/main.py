# -*- coding: utf-8 -*-
"""
Seamless License Management Bot — Entry Point
"""
import threading
import time
import logging
import os
import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

from bot.db import (
    init_db, get_expired_licenses, update_license_status,
    get_licenses_expiring_soon, set_warning_sent,
    get_all_instances, get_user, get_all_active_licenses,
    get_instance_by_token, update_instance_status,
    get_expired_not_notified, set_license_expired_notified,
    set_license_pending_delete, get_expired_pending_delete,
    set_license_final_backup_sent, delete_instance, delete_license,
)
from bot.bot_instance import bot as tg_bot
from bot.config import ADMIN_IDS, AUTO_UPDATE_ENABLED, AUTO_UPDATE_INTERVAL
from bot.deployer import stop_instance, repo_has_updates, update_all_instances, get_repo_changed_files, backup_instance_db, remove_instance

# Import handlers (registers them with bot)
import bot.handlers  # noqa: F401

BACKUP_CHANNEL = -1003744578285


def _notify_via_bot_token(bot_token, admin_id, text):
    """Send a message to admin_id using the given bot token (the user's deployed bot)."""
    try:
        import telebot
        _b = telebot.TeleBot(bot_token, parse_mode=None)
        _b.send_message(int(admin_id), text)
    except Exception as e:
        logger.warning(f"notify_via_bot_token failed ({admin_id}): {e}")


def _send_final_backup(lic, inst):
    """Take a final DB backup for the given license/instance and send to BACKUP_CHANNEL."""
    if not inst:
        return
    project = inst.get("project", "")
    token = lic.get("bot_token", "")
    if not project or not token:
        return
    try:
        db_files = backup_instance_db(project, token)
        if not db_files:
            return
        owner = get_user(lic["user_id"])
        owner_name = ""
        if owner:
            fn = owner.get("first_name") or ""
            un = f" (@{owner['username']})" if owner.get("username") else ""
            owner_name = fn + un
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        caption = (
            f"💾 <b>بکاپ نهایی هنگام انقضا — {now_str}</b>\n\n"
            f"🤖 ربات: @{lic.get('bot_username') or '—'}\n"
            f"📌 پروژه: {project}\n"
            f"👤 صاحب: {owner_name} — <code>{lic['user_id']}</code>\n"
            f"🆔 لایسنس: #{lic['id']}"
        )
        for fname, fdata in db_files:
            import io
            tg_bot.send_document(
                BACKUP_CHANNEL,
                io.BytesIO(fdata),
                caption=caption,
                parse_mode="HTML",
                visible_file_name=f"{lic.get('bot_username','bot')}_final_{fname}"
            )
        logger.info(f"Final backup sent for license #{lic['id']}")
    except Exception as e:
        logger.error(f"_send_final_backup error for license #{lic['id']}: {e}")


def expire_checker():
    """Background thread: every 60s marks expired licenses, takes final backup, stops instance, notifies."""
    while True:
        try:
            # Step 1: mark newly expired licenses and start the expiry process
            expired = get_expired_licenses()
            for lic in expired:
                update_license_status(lic["id"], "expired")
                logger.info(f"License #{lic['id']} expired (user {lic['user_id']})")

            # Step 2: process all expired-but-not-yet-notified licenses
            to_process = get_expired_not_notified()
            for lic in to_process:
                inst = get_instance_by_token(lic["bot_token"])

                # 2a. Take a final backup BEFORE stopping
                if not lic.get("final_backup_sent"):
                    _send_final_backup(lic, inst)
                    set_license_final_backup_sent(lic["id"])

                # 2b. Stop the bot instance
                if inst:
                    project = inst.get("project", "")
                    try:
                        ok, _ = stop_instance(project, lic["bot_token"])
                        if ok:
                            update_instance_status(inst["id"], "stopped")
                    except Exception as e:
                        logger.error(f"Stop instance error for license #{lic['id']}: {e}")

                # 2c. Notify user via license bot
                try:
                    tg_bot.send_message(
                        lic["user_id"],
                        f"⏰ <b>اشتراک ربات @{lic.get('bot_username','—')} به پایان رسید.</b>\n\n"
                        f"ربات شما خاموش شد.\n\n"
                        f"⚠️ اطلاعات ربات شما تا <b>48 ساعت دیگر</b> روی سرور باقی می‌ماند "
                        f"و سپس حذف خواهد شد.\n"
                        f"پس از حذف، در صورت نیاز باید اشتراک جدید خریداری کنید "
                        f"و دیتابیس خود را روی آن بارگذاری کنید.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

                # 2d. Notify via the bot's own token to its admin
                if lic.get("bot_token") and lic.get("admin_id"):
                    _notify_via_bot_token(
                        lic["bot_token"], lic["admin_id"],
                        "⏰ لایسنس ربات شما منقضی شد و ربات خاموش شد.\n"
                        "برای فعال‌سازی مجدد اشتراک جدید تهیه کنید."
                    )

                # 2e. Schedule deletion in 48 hours
                delete_at = time.time() + (48 * 3600)
                set_license_pending_delete(lic["id"], delete_at)
                set_license_expired_notified(lic["id"])

            # Step 3: permanently delete instances where 48h grace period is over
            for lic in get_expired_pending_delete():
                inst = get_instance_by_token(lic.get("bot_token", ""))
                if inst:
                    project = inst.get("project", "")
                    try:
                        remove_instance(project, lic["bot_token"])
                    except Exception as e:
                        logger.error(f"remove_instance failed for #{lic['id']}: {e}")
                    delete_instance(inst["id"])

                # Notify user of full removal
                try:
                    tg_bot.send_message(
                        lic["user_id"],
                        f"🗑 <b>ربات @{lic.get('bot_username','—')} از سرور حذف شد.</b>\n\n"
                        f"در صورت نیاز به راه‌اندازی مجدد، یک اشتراک جدید خریداری کنید "
                        f"و دیتابیس قبلی خود را روی آن بارگذاری کنید.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

                # Clear pending_delete_at so this doesn't re-trigger
                set_license_pending_delete(lic["id"], -1)
                logger.info(f"License #{lic['id']} instance fully removed after 48h grace period")

        except Exception as e:
            logger.error(f"expire_checker error: {e}")
        time.sleep(60)


def warning_checker():
    """Every 30 minutes: warn users whose licenses expire within 24h or 12h."""
    while True:
        time.sleep(1800)
        try:
            for warn_hours in (24, 12):
                expiring = get_licenses_expiring_soon(within_hours=warn_hours)
                for lic in expiring:
                    remaining_h = max(0, int((lic["expires_at"] - time.time()) / 3600))
                    remaining_m = max(0, int(((lic["expires_at"] - time.time()) % 3600) / 60))
                    if remaining_h > 0:
                        remaining_str = f"{remaining_h} ساعت"
                    else:
                        remaining_str = f"{remaining_m} دقیقه"

                    # Notify via license bot
                    try:
                        tg_bot.send_message(
                            lic["user_id"],
                            f"⚠️ <b>اشتراک ربات @{lic.get('bot_username','—')} رو به پایان است!</b>\n\n"
                            f"⏳ <b>{remaining_str} دیگر</b> اشتراک شما به پایان می‌رسد.\n\n"
                            f"برای تمدید اقدام کنید تا ربات شما قطع نشود.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                    # Notify via the bot's own token
                    if lic.get("bot_token") and lic.get("admin_id"):
                        _notify_via_bot_token(
                            lic["bot_token"], lic["admin_id"],
                            f"⚠️ لایسنس ربات شما {remaining_str} دیگر منقضی می‌شود.\n"
                            f"برای تمدید با پشتیبانی تماس بگیرید."
                        )

                    set_warning_sent(lic["id"], hours=warn_hours)
                    logger.info(f"Warning ({warn_hours}h) sent for license #{lic['id']}")
        except Exception as e:
            logger.error(f"warning_checker error: {e}")


def backup_worker():
    """Every hour: send .db backups of all active bot instances to backup channel."""
    while True:
        time.sleep(3600)
        try:
            instances = get_all_instances()
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            for inst in instances:
                idir = inst.get("instance_dir", "")
                if not idir or not os.path.isdir(idir):
                    continue
                db_files = [f for f in os.listdir(idir) if f.endswith(".db")]
                if not db_files:
                    continue

                owner = get_user(inst["user_id"])
                owner_name = ""
                if owner:
                    fn = owner.get("first_name") or ""
                    un = f" (@{owner['username']})" if owner.get("username") else ""
                    owner_name = fn + un

                caption = (
                    f"💾 <b>بکاپ اتوماتیک — {now_str}</b>\n\n"
                    f"🤖 ربات: @{inst.get('bot_username') or '—'}\n"
                    f"📌 پروژه: {inst.get('project', '—')}\n"
                    f"👤 صاحب: {owner_name} — <code>{inst['user_id']}</code>\n"
                    f"🆔 آیدی ادمین ربات: <code>{inst.get('admin_id', '—')}</code>"
                )
                for db_file in db_files:
                    db_path = os.path.join(idir, db_file)
                    try:
                        with open(db_path, "rb") as f:
                            tg_bot.send_document(
                                BACKUP_CHANNEL, f,
                                caption=caption, parse_mode="HTML",
                                visible_file_name=f"{inst.get('bot_username','bot')}_{db_file}"
                            )
                    except Exception as e:
                        logger.error(f"Backup send error {db_path}: {e}")
        except Exception as e:
            logger.error(f"backup_worker error: {e}")


def auto_update_worker():
    """Every AUTO_UPDATE_INTERVAL seconds, check both GitHub repos and update deployed bots if needed."""
    if not AUTO_UPDATE_ENABLED:
        logger.info("Automatic instance updater is disabled.")
        return

    tracked_projects = ("configflow", "seamless")
    logger.info(f"Automatic instance updater enabled (interval={AUTO_UPDATE_INTERVAL}s)")

    # Track the last commit we already applied so we don't re-apply or re-notify
    _last_applied: dict = {}

    while True:
        try:
            for project in tracked_projects:
                has_update, local_rev, remote_rev, err = repo_has_updates(project)
                if err:
                    logger.warning(f"auto_update_worker[{project}] check failed: {err}")
                    continue
                if not has_update:
                    continue

                # Skip if we already applied this exact remote commit
                if remote_rev and _last_applied.get(project) == remote_rev:
                    continue

                logger.info(
                    f"New GitHub update detected for {project}: "
                    f"{(local_rev or 'none')[:7]} -> {(remote_rev or 'none')[:7]}"
                )
                results = update_all_instances(project=project, refresh_cache=True)
                ok_count = sum(1 for _, ok, _ in results if ok)
                fail_count = sum(1 for _, ok, _ in results if not ok)
                changed_files = get_repo_changed_files(project, remote_rev, limit=8)
                logger.info(
                    f"Auto update finished for {project}: {ok_count} success, {fail_count} failed"
                )

                # Mark this commit as applied so we don't notify again next cycle
                if remote_rev:
                    _last_applied[project] = remote_rev

                if results:
                    files_block = ""
                    if changed_files:
                        files_block = "\n📝 فایل‌های تغییرکرده:\n" + "\n".join(
                            f"• {path}" for path in changed_files
                        )

                    summary = (
                        f"🔄 آپدیت خودکار {project}\n"
                        f"نسخه جدید از GitHub اعمال شد.\n"
                        f"✅ موفق: {ok_count}\n"
                        f"❌ خطا: {fail_count}\n"
                        f"Commit: {(local_rev or 'none')[:7]} -> {(remote_rev or 'none')[:7]}"
                        f"{files_block}"
                    )
                    for admin_id in ADMIN_IDS:
                        try:
                            tg_bot.send_message(admin_id, summary)
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"auto_update_worker error: {e}")

        time.sleep(AUTO_UPDATE_INTERVAL)


def start_license_api():
    """Start Flask API server for license checks."""
    from license_api import app as flask_app
    api_port = int(os.getenv("LICENSE_API_PORT", "8585"))
    logger.info(f"Starting License API on port {api_port}...")
    flask_app.run(host="0.0.0.0", port=api_port, use_reloader=False)


def main():
    logger.info("Initializing database...")
    init_db()

    logger.info("Starting expire checker thread...")
    threading.Thread(target=expire_checker, daemon=True).start()

    logger.info("Starting warning checker thread...")
    threading.Thread(target=warning_checker, daemon=True).start()

    logger.info("Starting backup worker thread...")
    threading.Thread(target=backup_worker, daemon=True).start()

    logger.info("Starting automatic updater thread...")
    threading.Thread(target=auto_update_worker, daemon=True).start()

    # Start License API in background thread
    api_thread = threading.Thread(target=start_license_api, daemon=True)
    api_thread.start()

    logger.info("Starting Seamless License Bot...")
    tg_bot.infinity_polling(timeout=60, long_polling_timeout=30)


if __name__ == "__main__":
    main()
