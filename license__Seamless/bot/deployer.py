# -*- coding: utf-8 -*-
"""
Bot Instance Deployer — Manages deployment of ConfigFlow & Seamless bot instances.

Each instance gets its own directory: /opt/license-bots/{project}_{bot_id}/
Repos are cached locally in /opt/license-bots/.repos/
"""
import os
import subprocess
import shutil
import logging
import threading

logger = logging.getLogger(__name__)

BASE_DIR = "/opt/license-bots"
REPOS_CACHE = os.path.join(BASE_DIR, ".repos")
CONFIGFLOW_REPO = "https://github.com/Emadhabibnia1385/ConfigFlow.git"
SEAMLESS_REPO = "https://github.com/gigiri33/PER.git"

_deploy_lock = threading.Lock()


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
    repo_url = SEAMLESS_REPO if project == "seamless" else CONFIGFLOW_REPO
    cache_dir = os.path.join(REPOS_CACHE, project)

    if os.path.isdir(os.path.join(cache_dir, ".git")):
        ok, out = _run("git fetch --all --prune && git reset --hard origin/main", cwd=cache_dir)
        if ok:
            return True, f"Repo {project} updated"
        return False, f"Failed to update repo: {out}"
    else:
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
        ok, out = _run(f"git clone --depth 1 {repo_url} {cache_dir}")
        if ok:
            return True, f"Repo {project} cloned"
        return False, f"Failed to clone repo: {out}"


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

            # 1. Ensure repo cache
            ok, msg = ensure_repo_cache(project)
            if not ok:
                return False, f"Repo cache failed: {msg}"

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


def update_instance(project, bot_token):
    """Update code from cached repo, keep .env and .db files."""
    idir = instance_dir(project, bot_token)
    svc = service_name(project, bot_token)

    if not os.path.isdir(idir):
        return False, "Instance not found"

    # Update cache first
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
    _run(f"{venv_dir}/bin/pip install -r requirements.txt -q", cwd=idir)

    # Restart
    _run(f"systemctl restart {svc}")

    return True, "Instance updated and restarted"


def update_all_instances():
    """Update all deployed instances."""
    results = []
    if not os.path.isdir(BASE_DIR):
        return results

    for name in os.listdir(BASE_DIR):
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

        # Find bot token from .env
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

        ok, msg = update_instance(project, token)
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
