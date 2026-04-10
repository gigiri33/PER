# -*- coding: utf-8 -*-
"""
Database layer for the Seamless License Management Bot.
"""
import sqlite3
import threading
import time
from .config import DB_NAME

_local = threading.local()


def get_conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id      INTEGER PRIMARY KEY,
        username     TEXT DEFAULT '',
        first_name   TEXT DEFAULT '',
        registered   REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS licenses (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        bot_token     TEXT NOT NULL,
        bot_username  TEXT DEFAULT '',
        admin_id      TEXT NOT NULL,
        support_user  TEXT DEFAULT '',
        plan          TEXT NOT NULL DEFAULT 'trial',
        status        TEXT NOT NULL DEFAULT 'active',
        created_at    REAL NOT NULL,
        expires_at    REAL NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    );

    CREATE TABLE IF NOT EXISTS payments (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        license_id    INTEGER,
        amount_usdt   REAL NOT NULL,
        plan          TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'pending',
        tx_id         TEXT DEFAULT '',
        created_at    REAL NOT NULL,
        confirmed_at  REAL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (license_id) REFERENCES licenses(id)
    );

    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS instances (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        license_id    INTEGER,
        user_id       INTEGER NOT NULL,
        project       TEXT NOT NULL,
        bot_token     TEXT NOT NULL,
        bot_id        TEXT NOT NULL,
        bot_username  TEXT DEFAULT '',
        admin_id      TEXT NOT NULL,
        instance_dir  TEXT DEFAULT '',
        service_name  TEXT DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'deploying',
        created_at    REAL NOT NULL,
        FOREIGN KEY (license_id) REFERENCES licenses(id),
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    );

    CREATE TABLE IF NOT EXISTS trial_usage (
        user_id      INTEGER NOT NULL,
        project_type TEXT NOT NULL,
        used_at      REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, project_type)
    );

    CREATE TABLE IF NOT EXISTS donate_payments (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        amount       REAL NOT NULL,
        currency     TEXT NOT NULL DEFAULT 'USDT',
        gateway      TEXT NOT NULL DEFAULT '',
        status       TEXT NOT NULL DEFAULT 'pending',
        invoice_id   TEXT DEFAULT '',
        created_at   REAL NOT NULL,
        confirmed_at REAL DEFAULT 0
    );
    """)
    # Add warning_sent column to licenses if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE licenses ADD COLUMN warning_sent INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except Exception:
        pass  # Column already exists

    # Discount codes and subscription orders tables
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS discount_codes (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        code       TEXT NOT NULL UNIQUE,
        percent    REAL NOT NULL DEFAULT 0,
        package    TEXT NOT NULL DEFAULT 'all',
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS subscription_orders (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        plan          TEXT NOT NULL,
        amount_usdt   REAL NOT NULL,
        amount_toman  INTEGER NOT NULL,
        final_usdt    REAL NOT NULL,
        final_toman   INTEGER NOT NULL,
        gateway       TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'pending',
        invoice_id    TEXT DEFAULT '',
        discount_code TEXT DEFAULT '',
        discount_pct  REAL DEFAULT 0,
        created_at    REAL NOT NULL,
        confirmed_at  REAL DEFAULT 0
    );
    """)
    conn.commit()


# ── Users ──────────────────────────────────────────────────────────────────────
def ensure_user(user_id, username="", first_name=""):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, registered) VALUES (?,?,?,?)",
        (user_id, username, first_name, time.time())
    )
    conn.execute(
        "UPDATE users SET username=?, first_name=? WHERE user_id=?",
        (username, first_name, user_id)
    )
    conn.commit()


def get_user(user_id):
    row = get_conn().execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_all_users():
    rows = get_conn().execute("SELECT * FROM users").fetchall()
    return [dict(r) for r in rows]


# ── Licenses ───────────────────────────────────────────────────────────────────
def create_license(user_id, bot_token, bot_username, admin_id, support_user, plan, duration_hours):
    conn = get_conn()
    now = time.time()
    expires = now + (duration_hours * 3600)
    cur = conn.execute(
        """INSERT INTO licenses (user_id, bot_token, bot_username, admin_id, support_user, plan, status, created_at, expires_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, bot_token, bot_username, admin_id, support_user, plan, "active", now, expires)
    )
    conn.commit()
    return cur.lastrowid


def get_license(license_id):
    row = get_conn().execute("SELECT * FROM licenses WHERE id=?", (license_id,)).fetchone()
    return dict(row) if row else None


def get_user_licenses(user_id):
    rows = get_conn().execute(
        "SELECT * FROM licenses WHERE user_id=? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_active_license_by_token(bot_token):
    row = get_conn().execute(
        "SELECT * FROM licenses WHERE bot_token=? AND status='active' ORDER BY expires_at DESC LIMIT 1",
        (bot_token,)
    ).fetchone()
    return dict(row) if row else None


def get_all_licenses():
    rows = get_conn().execute("SELECT * FROM licenses ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_license_status(license_id, status):
    conn = get_conn()
    conn.execute("UPDATE licenses SET status=? WHERE id=?", (status, license_id))
    conn.commit()


def extend_license(license_id, extra_hours):
    conn = get_conn()
    lic = get_license(license_id)
    if not lic:
        return False
    base = max(lic["expires_at"], time.time())
    new_expires = base + (extra_hours * 3600)
    conn.execute("UPDATE licenses SET expires_at=?, status='active' WHERE id=?", (new_expires, license_id))
    conn.commit()
    return True


def upgrade_license_plan(license_id, new_plan, extra_hours):
    conn = get_conn()
    lic = get_license(license_id)
    if not lic:
        return False
    base = max(lic["expires_at"], time.time())
    new_expires = base + (extra_hours * 3600)
    conn.execute(
        "UPDATE licenses SET plan=?, expires_at=?, status='active' WHERE id=?",
        (new_plan, new_expires, license_id)
    )
    conn.commit()
    return True


def get_expired_licenses():
    now = time.time()
    rows = get_conn().execute(
        "SELECT * FROM licenses WHERE status='active' AND expires_at < ?", (now,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Payments ───────────────────────────────────────────────────────────────────
def create_payment(user_id, amount_usdt, plan, license_id=None, tx_id=""):
    conn = get_conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO payments (user_id, license_id, amount_usdt, plan, status, tx_id, created_at) VALUES (?,?,?,?,?,?,?)",
        (user_id, license_id, amount_usdt, plan, "pending", tx_id, now)
    )
    conn.commit()
    return cur.lastrowid


def get_payment(payment_id):
    row = get_conn().execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    return dict(row) if row else None


def get_user_payments(user_id):
    rows = get_conn().execute(
        "SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def confirm_payment(payment_id, tx_id=""):
    conn = get_conn()
    conn.execute(
        "UPDATE payments SET status='confirmed', tx_id=?, confirmed_at=? WHERE id=?",
        (tx_id, time.time(), payment_id)
    )
    conn.commit()


def reject_payment(payment_id):
    conn = get_conn()
    conn.execute("UPDATE payments SET status='rejected' WHERE id=?", (payment_id,))
    conn.commit()


def get_pending_payments():
    rows = get_conn().execute(
        "SELECT * FROM payments WHERE status='pending' ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Settings ───────────────────────────────────────────────────────────────────
def setting_get(key, default=""):
    row = get_conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def setting_set(key, value):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))
    conn.commit()


# ── Stats ──────────────────────────────────────────────────────────────────────
def get_stats():
    conn = get_conn()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_licenses = conn.execute("SELECT COUNT(*) FROM licenses").fetchone()[0]
    active_licenses = conn.execute("SELECT COUNT(*) FROM licenses WHERE status='active'").fetchone()[0]
    trial_licenses = conn.execute("SELECT COUNT(*) FROM licenses WHERE plan='trial' AND status='active'").fetchone()[0]
    premium_licenses = conn.execute("SELECT COUNT(*) FROM licenses WHERE plan IN ('monthly','premium') AND status='active'").fetchone()[0]
    total_revenue = conn.execute("SELECT COALESCE(SUM(amount_usdt),0) FROM payments WHERE status='confirmed'").fetchone()[0]
    total_instances = conn.execute("SELECT COUNT(*) FROM instances").fetchone()[0]
    active_instances = conn.execute("SELECT COUNT(*) FROM instances WHERE status='running'").fetchone()[0]
    return {
        "total_users": total_users,
        "total_licenses": total_licenses,
        "active_licenses": active_licenses,
        "trial_licenses": trial_licenses,
        "premium_licenses": premium_licenses,
        "total_revenue": total_revenue,
        "total_instances": total_instances,
        "active_instances": active_instances,
    }


# ── Instances ──────────────────────────────────────────────────────────────────
def create_instance(license_id, user_id, project, bot_token, bot_id, bot_username,
                    admin_id, instance_dir, service_name):
    conn = get_conn()
    import time as _t
    cur = conn.execute(
        """INSERT INTO instances
           (license_id, user_id, project, bot_token, bot_id, bot_username,
            admin_id, instance_dir, service_name, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (license_id, user_id, project, bot_token, bot_id, bot_username,
         admin_id, instance_dir, service_name, "deploying", _t.time())
    )
    conn.commit()
    return cur.lastrowid


def update_instance_status(instance_id, status):
    conn = get_conn()
    conn.execute("UPDATE instances SET status=? WHERE id=?", (status, instance_id))
    conn.commit()


def get_instance(instance_id):
    row = get_conn().execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    return dict(row) if row else None


def get_instance_by_token(bot_token):
    row = get_conn().execute(
        "SELECT * FROM instances WHERE bot_token=? ORDER BY created_at DESC LIMIT 1",
        (bot_token,)
    ).fetchone()
    return dict(row) if row else None


def get_user_instances(user_id):
    rows = get_conn().execute(
        "SELECT * FROM instances WHERE user_id=? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_instances():
    rows = get_conn().execute("SELECT * FROM instances ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def delete_instance(instance_id):
    conn = get_conn()
    conn.execute("DELETE FROM instances WHERE id=?", (instance_id,))
    conn.commit()


# ── Trial Usage ────────────────────────────────────────────────────────────────
def has_used_trial(user_id, project_type):
    """Return True if user has ever used a trial for this project type."""
    row = get_conn().execute(
        "SELECT 1 FROM trial_usage WHERE user_id=? AND project_type=?",
        (user_id, project_type)
    ).fetchone()
    return row is not None


def mark_trial_used(user_id, project_type):
    """Mark that this user has consumed their trial for this project type."""
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO trial_usage (user_id, project_type, used_at) VALUES (?,?,?)",
        (user_id, project_type, time.time())
    )
    conn.commit()


# ── License Warnings ──────────────────────────────────────────────────────────
def get_licenses_expiring_soon(within_hours=24):
    """Return active licenses expiring within `within_hours` where warning not yet sent."""
    now = time.time()
    threshold = now + (within_hours * 3600)
    rows = get_conn().execute(
        "SELECT * FROM licenses WHERE status='active' AND expires_at <= ? AND expires_at > ? AND warning_sent=0",
        (threshold, now)
    ).fetchall()
    return [dict(r) for r in rows]


def set_warning_sent(license_id):
    conn = get_conn()
    conn.execute("UPDATE licenses SET warning_sent=1 WHERE id=?", (license_id,))
    conn.commit()


def get_all_active_licenses():
    rows = get_conn().execute(
        "SELECT * FROM licenses WHERE status='active' ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Donate Payments ───────────────────────────────────────────────────────────
def create_donate_payment(user_id, amount, currency="USDT", gateway=""):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO donate_payments (user_id, amount, currency, gateway, status, created_at) VALUES (?,?,?,?,?,?)",
        (user_id, amount, currency, gateway, "pending", time.time())
    )
    conn.commit()
    return cur.lastrowid


def get_donate_payment(donate_id):
    row = get_conn().execute("SELECT * FROM donate_payments WHERE id=?", (donate_id,)).fetchone()
    return dict(row) if row else None


def confirm_donate_payment(donate_id, invoice_id=""):
    conn = get_conn()
    conn.execute(
        "UPDATE donate_payments SET status='confirmed', invoice_id=?, confirmed_at=? WHERE id=?",
        (invoice_id, time.time(), donate_id)
    )
    conn.commit()


def cancel_donate_payment(donate_id):
    conn = get_conn()
    conn.execute("UPDATE donate_payments SET status='cancelled' WHERE id=?", (donate_id,))
    conn.commit()


# ── Discount Codes ────────────────────────────────────────────────────────────
def create_discount_code(code, percent, package="all"):
    conn = get_conn()
    cur = conn.execute(
        "INSERT OR IGNORE INTO discount_codes (code, percent, package, created_at) VALUES (?,?,?,?)",
        (code.strip().upper(), float(percent), package, time.time())
    )
    conn.commit()
    return cur.lastrowid


def get_discount_code_by_code(code):
    row = get_conn().execute(
        "SELECT * FROM discount_codes WHERE code=?", (code.strip().upper(),)
    ).fetchone()
    return dict(row) if row else None


def get_all_discount_codes():
    rows = get_conn().execute(
        "SELECT * FROM discount_codes ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_discount_code(code_id):
    conn = get_conn()
    conn.execute("DELETE FROM discount_codes WHERE id=?", (code_id,))
    conn.commit()


# ── Subscription Orders ───────────────────────────────────────────────────────
def create_subscription_order(user_id, plan, amount_usdt, amount_toman,
                               final_usdt, final_toman, gateway,
                               discount_code="", discount_pct=0):
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO subscription_orders
           (user_id, plan, amount_usdt, amount_toman, final_usdt, final_toman,
            gateway, status, discount_code, discount_pct, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, plan, amount_usdt, amount_toman, final_usdt, final_toman,
         gateway, "pending", discount_code, discount_pct, time.time())
    )
    conn.commit()
    return cur.lastrowid


def get_subscription_order(order_id):
    row = get_conn().execute(
        "SELECT * FROM subscription_orders WHERE id=?", (order_id,)
    ).fetchone()
    return dict(row) if row else None


def confirm_subscription_order(order_id, invoice_id=""):
    conn = get_conn()
    conn.execute(
        "UPDATE subscription_orders SET status='confirmed', invoice_id=?, confirmed_at=? WHERE id=?",
        (invoice_id, time.time(), order_id)
    )
    conn.commit()
