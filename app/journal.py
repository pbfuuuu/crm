"""Просмотр журнала действий (только администратор)."""
from flask import Blueprint, render_template, request

from . import audit
from .auth import admin_required
from .db import get_db

bp = Blueprint("journal", __name__, url_prefix="/audit")


@bp.route("/")
@admin_required
def index():
    action = request.args.get("action", "")
    username = request.args.get("user", "").strip()
    where, params = [], []
    if action in audit.ACTIONS:
        where.append("action = ?")
        params.append(action)
    if username:
        where.append("username LIKE ?")
        params.append(f"%{username}%")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = get_db().execute(
        f"SELECT * FROM audit_log {clause} ORDER BY id DESC LIMIT 300", params).fetchall()
    return render_template("audit_list.html", rows=rows, actions=audit.ACTIONS,
                           objects=audit.OBJECTS, action=action, username=username)
