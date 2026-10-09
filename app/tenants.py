"""Клиенты (арендаторы)."""
import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from . import audit, services
from .auth import admin_required, login_required
from .db import get_db
from .forms import check_email, check_phone, get_text, like
from .security import get_cipher, safe_decrypt, validate_inn

bp = Blueprint("tenants", __name__, url_prefix="/tenants")


def _get_tenant(tid):
    t = get_db().execute("SELECT * FROM tenants WHERE id = ?", (tid,)).fetchone()
    if t is None:
        abort(404)
    return t


def _read_form(form, errors):
    data = {
        "name": get_text(form, "name", errors, "Название", True, 200),
        "contact_person": get_text(form, "contact_person", errors, "Контактное лицо", False, 120),
        "phone": get_text(form, "phone", errors, "Телефон", False, 40),
        "email": get_text(form, "email", errors, "Email", False, 120),
        "note": get_text(form, "note", errors, "Примечание", False, 1000),
        "inn": re.sub(r"\s", "", form.get("inn", "")),
    }
    check_email(data["email"], errors)
    check_phone(data["phone"], errors)
    if not validate_inn(data["inn"]):
        errors["inn"] = "ИНН указан неверно (10 цифр для организации или 12 для ИП, с проверкой контрольной суммы)."
    return data


@bp.route("/")
@login_required
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    only_debt = request.args.get("debt") == "1"
    contracts, _ = services.contracts_with_summaries(db)
    debt, active = {}, {}
    for c in contracts:
        debt[c["tenant_id"]] = debt.get(c["tenant_id"], 0) + c["summary"]["debt"]
        if c["state"] == "active":
            active[c["tenant_id"]] = active.get(c["tenant_id"], 0) + 1
    rows = []
    for t in db.execute("SELECT * FROM tenants ORDER BY name COLLATE NOCASE").fetchall():
        if q and not like([t["name"], t["contact_person"], t["phone"], t["email"]], q):
            continue
        d = debt.get(t["id"], 0)
        if only_debt and d <= 0:
            continue
        rows.append({"t": t, "debt": d, "active": active.get(t["id"], 0)})
    return render_template("tenants_list.html", rows=rows, q=q, only_debt=only_debt)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    errors, form = {}, {}
    if request.method == "POST":
        db = get_db()
        form = _read_form(request.form, errors)
        cipher = get_cipher()
        if "inn" not in errors and db.execute(
                "SELECT 1 FROM tenants WHERE inn_hash = ?", (cipher.blind_index(form["inn"]),)
        ).fetchone():
            errors["inn"] = "Клиент с таким ИНН уже существует."
        if not errors:
            cur = db.execute(
                "INSERT INTO tenants (name, contact_person, phone, email, inn_encrypted, "
                "inn_hash, note, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (form["name"], form["contact_person"], form["phone"], form["email"],
                 cipher.encrypt(form["inn"]), cipher.blind_index(form["inn"]),
                 form["note"], services.now_str()))
            audit.log(db, "create", "tenant", cur.lastrowid, form["name"])
            db.commit()
            flash("Клиент добавлен.", "success")
            return redirect(url_for("tenants.detail", tid=cur.lastrowid))
    return render_template("tenant_form.html", form=form, errors=errors, tenant=None)


@bp.route("/<int:tid>")
@login_required
def detail(tid):
    t = _get_tenant(tid)
    contracts, _ = services.contracts_with_summaries(get_db())
    mine = [c for c in contracts if c["tenant_id"] == tid]
    return render_template("tenant_detail.html", t=t, inn=safe_decrypt(t["inn_encrypted"]),
                           contracts=mine, debt=sum(c["summary"]["debt"] for c in mine))


@bp.route("/<int:tid>/edit", methods=["GET", "POST"])
@login_required
def edit(tid):
    t = _get_tenant(tid)
    errors = {}
    form = dict(t)
    form["inn"] = safe_decrypt(t["inn_encrypted"])
    if request.method == "POST":
        db = get_db()
        form = _read_form(request.form, errors)
        cipher = get_cipher()
        new_hash = cipher.blind_index(form["inn"])
        if "inn" not in errors and db.execute(
                "SELECT 1 FROM tenants WHERE inn_hash = ? AND id != ?", (new_hash, tid)
        ).fetchone():
            errors["inn"] = "Клиент с таким ИНН уже существует."
        if not errors:
            changed = [label for key, label in (
                ("name", "название"), ("contact_person", "контактное лицо"),
                ("phone", "телефон"), ("email", "email"), ("note", "примечание"))
                if (t[key] or "") != form[key]]
            if new_hash != t["inn_hash"]:
                changed.append("ИНН")
            db.execute(
                "UPDATE tenants SET name=?, contact_person=?, phone=?, email=?, "
                "inn_encrypted=?, inn_hash=?, note=? WHERE id=?",
                (form["name"], form["contact_person"], form["phone"], form["email"],
                 cipher.encrypt(form["inn"]), new_hash, form["note"], tid))
            audit.log(db, "update", "tenant", tid, "изменено: " + (", ".join(changed) or "ничего"))
            db.commit()
            flash("Изменения сохранены.", "success")
            return redirect(url_for("tenants.detail", tid=tid))
    return render_template("tenant_form.html", form=form, errors=errors, tenant=t)


@bp.route("/<int:tid>/delete", methods=["POST"])
@admin_required
def delete(tid):
    t = _get_tenant(tid)
    db = get_db()
    if db.execute("SELECT 1 FROM contracts WHERE tenant_id = ?", (tid,)).fetchone():
        flash("Нельзя удалить клиента, у которого есть договоры.", "error")
        return redirect(url_for("tenants.detail", tid=tid))
    db.execute("DELETE FROM tenants WHERE id = ?", (tid,))
    audit.log(db, "delete", "tenant", tid, t["name"])
    db.commit()
    flash("Клиент удалён.", "success")
    return redirect(url_for("tenants.index"))
