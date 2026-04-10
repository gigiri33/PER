# -*- coding: utf-8 -*-
"""
Gateway availability checks shared across all payment gateways.
Adapted for Seamless License Bot (no user-status concept).
"""
from ..db import setting_get

_ALL_GATEWAYS = ("card", "crypto", "tetrapay", "swapwallet_crypto", "tronpays_rial")


def is_gateway_available(gw_name, user_id=None, amount=None):
    """Return True if the named gateway is enabled."""
    enabled = setting_get(f"gw_{gw_name}_enabled", "0")
    if enabled != "1":
        return False
    if amount is not None:
        range_enabled = setting_get(f"gw_{gw_name}_range_enabled", "0")
        if range_enabled == "1":
            range_min = setting_get(f"gw_{gw_name}_range_min", "")
            range_max = setting_get(f"gw_{gw_name}_range_max", "")
            if range_min and int(range_min) > amount:
                return False
            if range_max and int(range_max) < amount:
                return False
    return True


def get_gateway_range_text(gw_name):
    """Return a short range description for a gateway, e.g. '۵۰۰,۰۰۰ تا ۱,۸۰۰,۰۰۰'.
    Returns '' if range is not enabled."""
    if setting_get(f"gw_{gw_name}_range_enabled", "0") != "1":
        return "بدون محدودیت مبلغی"
    r_min = setting_get(f"gw_{gw_name}_range_min", "")
    r_max = setting_get(f"gw_{gw_name}_range_max", "")
    if r_min and r_max:
        return f"{int(r_min):,} تا {int(r_max):,} تومان"
    elif r_min:
        return f"حداقل {int(r_min):,} تومان — حداکثر ندارد"
    elif r_max:
        return f"حداقل ندارد — حداکثر {int(r_max):,} تومان"
    else:
        return "بدون محدودیت مبلغی"


def is_card_info_complete():
    """Return True if all card-to-card payment details have been configured."""
    return all([
        setting_get("payment_card", ""),
        setting_get("payment_bank", ""),
        setting_get("payment_owner", ""),
    ])


def is_gateway_in_range(gw_name, amount):
    """Return True if amount is within the gateway's allowed range (or range is disabled)."""
    if setting_get(f"gw_{gw_name}_range_enabled", "0") != "1":
        return True
    r_min = setting_get(f"gw_{gw_name}_range_min", "")
    r_max = setting_get(f"gw_{gw_name}_range_max", "")
    if r_min and int(r_min) > amount:
        return False
    if r_max and int(r_max) < amount:
        return False
    return True


def build_gateway_range_guide(gw_label_pairs):
    """Build a guide text listing each gateway's range.
    gw_label_pairs: list of (gw_name, display_label) tuples.
    Returns a string like:
      📋 راهنمای انتخاب درگاه پرداخت:
      • کارت به کارت: ۵۰۰٬۰۰۰ تا ۱٬۸۰۰٬۰۰۰ تومان
      • ارز دیجیتال: بدون محدودیت مبلغی
    """
    lines = []
    for gw_name, label in gw_label_pairs:
        rng = get_gateway_range_text(gw_name)
        lines.append(f"  • {label}: {rng}")
    if not lines:
        return ""
    return "📋 <b>راهنمای انتخاب درگاه پرداخت:</b>\n" + "\n".join(lines)
