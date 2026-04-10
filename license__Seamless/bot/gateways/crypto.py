# -*- coding: utf-8 -*-
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
