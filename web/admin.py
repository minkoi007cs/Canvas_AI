"""
Admin Blueprint — localhost only, password protected.
Accessible at http://localhost:8080/admin
"""
import os
import functools
from flask import (Blueprint, render_template, request, session,
                   redirect, url_for, jsonify, abort)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")


# ── Guards ─────────────────────────────────────────────────────────────────────

@admin_bp.before_request
def restrict_to_localhost():
    """Block requests unless ADMIN_ENABLED=true or running locally."""
    # In production (Railway), set ADMIN_ENABLED=true in env vars to unlock
    admin_enabled = os.getenv("ADMIN_ENABLED", "").lower() in ("true", "1", "yes")
    ip = request.remote_addr
    is_local = ip in ("127.0.0.1", "::1", "localhost")
    if not is_local and not admin_enabled:
        abort(403)


def admin_login_required(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authed"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return wrapped


# ── Auth ──────────────────────────────────────────────────────────────────────

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["admin_authed"] = True
            return redirect(url_for("admin.dashboard"))
        error = "Wrong password"
    return render_template("admin/login.html", error=error)


@admin_bp.route("/logout")
def logout():
    session.pop("admin_authed", None)
    return redirect(url_for("admin.login"))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route("/")
@admin_login_required
def dashboard():
    from storage.users import get_all_users, get_users_conn
    users = get_all_users()
    total      = len(users)
    linked     = sum(1 for u in users if u.get("canvas_linked"))
    admins     = sum(1 for u in users if u.get("is_admin"))
    banned     = sum(1 for u in users if u.get("is_banned"))
    syncing    = sum(1 for u in users if u.get("sync_status") == "syncing")
    return render_template("admin/dashboard.html",
        users=users, total=total, linked=linked,
        admins=admins, banned=banned, syncing=syncing)


# ── User actions ──────────────────────────────────────────────────────────────

@admin_bp.route("/users/<google_id>/toggle_admin", methods=["POST"])
@admin_login_required
def toggle_admin(google_id):
    from storage.users import get_user, set_admin
    user = get_user(google_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    new_val = not bool(user.get("is_admin"))
    set_admin(google_id, new_val)
    return jsonify({"success": True, "is_admin": new_val})


@admin_bp.route("/users/<google_id>/toggle_ban", methods=["POST"])
@admin_login_required
def toggle_ban(google_id):
    from storage.users import get_user, set_banned
    user = get_user(google_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    new_val = not bool(user.get("is_banned"))
    set_banned(google_id, new_val)
    return jsonify({"success": True, "is_banned": new_val})


@admin_bp.route("/users/<google_id>/resync", methods=["POST"])
@admin_login_required
def resync_user(google_id):
    from storage.users import get_user
    user = get_user(google_id)
    if not user or not user.get("canvas_linked"):
        return jsonify({"error": "User has no Canvas account linked"}), 400

    # Trigger sync in background thread
    import threading
    def _run():
        from web.app import _setup_user_context, _trigger_sync
        _setup_user_context(google_id)
        _trigger_sync(google_id)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "message": f"Sync started for {user.get('email')}"})


@admin_bp.route("/users/<google_id>/delete", methods=["POST"])
@admin_login_required
def delete_user_route(google_id):
    from storage.users import get_user, delete_user
    user = get_user(google_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Delete user data directory
    import shutil
    from storage.users import user_data_dir
    try:
        data_dir = user_data_dir(google_id)
        if data_dir.exists():
            shutil.rmtree(str(data_dir))
    except Exception as e:
        pass  # Best-effort

    delete_user(google_id)
    return jsonify({"success": True})


@admin_bp.route("/users/<google_id>/detail")
@admin_login_required
def user_detail(google_id):
    from storage.users import get_user, load_user_session
    user = get_user(google_id)
    if not user:
        abort(404)

    # Count canvas data if available
    canvas_stats = {}
    try:
        from storage.database import set_user_context, get_conn
        from config import set_user_paths
        set_user_context(google_id)
        set_user_paths(google_id)
        conn = get_conn()
        canvas_stats["courses"]     = conn.execute("SELECT COUNT(*) as n FROM courses WHERE google_id=?",     (google_id,)).fetchone()["n"]
        canvas_stats["assignments"] = conn.execute("SELECT COUNT(*) as n FROM assignments WHERE google_id=?", (google_id,)).fetchone()["n"]
        canvas_stats["files"]       = conn.execute("SELECT COUNT(*) as n FROM files WHERE google_id=?",       (google_id,)).fetchone()["n"]
        canvas_stats["pages"]       = conn.execute("SELECT COUNT(*) as n FROM pages WHERE google_id=?",       (google_id,)).fetchone()["n"]
        conn.close()
    except Exception:
        pass

    # Data dir size
    from storage.users import user_data_dir
    data_size = 0
    try:
        for f in user_data_dir(google_id).rglob("*"):
            if f.is_file():
                data_size += f.stat().st_size
    except Exception:
        pass
    data_size_mb = data_size / 1024 / 1024

    return render_template("admin/user_detail.html",
        user=user, canvas_stats=canvas_stats, data_size_mb=data_size_mb)


# ── Cleanup ─────────────────────────────────────────────────────────────────────

@admin_bp.route("/cleanup", methods=["GET", "POST"])
@admin_login_required
def cleanup():
    """Manually trigger data cleanup."""
    result = None
    if request.method == "POST":
        from tasks.cleanup import cleanup_all
        result = cleanup_all()
    return render_template("admin/cleanup.html", result=result)
