# -*- coding: utf-8 -*-
"""
Bot Instance Deployer — Manages deployment of ConfigFlow & Seamless bot instances.

Each instance gets its own directory: /opt/license-bots/{project}_{bot_id}/
Repos are cached locally in /opt/license-bots/.repos/
"""
import os
import sqlite3
import subprocess
import shutil
import logging
import threading

from .config import (
    DEPLOY_BASE_DIR,
    CONFIGFLOW_REPO_URL,
    SEAMLESS_REPO_URL,
    CONFIGFLOW_REPO_BRANCH,
    SEAMLESS_REPO_BRANCH,
)

logger = logging.getLogger(__name__)

BASE_DIR = DEPLOY_BASE_DIR
REPOS_CACHE = os.path.join(BASE_DIR, ".repos")
_REPO_META = {
    "configflow": {"url": CONFIGFLOW_REPO_URL, "branch": CONFIGFLOW_REPO_BRANCH},
    "seamless": {"url": SEAMLESS_REPO_URL, "branch": SEAMLESS_REPO_BRANCH},
}

_deploy_lock = threading.RLock()


def _run(cmd, cwd=None, timeout=300):
    """Run a shell command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def _ensure_dirs():
    os.makedirs(REPOS_CACHE, exist_ok=True)
    os.makedirs(BASE_DIR, exist_ok=True)


def _repo_info(project):
    project_key = (project or "").strip().lower()
    if project_key not in _REPO_META:
        raise ValueError(f"Unknown project: {project}")
    return _REPO_META[project_key]


def _bot_id_from_token(token):
    """Extract numeric bot ID from token like '123456789:ABC...'"""
    return token.split(":")[0]


def instance_dir(project, bot_token):
    """Return the directory path for a bot instance."""
    bot_id = _bot_id_from_token(bot_token)
    return os.path.join(BASE_DIR, f"{project}_{bot_id}")


def service_name(project, bot_token):
    """Return the systemd service name for a bot instance."""
    bot_id = _bot_id_from_token(bot_token)
    return f"licbot-{project}-{bot_id}"


# ── Repo Cache ────────────────────────────────────────────────────────────────

def update_repo_cache(project):
    """Clone or pull the latest repo into cache. Returns (success, message)."""
    _ensure_dirs()
    meta = _repo_info(project)
    repo_url = meta["url"]
    branch = meta["branch"]
    cache_dir = os.path.join(REPOS_CACHE, project)

    if os.path.isdir(os.path.join(cache_dir, ".git")):
        ok, out = _run(
            f"git fetch --depth 1 origin {branch} --prune && git checkout -B {branch} FETCH_HEAD && git reset --hard FETCH_HEAD",
            cwd=cache_dir
        )
        if ok:
            return True, f"Repo {project} updated to {branch}"
        return False, f"Failed to update repo: {out}"
    else:
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
        ok, out = _run(f"git clone --depth 1 --branch {branch} {repo_url} {cache_dir}")
        if ok:
            return True, f"Repo {project} cloned from {branch}"
        return False, f"Failed to clone repo: {out}"


def get_local_repo_revision(project):
    """Return the current cached repo commit hash for a project, if available."""
    cache_dir = os.path.join(REPOS_CACHE, project)
    if not os.path.isdir(os.path.join(cache_dir, ".git")):
        return ""
    ok, out = _run("git rev-parse HEAD", cwd=cache_dir, timeout=60)
    if not ok:
        return ""
    return (out or "").strip().splitlines()[0].strip()


def get_remote_repo_revision(project):
    """Return the latest remote commit hash for the configured branch."""
    _ensure_dirs()
    meta = _repo_info(project)
    ok, out = _run(
        f"git ls-remote {meta['url']} refs/heads/{meta['branch']}",
        cwd=BASE_DIR,
        timeout=60,
    )
    if not ok:
        return "", out
    line = next((ln.strip() for ln in (out or "").splitlines() if ln.strip()), "")
    if not line:
        return "", "No remote revision returned"
    revision = line.split()[0].strip()
    return revision, ""


def repo_has_updates(project):
    """Compare cached revision with GitHub and report whether an update exists."""
    local_rev = get_local_repo_revision(project)
    remote_rev, err = get_remote_repo_revision(project)
    if err:
        return False, local_rev, remote_rev, err
    has_update = (not local_rev) or (local_rev != remote_rev)
    return has_update, local_rev, remote_rev, ""

def ensure_repo_cache(project):
    """Make sure local cache exists, clone if needed."""
    cache_dir = os.path.join(REPOS_CACHE, project)
    if not os.path.isdir(os.path.join(cache_dir, ".git")):
        return update_repo_cache(project)
    return True, "Cache exists"


# ── Deploy ────────────────────────────────────────────────────────────────────

def deploy_instance(project, bot_token, admin_id, db_name="Seamless.db",
                    license_api_url="", bot_username=""):
    """
    Deploy a new bot instance.
    project: 'configflow' or 'seamless'
    Returns (success, message)
    """
    with _deploy_lock:
        try:
            _ensure_dirs()
            idir = instance_dir(project, bot_token)
            svc = service_name(project, bot_token)
            bot_id = _bot_id_from_token(bot_token)

            # 1. Always pull the latest GitHub code before each deployment
            ok, msg = update_repo_cache(project)
            if not ok:
                return False, f"Repo sync failed: {msg}"

            cache_dir = os.path.join(REPOS_CACHE, project)

            # 2. Copy files
            if os.path.exists(idir):
                # Preserve .env and .db if exists
                env_backup = None
                db_files = []
                env_path = os.path.join(idir, ".env")
                if os.path.isfile(env_path):
                    with open(env_path, "r") as f:
                        env_backup = f.read()
                for fname in os.listdir(idir):
                    if fname.endswith(".db"):
                        db_files.append(fname)

                # Remove code files, keep data
                for item in os.listdir(idir):
                    item_path = os.path.join(idir, item)
                    if item.endswith(".db") or item == ".env" or item == "venv":
                        continue
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)

                # Copy new code
                _copy_project_files(cache_dir, idir)

                # Restore .env
                if env_backup:
                    with open(env_path, "w") as f:
                        f.write(env_backup)
            else:
                os.makedirs(idir, exist_ok=True)
                _copy_project_files(cache_dir, idir)

            # 3. Write .env
            if project == "seamless":
                db_name = db_name or "Seamless.db"
            else:
                db_name = db_name or "ConfigFlow.db"

            env_content = f"BOT_TOKEN={bot_token}\nADMIN_IDS={admin_id}\nDB_NAME={db_name}\n"
            if project == "seamless" and license_api_url:
                env_content += f"LICENSE_API_URL={license_api_url}\n"

            with open(os.path.join(idir, ".env"), "w") as f:
                f.write(env_content)
            os.chmod(os.path.join(idir, ".env"), 0o600)

            # 4. Setup venv
            venv_dir = os.path.join(idir, "venv")
            if not os.path.isdir(venv_dir):
                ok, out = _run(f"python3 -m venv {venv_dir}")
                if not ok:
                    return False, f"venv creation failed: {out}"

            ok, out = _run(f"{venv_dir}/bin/pip install --upgrade pip wheel -q", cwd=idir)
            ok, out = _run(f"{venv_dir}/bin/pip install -r requirements.txt -q", cwd=idir)
            if not ok:
                return False, f"pip install failed: {out}"

            # 5. Create systemd service
            service_content = f"""[Unit]
Description=License Bot Instance — {project}_{bot_id} (@{bot_username})
After=network.target

[Service]
Type=simple
WorkingDirectory={idir}
EnvironmentFile={idir}/.env
ExecStart={idir}/venv/bin/python {idir}/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
            svc_path = f"/etc/systemd/system/{svc}.service"
            with open(svc_path, "w") as f:
                f.write(service_content)

            _run("systemctl daemon-reload")
            _run(f"systemctl enable {svc}")
            _run(f"systemctl restart {svc}")

            logger.info(f"Deployed {project}_{bot_id} at {idir}")
            return True, f"Instance deployed: {idir}"

        except Exception as e:
            logger.error(f"Deploy error: {e}")
            return False, str(e)


def _copy_project_files(src_dir, dst_dir):
    """Copy project files from cache to instance dir (skip .git, venv)."""
    for item in os.listdir(src_dir):
        if item in (".git", "venv", "__pycache__", ".env", "license__Seamless",
                     "install.sh", "README.md", "LICENSE"):
            continue
        s = os.path.join(src_dir, item)
        d = os.path.join(dst_dir, item)
        if os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d)
            shutil.copytree(s, d, ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "*.pyc", "venv"
            ))
        else:
            shutil.copy2(s, d)


# ── Instance Management ──────────────────────────────────────────────────────

def start_instance(project, bot_token):
    svc = service_name(project, bot_token)
    ok, out = _run(f"systemctl start {svc}")
    return ok, out


def stop_instance(project, bot_token):
    svc = service_name(project, bot_token)
    ok, out = _run(f"systemctl stop {svc}")
    return ok, out


def restart_instance(project, bot_token):
    svc = service_name(project, bot_token)
    ok, out = _run(f"systemctl restart {svc}")
    return ok, out


def instance_status(project, bot_token):
    """Returns 'active', 'inactive', 'failed', or 'not-found'."""
    svc = service_name(project, bot_token)
    ok, out = _run(f"systemctl is-active {svc}")
    return out.strip() if ok else out.strip()


def remove_instance(project, bot_token):
    """Stop service, remove service file, remove directory."""
    svc = service_name(project, bot_token)
    idir = instance_dir(project, bot_token)

    _run(f"systemctl stop {svc}")
    _run(f"systemctl disable {svc}")
    svc_path = f"/etc/systemd/system/{svc}.service"
    if os.path.isfile(svc_path):
        os.remove(svc_path)
    _run("systemctl daemon-reload")

    if os.path.isdir(idir):
        shutil.rmtree(idir)

    return True, f"Instance removed: {idir}"


def update_instance(project, bot_token, refresh_cache=True):
    """Update code from cached repo, keep .env and .db files."""
    with _deploy_lock:
        idir = instance_dir(project, bot_token)
        svc = service_name(project, bot_token)

        if not os.path.isdir(idir):
            return False, "Instance not found"

        if refresh_cache:
            ok, msg = update_repo_cache(project)
            if not ok:
                return False, f"Repo update failed: {msg}"

        cache_dir = os.path.join(REPOS_CACHE, project)

        # Preserve .env
        env_backup = None
        env_path = os.path.join(idir, ".env")
        if os.path.isfile(env_path):
            with open(env_path, "r") as f:
                env_backup = f.read()

        # Remove old code (keep venv, .db, .env)
        for item in os.listdir(idir):
            item_path = os.path.join(idir, item)
            if item.endswith(".db") or item == ".env" or item == "venv":
                continue
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)

        # Copy new code
        _copy_project_files(cache_dir, idir)

        # Restore .env
        if env_backup:
            with open(env_path, "w") as f:
                f.write(env_backup)

        # Reinstall deps
        venv_dir = os.path.join(idir, "venv")
        ok, out = _run(f"{venv_dir}/bin/pip install -r requirements.txt -q", cwd=idir)
        if not ok:
            return False, f"pip install failed: {out}"

        # Restart
        ok, out = _run(f"systemctl restart {svc}")
        if not ok:
            return False, f"restart failed: {out}"

        return True, "Instance updated and restarted"


def update_all_instances(project=None, refresh_cache=True):
    """Update all deployed instances, optionally filtered by project."""
    results = []
    if not os.path.isdir(BASE_DIR):
        return results

    project_filter = (project or "").strip().lower() or None
    repo_sync_status = {}

    if refresh_cache:
        target_projects = [project_filter] if project_filter else list(_REPO_META.keys())
        for proj in target_projects:
            if proj not in _REPO_META:
                repo_sync_status[proj] = (False, f"Unknown project: {proj}")
                continue
            repo_sync_status[proj] = update_repo_cache(proj)

    for name in os.listdir(BASE_DIR):
        if name.startswith("."):
            continue
        full = os.path.join(BASE_DIR, name)
        if not os.path.isdir(full):
            continue
        parts = name.split("_", 1)
        if len(parts) != 2:
            continue
        inst_project = parts[0].strip().lower()

        if project_filter and inst_project != project_filter:
            continue

        env_path = os.path.join(full, ".env")
        if not os.path.isfile(env_path):
            continue
        token = ""
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            continue

        if refresh_cache and inst_project in repo_sync_status and not repo_sync_status[inst_project][0]:
            ok, msg = repo_sync_status[inst_project]
            results.append((name, False, f"Skipped: {msg}"))
            continue

        ok, msg = update_instance(inst_project, token, refresh_cache=False)
        results.append((name, ok, msg))

    return results

def list_all_instances():
    """List all deployed instances with their status."""
    instances = []
    if not os.path.isdir(BASE_DIR):
        return instances

    for name in sorted(os.listdir(BASE_DIR)):
        if name.startswith("."):
            continue
        full = os.path.join(BASE_DIR, name)
        if not os.path.isdir(full):
            continue
        parts = name.split("_", 1)
        if len(parts) != 2:
            continue

        project = parts[0]
        bot_id = parts[1]

        # Read .env for token
        env_path = os.path.join(full, ".env")
        token = ""
        bot_username = ""
        if os.path.isfile(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith("BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip()

        status = instance_status(project, token) if token else "unknown"

        instances.append({
            "name": name,
            "project": project,
            "bot_id": bot_id,
            "bot_token": token,
            "dir": full,
            "status": status,
        })

    return instances


def restore_instance_db(project, bot_token, db_content_bytes, db_filename=None):
    """
    Safely restore a SQLite .db file for a deployed bot instance.
    It validates the uploaded backup first, keeps a timestamped backup of the
    current DB, and auto-rolls back if the service does not come back up.
    Returns (success, message).
    """
    idir = instance_dir(project, bot_token)
    svc = service_name(project, bot_token)

    if not os.path.isdir(idir):
        return False, "دایرکتوری نمونه پیدا نشد."

    if len(db_content_bytes) < 16 or db_content_bytes[:16] != b"SQLite format 3\x00":
        return False, "فایل ارسالی دیتابیس SQLite معتبر نیست."

    db_files = [f for f in os.listdir(idir) if f.endswith(".db")]
    target_name = db_files[0] if db_files else (db_filename or ("ConfigFlow.db" if project == "configflow" else "Seamless.db"))
    target_path = os.path.join(idir, target_name)
    tmp_path = target_path + ".tmp_restore"
    backup_path = None

    try:
        # 1) Save uploaded file to a temp path and validate it before touching the live DB
        with open(tmp_path, "wb") as f:
            f.write(db_content_bytes)

        test_conn = sqlite3.connect(tmp_path)
        try:
            row = test_conn.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                return False, "فایل بکاپ خراب است و integrity check را رد کرد."

            tables = {r[0] for r in test_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required_tables = {"users", "settings", "config_types", "packages", "configs"}
            if not required_tables.issubset(tables):
                return False, "این بکاپ مربوط به دیتابیس‌های اصلی ConfigFlow/Seamless نیست یا ناقص است."
        finally:
            test_conn.close()

        # 2) Stop the service and back up current DB
        _run(f"systemctl stop {svc}")
        import time as _time
        _time.sleep(1)

        if os.path.isfile(target_path):
            ts = int(_time.time())
            backup_path = target_path + f".bak_{ts}"
            shutil.copy2(target_path, backup_path)

        # Remove stale WAL/SHM files from the previous DB; otherwise SQLite may error after restore
        for sidecar in (target_path + "-wal", target_path + "-shm"):
            if os.path.exists(sidecar):
                os.remove(sidecar)

        # 3) Replace DB atomically
        os.replace(tmp_path, target_path)

        # 4) Restart and verify; rollback if needed so the bot won't stay down
        _run(f"systemctl start {svc}")
        st = ""
        for _ in range(5):
            st = instance_status(project, bot_token)
            if st == "active":
                break
            _time.sleep(1)
        if st != "active":
            if backup_path and os.path.isfile(backup_path):
                shutil.copy2(backup_path, target_path)
                _run(f"systemctl start {svc}")
            return False, "ری‌استور ناموفق بود؛ بکاپ قبلی برگردانده شد تا ربات قطع نشود."

        return True, f"دیتابیس {target_name} با موفقیت ری‌استور شد و سرویس فعال است."
    except Exception as e:
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        try:
            if backup_path and os.path.isfile(backup_path):
                shutil.copy2(backup_path, target_path)
            _run(f"systemctl start {svc}")
        except Exception:
            pass
        return False, f"خطا در ری‌استور: {str(e)}"
