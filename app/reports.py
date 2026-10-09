"""Главная панель и отчёты."""
from datetime import timedelta

from flask import Blueprint, render_template, request

from . import audit, exports, services
from .auth import login_required
from .config import EXPIRY_WARN_DAYS
from .db import get_db
from .services import ym_of

bp = Blueprint("reports", __name__)


@bp.route("/")
@login_required
def dashboard():
    db = get_db()
    today = services.today()
    cur = ym_of(today)
    contracts, data = services.contracts_with_summaries(db)
    month = services.month_rows(db, cur, precomputed=(contracts, data))

    pr = db.execute("SELECT COUNT(*) n, COALESCE(SUM(area),0) a FROM premises").fetchone()
    rented = db.execute("SELECT COUNT(*) n, COALESCE(SUM(area),0) a FROM premises "
                        "WHERE status='rented'").fetchone()
    repair = db.execute("SELECT COUNT(*) FROM premises WHERE status='repair'").fetchone()[0]
    limit = (today + timedelta(days=EXPIRY_WARN_DAYS)).isoformat()
    debtors = {}
    for c in contracts:
        if c["summary"]["debt"] > 0:
            d = debtors.setdefault(c["tenant_id"], {"name": c["tenant_name"], "debt": 0,
                                                    "tenant_id": c["tenant_id"]})
            d["debt"] += c["summary"]["debt"]
    top_debtors = sorted(debtors.values(), key=lambda d: -d["debt"])
    stats = {
        "premises_total": pr["n"], "premises_rented": rented["n"], "premises_repair": repair,
        "occupancy_area": round(rented["a"] / pr["a"] * 100) if pr["a"] else 0,
        "month_expected": sum(r["rent"] for r in month),
        "month_received": sum(r["paid"] for r in month),
        "month_left": sum(r["left"] for r in month),
        "debtors": len(debtors), "debt_total": sum(d["debt"] for d in debtors.values()),
    }
    ending = sorted([c for c in contracts if c["state"] == "active" and c["end_date"] <= limit],
                    key=lambda c: c["end_date"])
    expired = [c for c in contracts if c["state"] == "expired"]
    return render_template("dashboard.html", stats=stats, month=cur, top=top_debtors[:5],
                           ending=ending, expired=expired)


def _debtor_rows(db):
    contracts, _ = services.contracts_with_summaries(db)
    rows = []
    for c in contracts:
        s = c["summary"]
        if s["debt"] > 0:
            late = sum(1 for m in s["months"] if m["status"] in ("unpaid", "partial"))
            rows.append({"tenant": c["tenant_name"], "number": c["number"],
                         "premises": c["premises_number"], "rent": c["current_rent"],
                         "accrued": s["accrued"], "paid": s["paid"], "debt": s["debt"],
                         "late": late, "contract_id": c["id"], "tenant_id": c["tenant_id"]})
    rows.sort(key=lambda r: -r["debt"])
    return rows


@bp.route("/reports/debtors")
@login_required
def debtors():
    db = get_db()
    rows = _debtor_rows(db)
    if request.args.get("format") == "xlsx":
        audit.log(db, "export", "report", None, "должники")
        db.commit()
        return exports.xlsx_response(
            "Отчет по задолженностям", "Должники",
            ["Клиент", "Договор", "Помещение", "Ставка, ₽", "Начислено, ₽", "Оплачено, ₽",
             "Долг, ₽", "Месяцев с неполной оплатой"],
            [[r["tenant"], r["number"], r["premises"], r["rent"], r["accrued"], r["paid"],
              r["debt"], r["late"]] for r in rows],
            money_cols=(3, 4, 5, 6),
            total_row=["ИТОГО", "", "", "", sum(r["accrued"] for r in rows),
                       sum(r["paid"] for r in rows), sum(r["debt"] for r in rows), ""])
    return render_template("report_debtors.html", rows=rows,
                           total=sum(r["debt"] for r in rows))
