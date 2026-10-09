"""Оплаты по месяцам."""
from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   url_for)

from . import audit, exports, services
from .auth import admin_required, login_required
from .db import get_db
from .forms import get_text
from .services import fmt_date, fmt_money, fmt_month, parse_date, parse_money, parse_month, ym_of
from urllib.parse import urlparse

bp = Blueprint("payments", __name__, url_prefix="/payments")
STATUS_RU = {"paid": "Оплачено", "partial": "Частично", "unpaid": "Не оплачено",
             "future": "Не наступил"}


def _safe_back(target, default):
    if target:
        p = urlparse(target)
        if not p.scheme and not p.netloc and target.startswith("/") and not target.startswith("//"):
            return target
    return default


@bp.route("/")
@login_required
def month_view():
    db = get_db()
    cur = ym_of(services.today())
    month = parse_month(request.args.get("month")) or cur
    only_unpaid = request.args.get("filter") == "unpaid"
    rows = services.month_rows(db, month)
    totals = {"rent": sum(r["rent"] for r in rows), "paid": sum(r["paid"] for r in rows),
              "left": sum(r["left"] for r in rows)}
    if only_unpaid:
        rows = [r for r in rows if r["status"] in ("unpaid", "partial")]
    return render_template("payments_month.html", rows=rows, totals=totals, month=month,
                           prev_month=services.add_months(month, -1),
                           next_month=services.add_months(month, 1), cur_month=cur,
                           only_unpaid=only_unpaid, status_ru=STATUS_RU)


@bp.route("/export")
@login_required
def export():
    month = parse_month(request.args.get("month")) or ym_of(services.today())
    rows = services.month_rows(get_db(), month)
    db = get_db()
    audit.log(db, "export", "report", None, f"оплаты за {fmt_month(month)}")
    db.commit()
    return exports.xlsx_response(
        f"Отчет о оплате_{month}", fmt_month(month),
        ["Договор", "Клиент", "Помещение", "Начислено, ₽", "Оплачено, ₽", "Остаток, ₽", "Статус"],
        [[r["number"], r["tenant_name"], r["premises_number"], r["rent"], r["paid"], r["left"],
          STATUS_RU[r["status"]]] for r in rows],
        money_cols=(3, 4, 5),
        total_row=["ИТОГО", "", "", sum(r["rent"] for r in rows), sum(r["paid"] for r in rows),
                   sum(r["left"] for r in rows), ""])


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    db = get_db()
    cur_ym = ym_of(services.today())
    errors = {}
    form = {"contract_id": request.args.get("contract_id", ""),
            "period": parse_month(request.args.get("period")) or cur_ym,
            "amount": "", "paid_at": services.today().isoformat(), "note": "",
            "next": request.args.get("next", "")}
    contracts, data = services.contracts_with_summaries(db)
    by_id = {c["id"]: c for c in contracts}
    if request.method == "GET":
        c = by_id.get(int(form["contract_id"])) if form["contract_id"].isdigit() else None
        if c and services.covers_month(c, form["period"]):
            left = max(services.rent_for_month(c, data, form["period"])
                       - data["paid"].get(c["id"], {}).get(form["period"], 0), 0)
            form["amount"] = services.money_input(left) if left else ""
    else:
        form = {"contract_id": request.form.get("contract_id", ""),
                "period": request.form.get("period", ""), "amount": request.form.get("amount", ""),
                "paid_at": request.form.get("paid_at", ""),
                "note": get_text(request.form, "note", errors, "Примечание", False, 300),
                "next": request.form.get("next", "")}
        c = by_id.get(int(form["contract_id"])) if form["contract_id"].isdigit() else None
        if not c:
            errors["contract_id"] = "Выберите договор."
        period = parse_month(form["period"])
        if not period:
            errors["period"] = "Укажите месяц, за который вносится оплата."
        elif c and not services.covers_month(c, period):
            errors["period"] = "Этот месяц не входит в срок действия договора."
        elif period > cur_ym:
            errors["period"] = "Нельзя вносить оплату за будущий месяц."
        amount = parse_money(form["amount"])
        if amount is None or not 0 < amount <= services.MAX_RENT_KOP:
            errors["amount"] = "Укажите сумму (число больше нуля)."
        paid_at = parse_date(form["paid_at"])
        if not paid_at:
            errors["paid_at"] = "Укажите дату оплаты."
        elif paid_at > services.today():
            errors["paid_at"] = "Дата оплаты не может быть в будущем."
        if not errors:
            cur = db.execute(
                "INSERT INTO payments (contract_id, period, amount, paid_at, note, created_by, "
                "created_at) VALUES (?,?,?,?,?,?,?)",
                (c["id"], period, amount, paid_at.isoformat(), form["note"], g.user["id"],
                 services.now_str()))
            audit.log(db, "payment_add", "payment", cur.lastrowid,
                      f"{c['number']}: {fmt_money(amount)} за {fmt_month(period)}")
            db.commit()
            flash(f"Оплата {fmt_money(amount)} за {fmt_month(period)} записана.", "success")
            return redirect(_safe_back(form["next"],
                                       url_for("payments.month_view", month=period)))
    return render_template("payment_form.html", form=form, errors=errors, contracts=contracts)


@bp.route("/<int:pid>/delete", methods=["POST"])
@admin_required
def delete(pid):
    db = get_db()
    p = db.execute("SELECT p.*, c.number FROM payments p JOIN contracts c ON c.id = p.contract_id "
                   "WHERE p.id = ?", (pid,)).fetchone()
    if p is None:
        abort(404)
    db.execute("DELETE FROM payments WHERE id = ?", (pid,))
    audit.log(db, "payment_delete", "payment", pid,
              f"{p['number']}: {fmt_money(p['amount'])} за {fmt_month(p['period'])} "
              f"от {fmt_date(p['paid_at'])}")
    db.commit()
    flash("Платёж удалён.", "success")
    return redirect(url_for("contracts.detail", cid=p["contract_id"]))
