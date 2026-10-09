"""Договоры аренды, история арендной платы, расторжение."""
from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import audit, services
from .auth import admin_required, login_required
from .config import EXPIRY_WARN_DAYS
from .db import get_db
from .forms import get_text, like
from .services import (fmt_date, fmt_money, load_calc_data, parse_date, parse_money,
                       parse_month, ym_of)

bp = Blueprint("contracts", __name__, url_prefix="/contracts")
STATE_FILTERS = {"active": "Действующие", "ending": "Скоро истекают",
                 "expired": "Истёк срок (не закрыты)", "closed": "Закрытые"}


def _get_contract(cid):
    c = get_db().execute(
        "SELECT c.*, t.name AS tenant_name, p.number AS premises_number, "
        "p.floor AS floor, p.area AS area FROM contracts c "
        "JOIN tenants t ON t.id = c.tenant_id JOIN premises p ON p.id = c.premises_id "
        "WHERE c.id = ?", (cid,)).fetchone()
    if c is None:
        abort(404)
    return c


@bp.route("/")
@login_required
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    flt = request.args.get("state", "")
    limit = (services.today() + timedelta(days=EXPIRY_WARN_DAYS)).isoformat()
    contracts, _ = services.contracts_with_summaries(db)
    rows = []
    for c in contracts:
        if q and not like([c["number"], c["tenant_name"], c["premises_number"]], q):
            continue
        if flt == "ending" and not (c["state"] == "active" and c["end_date"] <= limit):
            continue
        if flt in ("active", "expired", "closed") and c["state"] != flt:
            continue
        rows.append(c)
    return render_template("contracts_list.html", rows=rows, q=q, flt=flt, filters=STATE_FILTERS)


def _read_new_form(form, errors, db):
    data = {"number": get_text(form, "number", errors, "Номер договора", True, 40),
            "tenant_id": form.get("tenant_id", ""), "premises_id": form.get("premises_id", ""),
            "start_date": form.get("start_date", ""), "end_date": form.get("end_date", ""),
            "monthly_rent": form.get("monthly_rent", "")}
    tenant = db.execute("SELECT id FROM tenants WHERE id = ?",
                        (data["tenant_id"] or 0,)).fetchone()
    if not tenant:
        errors["tenant_id"] = "Выберите клиента."
    premises = db.execute("SELECT * FROM premises WHERE id = ?",
                          (data["premises_id"] or 0,)).fetchone()
    if not premises:
        errors["premises_id"] = "Выберите помещение."
    elif premises["status"] != "free":
        errors["premises_id"] = "Помещение недоступно для аренды (не «Свободно»)."
    start, end = parse_date(data["start_date"]), parse_date(data["end_date"])
    if not start:
        errors["start_date"] = "Укажите дату начала."
    if not end:
        errors["end_date"] = "Укажите дату окончания."
    if start and end:
        if end < start:
            errors["end_date"] = "Дата окончания не может быть раньше даты начала."
        elif (end - start).days > 365 * 50:
            errors["end_date"] = "Срок договора слишком большой."
    rent = parse_money(data["monthly_rent"])
    if rent is None or not 0 < rent <= services.MAX_RENT_KOP:
        errors["monthly_rent"] = "Укажите арендную плату (число больше нуля)."
    data["rent_kop"] = rent
    if "number" not in errors and db.execute(
            "SELECT 1 FROM contracts WHERE number = ?", (data["number"],)).fetchone():
        errors["number"] = "Договор с таким номером уже существует."
    if premises and start and end and "premises_id" not in errors:
        for o in db.execute("SELECT start_date, end_date FROM contracts "
                            "WHERE premises_id = ? AND is_active = 1", (premises["id"],)):
            if services.ranges_overlap(start.isoformat(), end.isoformat(),
                                       o["start_date"], o["end_date"]):
                errors["premises_id"] = "На это помещение уже есть действующий договор в указанный период."
                break
    return data


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    db = get_db()
    errors = {}
    form = {"tenant_id": request.args.get("tenant_id", ""),
            "premises_id": request.args.get("premises_id", "")}
    if request.method == "POST":
        form = _read_new_form(request.form, errors, db)
        if not errors:
            cur = db.execute(
                "INSERT INTO contracts (number, tenant_id, premises_id, start_date, end_date, "
                "monthly_rent, is_active, created_at) VALUES (?,?,?,?,?,?,1,?)",
                (form["number"], form["tenant_id"], form["premises_id"], form["start_date"],
                 form["end_date"], form["rent_kop"], services.now_str()))
            db.execute("UPDATE premises SET status = 'rented' WHERE id = ?", (form["premises_id"],))
            audit.log(db, "create", "contract", cur.lastrowid,
                      f"№ {form['number']}, ставка {fmt_money(form['rent_kop'])}")
            db.commit()
            flash("Договор оформлен, помещение помечено как занятое.", "success")
            return redirect(url_for("contracts.detail", cid=cur.lastrowid))
    tenants = db.execute("SELECT id, name FROM tenants ORDER BY name COLLATE NOCASE").fetchall()
    free = db.execute("SELECT id, number, floor, area FROM premises WHERE status = 'free' "
                      "ORDER BY floor, number").fetchall()
    return render_template("contract_form.html", form=form, errors=errors,
                           tenants=tenants, free=free)


@bp.route("/<int:cid>")
@login_required
def detail(cid):
    db = get_db()
    c = _get_contract(cid)
    data = load_calc_data(db)
    summary = services.contract_summary(c, data)
    changes = db.execute("SELECT r.*, u.full_name AS author FROM rent_changes r "
                         "LEFT JOIN users u ON u.id = r.created_by WHERE r.contract_id = ? "
                         "ORDER BY r.valid_from", (cid,)).fetchall()
    payments = db.execute("SELECT p.*, u.full_name AS author FROM payments p "
                          "LEFT JOIN users u ON u.id = p.created_by WHERE p.contract_id = ? "
                          "ORDER BY p.paid_at DESC, p.id DESC", (cid,)).fetchall()
    return render_template("contract_detail.html", c=c, summary=summary, changes=changes,
                           payments=payments, state=services.contract_state(c),
                           cur_rent=services.rent_in(c["monthly_rent"], data["changes"].get(cid, []),
                                                     ym_of(services.today())),
                           today=services.today().isoformat())


@bp.route("/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def edit(cid):
    c = _get_contract(cid)
    if not c["is_active"]:
        flash("Закрытый договор изменять нельзя.", "error")
        return redirect(url_for("contracts.detail", cid=cid))
    errors, form = {}, {"number": c["number"], "end_date": c["end_date"]}
    if request.method == "POST":
        db = get_db()
        form["number"] = get_text(request.form, "number", errors, "Номер договора", True, 40)
        form["end_date"] = request.form.get("end_date", "")
        end = parse_date(form["end_date"])
        if not end:
            errors["end_date"] = "Укажите дату окончания."
        elif end.isoformat() < c["start_date"]:
            errors["end_date"] = "Дата окончания не может быть раньше даты начала."
        if "number" not in errors and db.execute(
                "SELECT 1 FROM contracts WHERE number = ? AND id != ?", (form["number"], cid)
        ).fetchone():
            errors["number"] = "Договор с таким номером уже существует."
        if not errors:
            db.execute("UPDATE contracts SET number = ?, end_date = ? WHERE id = ?",
                       (form["number"], form["end_date"], cid))
            audit.log(db, "update", "contract", cid,
                      f"№ {form['number']}, окончание {fmt_date(form['end_date'])}")
            db.commit()
            flash("Изменения сохранены.", "success")
            return redirect(url_for("contracts.detail", cid=cid))
    return render_template("contract_edit.html", c=c, form=form, errors=errors)


@bp.route("/<int:cid>/rent", methods=["POST"])
@login_required
def add_rent_change(cid):
    c = _get_contract(cid)
    db = get_db()
    back = redirect(url_for("contracts.detail", cid=cid))
    if not c["is_active"]:
        flash("Для закрытого договора ставку менять нельзя.", "error")
        return back
    new_rent = parse_money(request.form.get("new_rent"))
    month = parse_month(request.form.get("valid_from"))
    if new_rent is None or not 0 < new_rent <= services.MAX_RENT_KOP:
        flash("Укажите новую арендную плату (число больше нуля).", "error")
    elif not month or not (c["start_date"][:7] <= month <= c["end_date"][:7]):
        flash("Месяц начала действия ставки должен попадать в срок договора.", "error")
    elif db.execute("SELECT 1 FROM rent_changes WHERE contract_id = ? AND valid_from = ?",
                    (cid, month)).fetchone():
        flash("На этот месяц ставка уже изменялась. Удалите прежнюю запись (администратор) "
              "или выберите другой месяц.", "error")
    else:
        cur = db.execute("INSERT INTO rent_changes (contract_id, new_rent, valid_from, "
                         "created_by, created_at) VALUES (?,?,?,?,?)",
                         (cid, new_rent, month, g.user["id"], services.now_str()))
        audit.log(db, "rent_change", "contract", cid,
                  f"№ {c['number']}: {fmt_money(new_rent)} с {services.fmt_month(month)}")
        db.commit()
        flash(f"Ставка {fmt_money(new_rent)} действует с {services.fmt_month(month)}. "
              "Ранее начисленные суммы не изменились.", "success")
    return back


@bp.route("/<int:cid>/rent/<int:rid>/delete", methods=["POST"])
@admin_required
def delete_rent_change(cid, rid):
    db = get_db()
    r = db.execute("SELECT * FROM rent_changes WHERE id = ? AND contract_id = ?",
                   (rid, cid)).fetchone()
    if r is None:
        abort(404)
    db.execute("DELETE FROM rent_changes WHERE id = ?", (rid,))
    audit.log(db, "delete", "rent_change", rid,
              f"договор {cid}: {fmt_money(r['new_rent'])} с {services.fmt_month(r['valid_from'])}")
    db.commit()
    flash("Изменение ставки удалено.", "success")
    return redirect(url_for("contracts.detail", cid=cid))


@bp.route("/<int:cid>/terminate", methods=["POST"])
@login_required
def terminate(cid):
    c = _get_contract(cid)
    db = get_db()
    d = parse_date(request.form.get("end_date"))
    if not c["is_active"]:
        flash("Договор уже закрыт.", "error")
    elif not d or not (c["start_date"] <= d.isoformat() <= c["end_date"]):
        flash("Дата расторжения должна лежать в пределах срока договора.", "error")
    else:
        db.execute("UPDATE contracts SET is_active = 0, end_date = ? WHERE id = ?",
                   (d.isoformat(), cid))
        db.execute("UPDATE premises SET status = 'free' WHERE id = ? AND status = 'rented'",
                   (c["premises_id"],))
        audit.log(db, "terminate", "contract", cid, f"№ {c['number']}, дата {fmt_date(d)}")
        db.commit()
        flash("Договор закрыт, помещение освобождено. Начисления идут до даты расторжения.",
              "success")
    return redirect(url_for("contracts.detail", cid=cid))


@bp.route("/<int:cid>/delete", methods=["POST"])
@admin_required
def delete(cid):
    c = _get_contract(cid)
    db = get_db()
    if db.execute("SELECT 1 FROM payments WHERE contract_id = ?", (cid,)).fetchone():
        flash("Нельзя удалить договор, по которому есть оплаты. Закройте его вместо удаления.",
              "error")
        return redirect(url_for("contracts.detail", cid=cid))
    db.execute("DELETE FROM contracts WHERE id = ?", (cid,))
    if c["is_active"]:
        db.execute("UPDATE premises SET status = 'free' WHERE id = ? AND status = 'rented'",
                   (c["premises_id"],))
    audit.log(db, "delete", "contract", cid, f"№ {c['number']}")
    db.commit()
    flash("Договор удалён.", "success")
    return redirect(url_for("contracts.index"))
