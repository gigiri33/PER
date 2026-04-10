# -*- coding: utf-8 -*-
"""
License verification module.
Checks license validity against the Seamless License Bot API every hour.
If license is invalid/expired, the bot stops responding.
"""
import time
import threading
import logging
import requests

from .config import BOT_TOKEN, LICENSE_API_URL, ADMIN_IDS
from .bot_instance import bot

logger = logging.getLogger(__name__)

# Global license status — other modules can check this
license_valid = True
license_info = {}
_CHECK_INTERVAL = 3600  # 1 hour


def check_license_once():
    """Call the license API and return True/False."""
    global license_valid, license_info
    if not LICENSE_API_URL:
        # No license server configured — allow (dev mode)
        license_valid = True
        return True
    try:
        resp = requests.get(
            f"{LICENSE_API_URL.rstrip('/')}/api/check",
            params={"token": BOT_TOKEN},
            timeout=15
        )
        data = resp.json()
        if data.get("valid"):
            license_valid = True
            license_info = data
            logger.info(
                f"✅ License OK — plan: {data.get('plan')}, "
                f"remaining: {data.get('remaining_hours')}h"
            )
            return True
        else:
            license_valid = False
            license_info = data
            logger.warning(f"❌ License invalid: {data.get('error', 'unknown')}")
            # Notify admins
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_message(
                        admin_id,
                        "⚠️ <b>هشدار لایسنس!</b>\n\n"
                        f"❌ لایسنس ربات معتبر نیست.\n"
                        f"دلیل: {data.get('error', 'نامشخص')}\n\n"
                        "ربات تا زمان تمدید لایسنس غیرفعال خواهد شد.\n"
                        "📞 پشتیبانی: @license_Seamless_BOT"
                    )
                except Exception:
                    pass
            return False
    except Exception as e:
        logger.error(f"License check failed (network): {e}")
        # On network error, keep the last known state
        return license_valid


def license_checker_loop():
    """Background thread: checks license every hour."""
    # First check immediately at startup
    check_license_once()
    while True:
        time.sleep(_CHECK_INTERVAL)
        check_license_once()


def start_license_checker():
    """Start the license checker background thread."""
    t = threading.Thread(target=license_checker_loop, daemon=True)
    t.start()
    logger.info("License checker started (interval: 1h)")


def is_licensed():
    """Check if the bot currently has a valid license."""
    return license_valid
