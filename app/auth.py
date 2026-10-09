"""Аутентификация, смена пароля, декораторы доступа."""
import functools
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import audit, services
from .db import get_db
from .security import password_problem

bp = Blueprint("auth", __name__)


@bp.before_app_request
def load_user():
    g.user = None
    uid = session.get("user_id")
    if uid is not None:
        user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if user and user["is_active"]:
            g.user = user
        else:
            session.clear()


def login_required(view=None, *, allow_unchanged_password=False):
    """Требует вход. Если пароль временный - отправляет на его смену."""
    def decorator(func):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            if g.user["must_change_password"] and not allow_unchanged_password:
                return redirect(url_for("auth.change_password"))
            return func(*args, **kwargs)
        return wrapped
    return decorator(view) if view else decorator


def admin_required(view):
    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def _safe_next(target):
    if not target:
        return None
    p = urlparse(target)
    if p.scheme or p.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("reports.dashboard"))
    error = None
    if request.method == "POST":
        db = get_db()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        now = datetime.now()
        locked = bool(user and user["locked_until"]
                      and datetime.fromisoformat(user["locked_until"]) > now)
        if locked:
            error = "Учётная запись временно заблокирована из-за неудачных попыток входа."
            audit.log(db, "login_failed", "user", user["id"], "учётная запись заблокирована",
                      username=username)
        elif user and user["is_active"] and check_password_hash(user["password_hash"], password):
            db.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
                       (user["id"],))
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            g.user = user
            audit.log(db, "login", "user", user["id"])
            db.commit()
            return redirect(_safe_next(request.args.get("next")) or url_for("reports.dashboard"))
        else:
            error = "Неверный логин или пароль."
            if user:
                attempts = user["failed_attempts"] + 1
                locked_until = None
                if attempts >= current_app.config.get("MAX_FAILED_LOGINS", 5):
                    locked_until = (now + timedelta(
                        minutes=current_app.config.get("LOCK_MINUTES", 10))
                    ).isoformat(timespec="seconds")
                    attempts = 0
                db.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                           (attempts, locked_until, user["id"]))
            audit.log(db, "login_failed", "user", user["id"] if user else None,
                      None, username=username)
        db.commit()
    return render_template("login.html", error=error)


@bp.route("/logout", methods=["POST"])
@login_required(allow_unchanged_password=True)
def logout():
    db = get_db()
    audit.log(db, "logout", "user", g.user["id"])
    db.commit()
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required(allow_unchanged_password=True)
def change_password():
    errors = []
    if request.method == "POST":
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        repeat = request.form.get("repeat_password", "")
        if not check_password_hash(g.user["password_hash"], old):
            errors.append("Текущий пароль указан неверно.")
        problem = password_problem(new)
        if problem:
            errors.append(problem)
        if new != repeat:
            errors.append("Новый пароль и подтверждение не совпадают.")
        if new and new == old:
            errors.append("Новый пароль должен отличаться от текущего.")
        if not errors:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ?, must_change_password = 0 "
                       "WHERE id = ?", (generate_password_hash(new), g.user["id"]))
            audit.log(db, "password_change", "user", g.user["id"])
            db.commit()
            flash("Пароль изменён.", "success")
            return redirect(url_for("reports.dashboard"))
    return render_template("change_password.html", errors=errors)
