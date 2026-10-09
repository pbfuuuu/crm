"""Управление пользователями (только администратор)."""
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from . import audit
from .auth import admin_required
from .db import get_db
from .forms import get_text
from .security import generate_password
from .services import now_str

bp = Blueprint("users", __name__, url_prefix="/users")
ROLES = {"admin": "Администратор", "manager": "Менеджер"}


def _get_user(uid):
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if user is None:
        abort(404)
    return user


@bp.route("/")
@admin_required
def index():
    users = get_db().execute("SELECT * FROM users ORDER BY is_active DESC, username").fetchall()
    return render_template("users_list.html", users=users, roles=ROLES)


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    errors, form = {}, {"username": "", "full_name": "", "role": "manager"}
    if request.method == "POST":
        db = get_db()
        form["username"] = request.form.get("username", "").strip().lower()
        form["full_name"] = get_text(request.form, "full_name", errors, "ФИО", True, 100)
        form["role"] = request.form.get("role", "")
        if not re.fullmatch(r"[a-z0-9_.-]{3,30}", form["username"]):
            errors["username"] = "Логин: 3–30 символов, латиница, цифры и знаки _ . -"
        elif db.execute("SELECT 1 FROM users WHERE username = ?", (form["username"],)).fetchone():
            errors["username"] = "Такой логин уже существует."
        if form["role"] not in ROLES:
            errors["role"] = "Выберите роль."
        if not errors:
            password = generate_password()
            cur = db.execute(
                "INSERT INTO users (username, full_name, password_hash, role, "
                "must_change_password, created_at) VALUES (?,?,?,?,1,?)",
                (form["username"], form["full_name"], generate_password_hash(password),
                 form["role"], now_str()))
            audit.log(db, "create", "user", cur.lastrowid,
                      f"логин {form['username']}, роль {form['role']}")
            db.commit()
            return render_template("user_password.html", title="Пользователь создан",
                                   username=form["username"], password=password)
    return render_template("user_form.html", form=form, errors=errors, roles=ROLES)


@bp.route("/<int:uid>/reset", methods=["POST"])
@admin_required
def reset(uid):
    user = _get_user(uid)
    password = generate_password()
    db = get_db()
    db.execute("UPDATE users SET password_hash = ?, must_change_password = 1, "
               "failed_attempts = 0, locked_until = NULL WHERE id = ?",
               (generate_password_hash(password), uid))
    audit.log(db, "password_reset", "user", uid)
    db.commit()
    return render_template("user_password.html", title="Пароль сброшен",
                           username=user["username"], password=password)


@bp.route("/<int:uid>/toggle", methods=["POST"])
@admin_required
def toggle(uid):
    user = _get_user(uid)
    if user["id"] == g.user["id"]:
        flash("Нельзя заблокировать собственную учётную запись.", "error")
        return redirect(url_for("users.index"))
    new_state = 0 if user["is_active"] else 1
    db = get_db()
    db.execute("UPDATE users SET is_active = ?, failed_attempts = 0, locked_until = NULL "
               "WHERE id = ?", (new_state, uid))
    audit.log(db, "activate" if new_state else "deactivate", "user", uid)
    db.commit()
    flash("Пользователь разблокирован." if new_state else "Пользователь заблокирован.", "success")
    return redirect(url_for("users.index"))
