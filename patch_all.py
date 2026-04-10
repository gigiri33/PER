# -*- coding: utf-8 -*-
"""Patch script for donate/buy flows and plan cleanup."""
import re
import os

# â”€â”€â”€ 1. Update crypto.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
CRYPTO_FILE = r"c:\Users\HP\Desktop\Seamless\license__Seamless\bot\gateways\crypto.py"

new_crypto = '''# -*- coding: utf-8 -*-
"""
Crypto price fetching from SwapWallet market API.
"""
import json
import urllib.request

from ..config import CRYPTO_PRICES_API


def fetch_crypto_prices():
    """Return dict of {symbol: {"irt": float, "usdt": float}} or {} on error."""
    try:
        req = urllib.request.Request(
            CRYPTO_PRICES_API,
            headers={"User-Agent": "ConfigFlow/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        prices = {}
        for key, val in data.get("result", data).items():
            if "/" not in key:
                continue
            symbol, quote = key.split("/", 1)
            if quote not in ("IRT", "USDT"):
                continue
            try:
                price = float(str(val).replace(",", ""))
            except (ValueError, TypeError):
                continue
            prices.setdefault(symbol, {})[quote.lower()] = price
        return prices
    except Exception:
        return {}
'''

with open(CRYPTO_FILE, "w", encoding="utf-8") as f:
    f.write(new_crypto)
print("[OK] crypto.py updated")

# â”€â”€â”€ 2. Patch callbacks.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
CB_FILE = r"c:\Users\HP\Desktop\Seamless\license__Seamless\bot\handlers\callbacks.py"

with open(CB_FILE, "r", encoding="utf-8") as f:
    src = f.read()

# â”€â”€ 2a. Fix _get_usdt_to_toman â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
old_usdt = '''def _get_usdt_to_toman():
    """Fetch current USDTToman rate via Swapwallet API. Returns 0 on failure."""
    from ..gateways.crypto import fetch_crypto_prices
    prices = fetch_crypto_prices()
    return prices.get("USDT", 0)'''

new_usdt = '''def _get_usdt_to_toman():
    """Fetch current USDTâ†’Toman rate via Swapwallet API. Returns 0 on failure."""
    from ..gateways.crypto import fetch_crypto_prices
    prices = fetch_crypto_prices()
    data = prices.get("USDT", {})
    if isinstance(data, dict):
        return data.get("irt", 0)
    return float(data) if data else 0


def _get_coin_amount(amount_usdt, coin_symbol):
    """Return how many units of coin_symbol equal amount_usdt USDT. None on failure."""
    from ..gateways.crypto import fetch_crypto_prices
    from ..config import CRYPTO_API_SYMBOLS
    prices = fetch_crypto_prices()
    coin_data = prices.get(coin_symbol, {})
    usdt_rate = coin_data.get("usdt", 0) if isinstance(coin_data, dict) else 0
    if not usdt_rate:
        return None
    return amount_usdt / usdt_rate


def _fmt_coin(amount):
    """Format coin amount with appropriate precision."""
    if amount is None:
        return "?"
    if amount >= 100:
        return f"{amount:.2f}"
    elif amount >= 1:
        return f"{amount:.4f}"
    else:
        return f"{amount:.6f}"'''

if old_usdt in src:
    src = src.replace(old_usdt, new_usdt)
    print("âœ“ _get_usdt_to_toman + helpers added")
else:
    print("âœ— Could not find _get_usdt_to_toman")

# â”€â”€ 2b. Fix _show_donate_gateways â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
old_show_gw = '''def _show_donate_gateways(call, uid, amount):
    from ..gateways.base import is_gateway_available, is_card_info_complete
    from ..db import setting_get as sg
    kb = types.InlineKeyboardMarkup()
    if is_gateway_available("card") and is_card_info_complete():
        lbl = sg("gw_card_display_name", "").strip() or "ًں’³ ع©ط§ط±طھ ط¨ظ‡ ع©ط§ط±طھ"
        kb.add(types.InlineKeyboardButton(lbl, callback_data=f"donate_gw:card:{amount}"))
    if is_gateway_available("crypto"):
        lbl = sg("gw_crypto_display_name", "").strip() or "ًں’ژ ط§ط±ط² ط¯غŒط¬غŒطھط§ظ„"
        kb.add(types.InlineKeyboardButton(lbl, callback_data=f"donate_gw:crypto:{amount}"))
    kb.add(types.InlineKeyboardButton("â‌Œ ط§ظ†طµط±ط§ظپ", callback_data="main_menu"))
    text = (
        f"ًں’› <b>ط¯ظˆظ†غŒطھ â€” {amount} USDT</b>\\n\\n"
        "ط±ظˆط´ ظ¾ط±ط¯ط§ط®طھ ط±ط§ ط§ظ†طھط®ط§ط¨ ع©ظ†غŒط¯:"
    )
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")'''

new_show_gw = '''def _show_donate_gateways(call, uid, amount_usdt):
    from ..gateways.base import is_gateway_available, is_card_info_complete
    from ..db import setting_get as sg
    rate = _get_usdt_to_toman()
    amount_irt = int(amount_usdt * rate) if rate else 0
    irt_str = f" ({_fmt_toman(amount_irt)} طھظˆظ…ط§ظ†)" if amount_irt else ""
    kb = types.InlineKeyboardMarkup()
    if is_gateway_available("card") and is_card_info_complete():
        lbl = sg("gw_card_display_name", "").strip() or "ًں’³ ع©ط§ط±طھ ط¨ظ‡ ع©ط§ط±طھ"
        kb.add(types.InlineKeyboardButton(lbl + irt_str, callback_data=f"donate_gw:card:{amount_usdt}"))
    if is_gateway_available("tetrapay") and sg("tetrapay_api_key", ""):
        lbl = sg("gw_tetrapay_display_name", "").strip() or "ًںڈ¦ Tetrapay"
        kb.add(types.InlineKeyboardButton(lbl + irt_str, callback_data=f"donate_gw:tetrapay:{amount_usdt}"))
    if is_gateway_available("swapwallet_crypto") and sg("swapwallet_api_key", ""):
        lbl = sg("gw_swapwallet_crypto_display_name", "").strip() or "ًں”„ SwapWallet"
        kb.add(types.InlineKeyboardButton(lbl + irt_str, callback_data=f"donate_gw:swc:{amount_usdt}"))
    if is_gateway_available("tronpays_rial") and sg("tronpays_api_key", ""):
        lbl = sg("gw_tronpays_rial_display_name", "").strip() or "âڑ، TronPays"
        kb.add(types.InlineKeyboardButton(lbl + irt_str, callback_data=f"donate_gw:tronpays:{amount_usdt}"))
    if is_gateway_available("crypto"):
        lbl = sg("gw_crypto_display_name", "").strip() or "ًں’ژ ط§ط±ط² ط¯غŒط¬غŒطھط§ظ„"
        kb.add(types.InlineKeyboardButton(lbl, callback_data=f"donate_gw:crypto:{amount_usdt}"))
    kb.add(types.InlineKeyboardButton("â‌Œ ط§ظ†طµط±ط§ظپ", callback_data="main_menu"))
    toman_line = f"\\nًں’µ ظ…ط¹ط§ط¯ظ„: <b>{_fmt_toman(amount_irt)} طھظˆظ…ط§ظ†</b>" if amount_irt else ""
    text = (
        f"ًں’› <b>ط¯ظˆظ†غŒطھ â€” {amount_usdt} USDT</b>{toman_line}\\n\\n"
        "ط±ظˆط´ ظ¾ط±ط¯ط§ط®طھ ط±ط§ ط§ظ†طھط®ط§ط¨ ع©ظ†غŒط¯:"
    )
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")'''

if old_show_gw in src:
    src = src.replace(old_show_gw, new_show_gw)
    print("âœ“ _show_donate_gateways updated")
else:
    print("âœ— Could not find _show_donate_gateways â€” trying alternate match")
    # Try with actual newlines
    old_alt = "def _show_donate_gateways(call, uid, amount):"
    if old_alt in src:
        # Find the function boundaries
        start = src.find(old_alt)
        end = src.find("\ndef _show_donate_crypto", start)
        if end > start:
            old_block = src[start:end]
            src = src[:start] + new_show_gw + src[end:]
            print("âœ“ _show_donate_gateways updated via boundary match")
        else:
            print("âœ— Failed to find _show_donate_gateways end boundary")

# â”€â”€ 2c. Fix cb_donate_gw (add tetrapay/swc/tronpays handling) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
old_donate_gw_end = '''    bot.answer_callback_query(call.id, "âڑ ï¸ڈ ط¯ط±ع¯ط§ظ‡ ظ¾ط´طھغŒط¨ط§ظ†غŒâ€Œظ†ط´ط¯ظ‡", show_alert=True)


def _show_donate_gateways(call, uid, amount):'''

new_donate_gw_end = '''    # Convert USDT to IRT for rial gateways
    rate = _get_usdt_to_toman()
    amount_irt = int(amount * rate) if rate else 0

    donate_id = create_donate_payment(uid, amount, "USDT", gw)

    if not amount_irt:
        bot.answer_callback_query(call.id, "âڑ ï¸ڈ ظ‚غŒظ…طھ طھظˆظ…ط§ظ† ط¯ط± ط¯ط³طھط±ط³ ظ†غŒط³طھ. ط¨ط¹ط¯ط§ظ‹ طھظ„ط§ط´ ع©ظ†غŒط¯.", show_alert=True)
        return

    if gw == "tetrapay":
        from ..gateways.tetrapay import create_tetrapay_order
        ok, result = create_tetrapay_order(amount_irt, f"donate_{donate_id}", f"ط¯ظˆظ†غŒطھ {amount} USDT")
        if ok:
            pay_url = result.get("payment_url") or result.get("url") or ""
            text = (
                f"ًںڈ¦ <b>ظ¾ط±ط¯ط§ط®طھ Tetrapay</b>\\n\\n"
                f"ًں’° {amount} USDT â€” {_fmt_toman(amount_irt)} طھظˆظ…ط§ظ†\\n\\n"
                f"ًں”— ظ„غŒظ†ع© ظ¾ط±ط¯ط§ط®طھ:\\n{pay_url}\\n\\n"
                f"ًں†” #{donate_id}"
            )
        else:
            text = f"â‌Œ ط®ط·ط§ ط¯ط± Tetrapay:\\n{result.get('error', str(result))[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton("ًں’³ ظ¾ط±ط¯ط§ط®طھ ط¢ظ†ظ„ط§غŒظ†", url=pay_url))
        kb.add(types.InlineKeyboardButton("ًں”™ ط¨ط§ط²ع¯ط´طھ", callback_data="donate"))
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
                f"ًں”„ <b>ظ¾ط±ط¯ط§ط®طھ SwapWallet</b>\\n\\n"
                f"ًں’° {amount} USDT â€” {_fmt_toman(amount_irt)} طھظˆظ…ط§ظ†\\n\\n"
                f"ًں”— ظ„غŒظ†ع© ظ¾ط±ط¯ط§ط®طھ:\\n{pay_url}\\n\\n"
                f"ًں†” #{donate_id}"
            )
        else:
            text = f"â‌Œ ط®ط·ط§ ط¯ط± SwapWallet:\\n{str(result)[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton("ًں’³ ظ¾ط±ط¯ط§ط®طھ ط¢ظ†ظ„ط§غŒظ†", url=pay_url))
        kb.add(types.InlineKeyboardButton("ًں”™ ط¨ط§ط²ع¯ط´طھ", callback_data="donate"))
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
                f"âڑ، <b>ظ¾ط±ط¯ط§ط®طھ TronPays</b>\\n\\n"
                f"ًں’° {amount} USDT â€” {_fmt_toman(amount_irt)} طھظˆظ…ط§ظ†\\n\\n"
                f"ًں”— ظ„غŒظ†ع© ظ¾ط±ط¯ط§ط®طھ:\\n{pay_url}\\n\\n"
                f"ًں†” #{donate_id}"
            )
        else:
            text = f"â‌Œ ط®ط·ط§ ط¯ط± TronPays:\\n{str(result)[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton("ًں’³ ظ¾ط±ط¯ط§ط®طھ ط¢ظ†ظ„ط§غŒظ†", url=pay_url))
        kb.add(types.InlineKeyboardButton("ًں”™ ط¨ط§ط²ع¯ط´طھ", callback_data="donate"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
        bot.answer_callback_query(call.id)
        return

    bot.answer_callback_query(call.id, "âڑ ï¸ڈ ط¯ط±ع¯ط§ظ‡ ظ¾ط´طھغŒط¨ط§ظ†غŒâ€Œظ†ط´ط¯ظ‡", show_alert=True)


def _show_donate_gateways(call, uid, amount_usdt):'''

# Find and replace the end of cb_donate_gw
# The old code ends with "bot.answer_callback_query(call.id, "âڑ ï¸ڈ ط¯ط±ع¯ط§ظ‡ ظ¾ط´طھغŒط¨ط§ظ†غŒâ€Œظ†ط´ط¯ظ‡", show_alert=True)"
# followed by "_show_donate_gateways"
# We need to restructure cb_donate_gw to remove the old "donate_id" line and add tetrapay/swc/tronpays

# First, let's find the card handling block and replace from after it
old_card_block = '''    donate_id = create_donate_payment(uid, amount, "USDT", gw)

    # Card to card
    if gw == "card":
        card = sg("payment_card", "â€”")
        bank = sg("payment_bank", "â€”")
        owner = sg("payment_owner", "â€”")
        text = (
            f"ًں’³ <b>ظ¾ط±ط¯ط§ط®طھ ع©ط§ط±طھ ط¨ظ‡ ع©ط§ط±طھ</b>\\n\\n"
            f"ًں’° ظ…ط¨ظ„ط؛: <b>{amount} USDT</b>\\n\\n"
            f"ًںڈ¦ ط¨ط§ظ†ع©: <b>{esc(bank)}</b>\\n"
            f"ًں’³ ط´ظ…ط§ط±ظ‡ ع©ط§ط±طھ: <code>{esc(card)}</code>\\n"
            f"ًں‘¤ ط¨ظ‡ ظ†ط§ظ…: <b>{esc(owner)}</b>\\n\\n"
            f"ظ¾ط³ ط§ط² ظ¾ط±ط¯ط§ط®طھ ط±ط³غŒط¯ ط®ظˆط¯ ط±ط§ ط¨ط±ط§غŒ ط§ط¯ظ…غŒظ† ط§ط±ط³ط§ظ„ ع©ظ†غŒط¯:\\n{SUPPORT_USERNAME}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("ًں”™ ط¨ط§ط²ع¯ط´طھ", callback_data="donate"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
        # Notify admins
        u = get_user(uid)
        uname = f"@{u['username']}" if u and u.get("username") else str(uid)
        for adm in ADMIN_IDS:
            try:
                tg_bot_notify = bot
                tg_bot_notify.send_message(adm,
                    f"ًں’› <b>ط¯ظˆظ†غŒطھ ط¬ط¯غŒط¯ (ع©ط§ط±طھ)</b>\\n"
                    f"ًں‘¤ {esc(uname)} â€” <code>{uid}</code>\\n"
                    f"ًں’° {amount} USDT\\nًں†” #{donate_id}"
                )
            except Exception:
                pass
        bot.answer_callback_query(call.id)
        return

    bot.answer_callback_query(call.id, "âڑ ï¸ڈ ط¯ط±ع¯ط§ظ‡ ظ¾ط´طھغŒط¨ط§ظ†غŒâ€Œظ†ط´ط¯ظ‡", show_alert=True)'''

new_card_block = '''    # Convert USDT to IRT for rial gateways
    rate = _get_usdt_to_toman()
    amount_irt = int(amount * rate) if rate else 0

    donate_id = create_donate_payment(uid, amount, "USDT", gw)

    # Card to card
    if gw == "card":
        card = sg("payment_card", "â€”")
        bank = sg("payment_bank", "â€”")
        owner = sg("payment_owner", "â€”")
        irt_line = f"\\nًں’µ ظ…ط¹ط§ط¯ظ„: <b>{_fmt_toman(amount_irt)} طھظˆظ…ط§ظ†</b>" if amount_irt else ""
        text = (
            f"ًں’³ <b>ظ¾ط±ط¯ط§ط®طھ ع©ط§ط±طھ ط¨ظ‡ ع©ط§ط±طھ</b>\\n\\n"
            f"ًں’° ظ…ط¨ظ„ط؛: <b>{amount} USDT</b>{irt_line}\\n\\n"
            f"ًںڈ¦ ط¨ط§ظ†ع©: <b>{esc(bank)}</b>\\n"
            f"ًں’³ ط´ظ…ط§ط±ظ‡ ع©ط§ط±طھ: <code>{esc(card)}</code>\\n"
            f"ًں‘¤ ط¨ظ‡ ظ†ط§ظ…: <b>{esc(owner)}</b>\\n\\n"
            f"ظ¾ط³ ط§ط² ظ¾ط±ط¯ط§ط®طھ ط±ط³غŒط¯ ط®ظˆط¯ ط±ط§ ط¨ط±ط§غŒ ط§ط¯ظ…غŒظ† ط§ط±ط³ط§ظ„ ع©ظ†غŒط¯:\\n{SUPPORT_USERNAME}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("ًں”™ ط¨ط§ط²ع¯ط´طھ", callback_data="donate"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
        # Notify admins
        u = get_user(uid)
        uname = f"@{u['username']}" if u and u.get("username") else str(uid)
        for adm in ADMIN_IDS:
            try:
                bot.send_message(adm,
                    f"ًں’› <b>ط¯ظˆظ†غŒطھ ط¬ط¯غŒط¯ (ع©ط§ط±طھ)</b>\\n"
                    f"ًں‘¤ {esc(uname)} â€” <code>{uid}</code>\\n"
                    f"ًں’° {amount} USDT\\nًں†” #{donate_id}"
                )
            except Exception:
                pass
        bot.answer_callback_query(call.id)
        return

    if not amount_irt:
        bot.answer_callback_query(call.id, "âڑ ï¸ڈ ظ‚غŒظ…طھ طھظˆظ…ط§ظ† ط¯ط± ط¯ط³طھط±ط³ ظ†غŒط³طھ. ط¨ط¹ط¯ط§ظ‹ طھظ„ط§ط´ ع©ظ†غŒط¯.", show_alert=True)
        return

    if gw == "tetrapay":
        from ..gateways.tetrapay import create_tetrapay_order
        ok, result = create_tetrapay_order(amount_irt, f"donate_{donate_id}", f"ط¯ظˆظ†غŒطھ {amount} USDT")
        if ok:
            pay_url = result.get("payment_url") or result.get("url") or ""
            text = (
                f"ًںڈ¦ <b>ظ¾ط±ط¯ط§ط®طھ Tetrapay</b>\\n\\n"
                f"ًں’° {amount} USDT â€” {_fmt_toman(amount_irt)} طھظˆظ…ط§ظ†\\n\\n"
                f"ًں”— ظ„غŒظ†ع© ظ¾ط±ط¯ط§ط®طھ:\\n{pay_url}\\n\\n"
                f"ًں†” #{donate_id}"
            )
        else:
            text = f"â‌Œ ط®ط·ط§ ط¯ط± Tetrapay:\\n{result.get('error', str(result))[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton("ًں’³ ظ¾ط±ط¯ط§ط®طھ ط¢ظ†ظ„ط§غŒظ†", url=pay_url))
        kb.add(types.InlineKeyboardButton("ًں”™ ط¨ط§ط²ع¯ط´طھ", callback_data="donate"))
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
                f"ًں”„ <b>ظ¾ط±ط¯ط§ط®طھ SwapWallet</b>\\n\\n"
                f"ًں’° {amount} USDT â€” {_fmt_toman(amount_irt)} طھظˆظ…ط§ظ†\\n\\n"
                f"ًں”— ظ„غŒظ†ع© ظ¾ط±ط¯ط§ط®طھ:\\n{pay_url}\\n\\n"
                f"ًں†” #{donate_id}"
            )
        else:
            text = f"â‌Œ ط®ط·ط§ ط¯ط± SwapWallet:\\n{str(result)[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton("ًں’³ ظ¾ط±ط¯ط§ط®طھ ط¢ظ†ظ„ط§غŒظ†", url=pay_url))
        kb.add(types.InlineKeyboardButton("ًں”™ ط¨ط§ط²ع¯ط´طھ", callback_data="donate"))
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
                f"âڑ، <b>ظ¾ط±ط¯ط§ط®طھ TronPays</b>\\n\\n"
                f"ًں’° {amount} USDT â€” {_fmt_toman(amount_irt)} طھظˆظ…ط§ظ†\\n\\n"
                f"ًں”— ظ„غŒظ†ع© ظ¾ط±ط¯ط§ط®طھ:\\n{pay_url}\\n\\n"
                f"ًں†” #{donate_id}"
            )
        else:
            text = f"â‌Œ ط®ط·ط§ ط¯ط± TronPays:\\n{str(result)[:200]}"
        kb = types.InlineKeyboardMarkup()
        if ok and pay_url:
            kb.add(types.InlineKeyboardButton("ًں’³ ظ¾ط±ط¯ط§ط®طھ ط¢ظ†ظ„ط§غŒظ†", url=pay_url))
        kb.add(types.InlineKeyboardButton("ًں”™ ط¨ط§ط²ع¯ط´طھ", callback_data="donate"))
        try:
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
        bot.answer_callback_query(call.id)
        return

    bot.answer_callback_query(call.id, "âڑ ï¸ڈ ط¯ط±ع¯ط§ظ‡ ظ¾ط´طھغŒط¨ط§ظ†غŒâ€Œظ†ط´ط¯ظ‡", show_alert=True)'''

if old_card_block in src:
    src = src.replace(old_card_block, new_card_block)
    print("âœ“ cb_donate_gw card block + new gateways updated")
else:
    print("âœ— Could not find cb_donate_gw card block")

# â”€â”€ 2d. Fix cb_donate_crypto (show coin equivalent amount) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
old_donate_crypto = '''@bot.callback_query_handler(func=lambda c: c.data.startswith("donate_crypto:"))
def cb_donate_crypto(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    coin_key = parts[1]
    amount = parts[2]
    from ..config import CRYPTO_COINS
    from ..db import setting_get as sg
    addr = sg(f"crypto_{coin_key}", "")
    label = next((l for k, l in CRYPTO_COINS if k == coin_key), coin_key)
    if not addr:
        bot.answer_callback_query(call.id, "âڑ ï¸ڈ ط¢ط¯ط±ط³ ط§غŒظ† ط§ط±ط² ظ‡ظ†ظˆط² ط«ط¨طھ ظ†ط´ط¯ظ‡.", show_alert=True)
        return
    text = (
        f"ًں’› <b>ط¯ظˆظ†غŒطھ ط¨ط§ {label}</b>\\n\\n"
        f"ًں’° ظ…ط¹ط§ط¯ظ„ {amount} USDT ط§ط±ط³ط§ظ„ ع©ظ†غŒط¯\\n\\n"
        f"ًں“¬ ط¢ط¯ط±ط³:\\n<code>{esc(addr)}</code>\\n\\n"
        f"ظ¾ط³ ط§ط² ط§ط±ط³ط§ظ„ ط¨ظ‡ {SUPPORT_USERNAME} ط§ط·ظ„ط§ط¹ ط¯ظ‡غŒط¯."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("ًں”™ ط¨ط§ط²ع¯ط´طھ", callback_data="donate"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)'''

new_donate_crypto = '''@bot.callback_query_handler(func=lambda c: c.data.startswith("donate_crypto:"))
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
        bot.answer_callback_query(call.id, "âڑ ï¸ڈ ط¢ط¯ط±ط³ ط§غŒظ† ط§ط±ط² ظ‡ظ†ظˆط² ط«ط¨طھ ظ†ط´ط¯ظ‡.", show_alert=True)
        return
    api_symbol = CRYPTO_API_SYMBOLS.get(coin_key, coin_key.upper())
    coin_amount = _get_coin_amount(amount_usdt, api_symbol)
    coin_line = f"\\nًں’± ظ…ط¹ط§ط¯ظ„: <b>{_fmt_coin(coin_amount)} {api_symbol}</b>" if coin_amount else ""
    text = (
        f"ًں’› <b>ط¯ظˆظ†غŒطھ ط¨ط§ {label}</b>\\n\\n"
        f"ًں’° ظ…ط¨ظ„ط؛: <b>{amount_usdt} USDT</b>{coin_line}\\n\\n"
        f"ًں“¬ ط¢ط¯ط±ط³:\\n<code>{esc(addr)}</code>\\n\\n"
        f"ظ¾ط³ ط§ط² ط§ط±ط³ط§ظ„ ط¨ظ‡ {SUPPORT_USERNAME} ط§ط·ظ„ط§ط¹ ط¯ظ‡غŒط¯."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("ًں”™ ط¨ط§ط²ع¯ط´طھ", callback_data="donate"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)'''

if old_donate_crypto in src:
    src = src.replace(old_donate_crypto, new_donate_crypto)
    print("âœ“ cb_donate_crypto updated")
else:
    print("âœ— Could not find cb_donate_crypto")

# â”€â”€ 2e. Remove sm_monthly from _PLAN_INFO â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Use regex to replace the entire _PLAN_INFO block safely
plan_pattern = re.compile(
    r'(_PLAN_INFO\s*=\s*\{[^}]*?"sm_monthly"[^}]*?\})',
    re.DOTALL
)
def replace_plan_info(m):
    old = m.group(1)
    # Extract just cf_hosted and sm_premium lines
    lines = old.split('\n')
    new_lines = []
    for line in lines:
        if '"sm_monthly"' in line:
            continue  # remove this line
        new_lines.append(line)
    return '\n'.join(new_lines)

new_src, count = plan_pattern.subn(replace_plan_info, src)
if count:
    src = new_src
    print("âœ“ sm_monthly removed from _PLAN_INFO")
else:
    print("âœ— Could not find _PLAN_INFO with sm_monthly")

# â”€â”€ 2f. Fix cb_buy_type seamless branch (remove monthly, show only premium) â”€â”€
old_buy_type_else = '''    else:
        sm_monthly_price = float(setting_get("price_sm_monthly", "10"))
        sm_premium_price = float(setting_get("price_sm_premium", "25"))
        sm_monthly_toman = int(sm_monthly_price * rate) if rate else 0
        sm_premium_toman = int(sm_premium_price * rate) if rate else 0
        m_toman = f"  {_fmt_toman(sm_monthly_toman)} طھظˆظ…ط§ظ†" if sm_monthly_toman else ""
        p_toman = f"  {_fmt_toman(sm_premium_toman)} طھظˆظ…ط§ظ†" if sm_premium_toman else ""
        text = (
            " <b>Seamless  ط®ط±غŒط¯ ط§ط´طھط±ط§ع©</b>\\n\\n"
            f" <b>ظ…ط§ظ‡ط§ظ†ظ‡ (ط³ط±ظˆط± ظ…ط§):</b>\\n   {sm_monthly_price:.0f} USDT{m_toman}\\n\\n"
            f" <b>ظ¾ط±ظ…غŒظˆظ… (ظ„ط§غŒط³ظ†ط³ ط§ط®طھطµط§طµغŒ):</b>\\n   {sm_premium_price:.0f} USDT{p_toman}"
        )
        kb.row(
            types.InlineKeyboardButton(f" ظ…ط§ظ‡ط§ظ†ظ‡  {sm_monthly_price:.0f} USDT", callback_data="buy_plan:sm_monthly"),
            types.InlineKeyboardButton(f" ظ¾ط±ظ…غŒظˆظ…  {sm_premium_price:.0f} USDT", callback_data="buy_plan:sm_premium"),
        )'''

# Find the else branch in cb_buy_type - use regex since there are emojis
buy_type_pattern = re.compile(
    r'(    else:\s*\n        sm_monthly_price = float\(setting_get\("price_sm_monthly".*?kb\.row\(\s*\n            types\.InlineKeyboardButton\(f".*?sm_monthly.*?\),\s*\n            types\.InlineKeyboardButton\(f".*?sm_premium.*?\),\s*\n        \))',
    re.DOTALL
)

new_buy_type_else = '''    else:
        sm_premium_price = float(setting_get("price_sm_premium", "25"))
        sm_premium_toman = int(sm_premium_price * rate) if rate else 0
        p_toman = f"\\nًں’µ {_fmt_toman(sm_premium_toman)} طھظˆظ…ط§ظ†" if sm_premium_toman else ""
        text = (
            "ًںŒٹ <b>Seamless â€” ط®ط±غŒط¯ ط§ط´طھط±ط§ع©</b>\\n\\n"
            f"ًں’ژ <b>ظ¾ط±ظ…غŒظˆظ… (ظ„ط§غŒط³ظ†ط³ ط§ط®طھطµط§طµغŒ):</b>\\n"
            f"   {sm_premium_price:.0f} USDT{p_toman}"
        )
        kb.add(types.InlineKeyboardButton(f"ًں’ژ ظ¾ط±ظ…غŒظˆظ… â€” {sm_premium_price:.0f} USDT", callback_data="buy_plan:sm_premium"))'''

new_src, count = buy_type_pattern.subn(new_buy_type_else, src)
if count:
    src = new_src
    print("âœ“ cb_buy_type seamless branch updated (removed monthly)")
else:
    # fallback: try simpler string match
    locs = []
    search = 'sm_monthly_price = float(setting_get("price_sm_monthly"'
    idx = src.find(search)
    if idx != -1:
        # Find the enclosing else block
        else_start = src.rfind("    else:", 0, idx)
        # Find end of kb.row block
        kb_row_end = src.find("\n    kb.add(types.InlineKeyboardButton(\" ط¨ط§ط²ع¯ط´طھ\"", idx)
        if kb_row_end == -1:
            kb_row_end = src.find("\n\n    kb.add(types.InlineKeyboardButton(", idx)
        if else_start != -1 and kb_row_end != -1:
            old_block = src[else_start:kb_row_end]
            src = src[:else_start] + new_buy_type_else + src[kb_row_end:]
            print("âœ“ cb_buy_type seamless branch updated via fallback")
        else:
            print(f"âœ— Could not find cb_buy_type else boundaries (else_start={else_start}, kb_row_end={kb_row_end})")
    else:
        print("âœ— Could not find cb_buy_type seamless branch")

# â”€â”€ 2g. Fix cb_buy_crypto (show coin equivalent) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
old_buy_crypto_func = '''@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_crypto:"))
def cb_buy_crypto(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    coin_key = parts[1]
    order_id = parts[2]
    from ..config import CRYPTO_COINS
    addr = setting_get(f"crypto_{coin_key}", "")
    label = next((l for k, l in CRYPTO_COINS if k == coin_key), coin_key)
    if not addr:
        bot.answer_callback_query(call.id, " ط¢ط¯ط±ط³ ط§غŒظ† ط§ط±ط² ط«ط¨طھ ظ†ط´ط¯ظ‡ ط§ط³طھ.", show_alert=True)
        return
    text = (
        f" <b>ظ¾ط±ط¯ط§ط®طھ ط¨ط§ {label}</b>\\n\\n"
        f" ط¢ط¯ط±ط³:\\n<code>{esc(addr)}</code>\\n\\n"
        f" ط³ظپط§ط±ط´ #{order_id}\\n"
        f"ظ¾ط³ ط§ط² ط§ط±ط³ط§ظ„ ط¨ظ‡ {SUPPORT_USERNAME} ط§ط·ظ„ط§ط¹ ط¯ظ‡غŒط¯."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(" ظ…ظ†ظˆغŒ ط§طµظ„غŒ", callback_data="main_menu"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:'''

# Use simpler regex match to find cb_buy_crypto
buy_crypto_pattern = re.compile(
    r'@bot\.callback_query_handler\(func=lambda c: c\.data\.startswith\("buy_crypto:"\)\)\ndef cb_buy_crypto\(call\):.*?bot\.answer_callback_query\(call\.id\)',
    re.DOTALL
)

new_buy_crypto_func = '''@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_crypto:"))
def cb_buy_crypto(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    coin_key = parts[1]
    order_id = parts[2]
    from ..config import CRYPTO_COINS, CRYPTO_API_SYMBOLS
    addr = setting_get(f"crypto_{coin_key}", "")
    label = next((l for k, l in CRYPTO_COINS if k == coin_key), coin_key)
    if not addr:
        bot.answer_callback_query(call.id, "âڑ ï¸ڈ ط¢ط¯ط±ط³ ط§غŒظ† ط§ط±ط² ط«ط¨طھ ظ†ط´ط¯ظ‡ ط§ط³طھ.", show_alert=True)
        return
    order = get_subscription_order(order_id)
    amount_usdt = float(order["final_usdt"]) if order else 0
    api_symbol = CRYPTO_API_SYMBOLS.get(coin_key, coin_key.upper())
    coin_amount = _get_coin_amount(amount_usdt, api_symbol) if amount_usdt else None
    usdt_line = f"\\nًں’° ظ…ط¨ظ„ط؛: <b>{amount_usdt:.2f} USDT</b>" if amount_usdt else ""
    coin_line = f"\\nًں’± ظ…ط¹ط§ط¯ظ„: <b>{_fmt_coin(coin_amount)} {api_symbol}</b>" if coin_amount else ""
    text = (
        f"ًں’ژ <b>ظ¾ط±ط¯ط§ط®طھ ط¨ط§ {label}</b>{usdt_line}{coin_line}\\n\\n"
        f"ًں“¬ ط¢ط¯ط±ط³:\\n<code>{esc(addr)}</code>\\n\\n"
        f"ًں†” ط³ظپط§ط±ط´ #{order_id}\\n"
        f"ظ¾ط³ ط§ط² ط§ط±ط³ط§ظ„ ط¨ظ‡ {SUPPORT_USERNAME} ط§ط·ظ„ط§ط¹ ط¯ظ‡غŒط¯."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("ًں”™ ظ…ظ†ظˆغŒ ط§طµظ„غŒ", callback_data="main_menu"))
    try:
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
    bot.answer_callback_query(call.id)'''

new_src, count = buy_crypto_pattern.subn(new_buy_crypto_func, src)
if count:
    src = new_src
    print("âœ“ cb_buy_crypto updated")
else:
    print("âœ— Could not find cb_buy_crypto via regex")

# â”€â”€ 2h. Fix _show_admin_prices (remove sm_monthly) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
admin_prices_pattern = re.compile(
    r'(def _show_admin_prices\(uid, msg_id\):.*?kb\.add\(types\.InlineKeyboardButton\(" ظ¾ظ†ظ„ ظ…ط¯غŒط±غŒطھ".*?\))',
    re.DOTALL
)

new_admin_prices = '''def _show_admin_prices(uid, msg_id):
    cf = float(setting_get("price_cf_hosted",  "10"))
    sp = float(setting_get("price_sm_premium", "25"))
    rate = _get_usdt_to_toman()
    def _t(n): return f"  {_fmt_toman(int(n * rate))} طھظˆظ…ط§ظ†" if rate else ""
    text = (
        "ًں’° <b>ظ‚غŒظ…طھâ€Œع¯ط°ط§ط±غŒ ظ¾ظ„ظ†â€Œظ‡ط§</b>\\n\\n"
        f"âڑ، ConfigFlow (ط³ط±ظˆط± ظ…ط§): <b>{cf:.0f} USDT</b>{_t(cf)}\\n"
        f"ًں’ژ Seamless ظ¾ط±ظ…غŒظˆظ…: <b>{sp:.0f} USDT</b>{_t(sp)}\\n"
    )
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("âڑ، ConfigFlow", callback_data="adm:price_set:price_cf_hosted"),
        types.InlineKeyboardButton("ًں’ژ Seamless ظ¾ط±ظ…غŒظˆظ…", callback_data="adm:price_set:price_sm_premium"),
    )
    kb.add(types.InlineKeyboardButton("ًں”™ ظ¾ظ†ظ„ ظ…ط¯غŒط±غŒطھ", callback_data="admin_panel"))'''

new_src, count = admin_prices_pattern.subn(new_admin_prices, src)
if count:
    src = new_src
    print("âœ“ _show_admin_prices updated")
else:
    print("âœ— Could not find _show_admin_prices via regex")

# â”€â”€ Write output â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
with open(CB_FILE, "w", encoding="utf-8") as f:
    f.write(src)
print("âœ“ callbacks.py written")
print("\nDone!")
