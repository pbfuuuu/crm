"""Помещения."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from . import audit, services
from .auth import admin_required, login_required
from .db import get_db
from .forms import get_text, like

bp = Blueprint("premises", __name__, url_prefix="/premises")
STATUSES = {"free": "Свободно", "rented": "Занято", "repair": "На ремонте"}


def _get_premises(pid):
    p = get_db().execute("SELECT * FROM premises WHERE id = ?", (pid,)).fetchone()
    if p is None:
        abort(404)
    return p


def _active_contract(db, pid):
    return db.execute(
        "SELECT c.*, t.name AS tenant_name FROM contracts c JOIN tenants t ON t.id = c.tenant_id "
        "WHERE c.premises_id = ? AND c.is_active = 1 ORDER BY c.start_date DESC", (pid,)
    ).fetchone()


def _read_form(form, errors, locked_rented):
    data = {"number": get_text(form, "number", errors, "Номер", True, 30),
            "note": get_text(form, "note", errors, "Примечание", False, 500),
            "floor": form.get("floor", "").strip(), "area": form.get("area", "").strip(),
            "status": "rented" if locked_rented else form.get("status", "free")}
    try:
        data["floor"] = int(data["floor"])
        if not -5 <= data["floor"] <= 200:
            raise ValueError
    except ValueError:
        errors["floor"] = "Этаж — целое число от -5 до 200."
    try:
        data["area"] = float(str(data["area"]).replace(",", "."))
        if not 0 < data["area"] <= 100000:
            raise ValueError
    except ValueError:
        errors["area"] = "Площадь — число больше нуля (кв. м)."
    if data["status"] not in STATUSES or (data["status"] == "rented" and not locked_rented):
        errors["status"] = "Выберите статус «Свободно» или «На ремонте»."
    return data


@bp.route("/")
@login_required
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    floor = request.args.get("floor", "")
    contracts = {c["premises_id"]: c for c in db.execute(
        "SELECT c.premises_id, t.name AS tenant_name, c.end_date FROM contracts c "
        "JOIN tenants t ON t.id = c.tenant_id WHERE c.is_active = 1").fetchall()}
    rows = []
    for p in db.execute("SELECT * FROM premises ORDER BY floor, number").fetchall():
        if status in STATUSES and p["status"] != status:
            continue
        if floor.lstrip("-").isdigit() and p["floor"] != int(floor):
            continue
        c = contracts.get(p["id"])
        if q and not like([p["number"], c["tenant_name"] if c else ""], q):
            continue
        rows.append({"p": p, "contract": c})
    floors = [r[0] for r in db.execute("SELECT DISTINCT floor FROM premises ORDER BY floor")]
    return render_template("premises_list.html", rows=rows, q=q, status=status, floor=floor,
                           statuses=STATUSES, floors=floors,
                           total_area=sum(r["p"]["area"] for r in rows))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    errors, form = {}, {"status": "free"}
    if request.method == "POST":
        db = get_db()
        form = _read_form(request.form, errors, False)
        if "number" not in errors and db.execute(
                "SELECT 1 FROM premises WHERE number = ?", (form["number"],)).fetchone():
            errors["number"] = "Помещение с таким номером уже существует."
        if not errors:
            cur = db.execute(
                "INSERT INTO premises (number, floor, area, status, note) VALUES (?,?,?,?,?)",
                (form["number"], form["floor"], form["area"], form["status"], form["note"]))
            audit.log(db, "create", "premises", cur.lastrowid, form["number"])
            db.commit()
            flash("Помещение добавлено.", "success")
            return redirect(url_for("premises.index"))
    return render_template("premises_form.html", form=form, errors=errors, premises=None,
                           statuses=STATUSES, locked=False)


@bp.route("/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def edit(pid):
    p = _get_premises(pid)
    db = get_db()
    locked = _active_contract(db, pid) is not None
    errors, form = {}, dict(p)
    if request.method == "POST":
        form = _read_form(request.form, errors, locked)
        if "number" not in errors and db.execute(
                "SELECT 1 FROM premises WHERE number = ? AND id != ?", (form["number"], pid)
        ).fetchone():
            errors["number"] = "Помещение с таким номером уже существует."
        if not errors:
            db.execute("UPDATE premises SET number=?, floor=?, area=?, status=?, note=? "
                       "WHERE id=?", (form["number"], form["floor"], form["area"],
                                      form["status"], form["note"], pid))
            audit.log(db, "update", "premises", pid, form["number"])
            db.commit()
            flash("Изменения сохранены.", "success")
            return redirect(url_for("premises.index"))
    return render_template("premises_form.html", form=form, errors=errors, premises=p,
                           statuses=STATUSES, locked=locked)


@bp.route("/<int:pid>/delete", methods=["POST"])
@admin_required
def delete(pid):
    p = _get_premises(pid)
    db = get_db()
    if db.execute("SELECT 1 FROM contracts WHERE premises_id = ?", (pid,)).fetchone():
        flash("Нельзя удалить помещение, по которому есть договоры.", "error")
        return redirect(url_for("premises.index"))
    db.execute("DELETE FROM premises WHERE id = ?", (pid,))
    audit.log(db, "delete", "premises", pid, p["number"])
    db.commit()
    flash("Помещение удалено.", "success")
    return redirect(url_for("premises.index"))
