# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_NAME = os.getenv("DB_NAME", "license.db")

# Trial duration in hours
TRIAL_HOURS = 48

# Subscription plans (prices in USDT)
PLAN_MONTHLY_HOSTED = 10      # ماهانه - ران روی سرور ما
PLAN_PREMIUM_LICENSE = 25     # خرید لایسنس نسخه اشتراکی

# Bot demo links
SEAMLESS_DEMO_BOT = "https://t.me/Seamless_ROBOT"
CONFIGFLOW_DEMO_BOT = "https://t.me/ConfigFlowROBOT"

# ConfigFlow install command
CONFIGFLOW_INSTALL_CMD = "bash &lt;(curl -s https://raw.githubusercontent.com/Emadhabibnia1385/ConfigFlow/main/install.sh)"

# ConfigFlow GitHub
CONFIGFLOW_GITHUB = "https://github.com/Emadhabibnia1385/ConfigFlow"

# Deployment
DEPLOY_BASE_DIR = "/opt/license-bots"
CONFIGFLOW_REPO_URL = "https://github.com/Emadhabibnia1385/ConfigFlow.git"
SEAMLESS_REPO_URL = "https://github.com/gigiri33/PER.git"
LICENSE_API_PORT = int(os.getenv("LICENSE_API_PORT", "8585"))

# Support
SUPPORT_USERNAME = "https://t.me/EmadHabibnia?direct"
CHANNEL_USERNAME = "@Emadhabibnia"

# ── Payment Gateways ───────────────────────────────────────────────────────────
CRYPTO_PRICES_API   = "https://swapwallet.app/api/v1/market/prices"
TETRAPAY_CREATE_URL = "https://tetra98.com/api/create_order"
TETRAPAY_VERIFY_URL = "https://tetra98.com/api/verify"
SWAPWALLET_BASE_URL = "https://swapwallet.app/api"
CRYPTO_API_SYMBOLS  = {
    "tron":       "TRX",
    "ton":        "TON",
    "usdt_bep20": "USDT",
    "usdc_bep20": "USDC",
    "ltc":        "LTC",
}
CRYPTO_COINS = [
    ("tron",       "🔵 Tron (TRC20)"),
    ("ton",        "💎 TON"),
    ("usdt_bep20", "🟢 USDT (BEP20)"),
    ("usdc_bep20", "🔵 USDC (BEP20)"),
    ("ltc",        "🪙 LTC"),
]

if not BOT_TOKEN or ":" not in BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN تنظیم نشده یا معتبر نیست.")
if not ADMIN_IDS:
    raise SystemExit("❌ ADMIN_IDS تنظیم نشده است.")
