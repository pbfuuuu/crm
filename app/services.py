import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MAX_RENT_KOP = 100_000_000 * 100  # 100 млн руб. - защита от опечаток


def today() -> date:
    """Вынесено в функцию, чтобы в тестах можно было подменить текущую дату."""
    return date.today()


def now_str() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def parse_money(text):
    """'55 000,50' -> 5500050 (копейки). None, если не число."""
    s = (text or "").strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def fmt_money(kop) -> str:
    if kop is None:
        return "—"
    return f"{Decimal(kop) / 100:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def money_input(kop) -> str:
    """Значение для поля формы: 5500000 -> '55000.00'."""
    return f"{Decimal(kop) / 100:.2f}"


def parse_date(text):
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def parse_month(text):
    """Проверка формата, иначе None."""
    s = (text or "").strip()
    return s if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", s) else None


def ym_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def add_months(ym: str, n: int = 1) -> str:
    y, m = map(int, ym.split("-"))
    t = y * 12 + (m - 1) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def months_range(start_ym: str, end_ym: str):
    cur = start_ym
    while cur <= end_ym:
        yield cur
        cur = add_months(cur)


MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
             "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
              "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]


def fmt_date(value) -> str:
    if not value:
        return "—"
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return d.strftime("%d.%m.%Y")


def fmt_month(ym) -> str:
    if not ym:
        return "—"
    y, m = ym.split("-")
    return f"{MONTHS_NOM[int(m) - 1]} {y}"


def rent_in(base_rent, changes, period):
    rent = base_rent
    for valid_from, new_rent in changes:
        if valid_from <= period:
            rent = new_rent
        else:
            break
    return rent


def load_calc_data(db):
    changes, paid_by_period = {}, {}
    for r in db.execute("SELECT contract_id, valid_from, new_rent FROM rent_changes "
                        "ORDER BY valid_from"):
        changes.setdefault(r["contract_id"], []).append((r["valid_from"], r["new_rent"]))
    for r in db.execute("SELECT contract_id, period, SUM(amount) AS s FROM payments "
                        "GROUP BY contract_id, period"):
        paid_by_period.setdefault(r["contract_id"], {})[r["period"]] = r["s"]
    return {"changes": changes, "paid": paid_by_period}


def contract_summary(contract, data, on_date=None):
    """Сводка по договору: помесячная таблица, начислено, оплачено, долг."""
    on_date = on_date or today()
    cid = contract["id"]
    changes = data["changes"].get(cid, [])
    paid = data["paid"].get(cid, {})
    start = contract["start_date"][:7]
    end = min(contract["end_date"][:7], ym_of(on_date))
    months = []
    accrued = 0
    for ym in months_range(start, end):
        rent = rent_in(contract["monthly_rent"], changes, ym)
        got = paid.get(ym, 0)
        accrued += rent
        status = "paid" if got >= rent else ("partial" if got > 0 else "unpaid")
        months.append({"period": ym, "rent": rent, "paid": got,
                       "left": max(rent - got, 0), "status": status})
    paid_total = sum(paid.values())
    balance = accrued - paid_total
    return {"months": months, "accrued": accrued, "paid": paid_total,
            "debt": max(balance, 0), "overpaid": max(-balance, 0)}


def rent_for_month(contract, data, ym):
    return rent_in(contract["monthly_rent"], data["changes"].get(contract["id"], []), ym)


def covers_month(contract, ym) -> bool:
    return contract["start_date"][:7] <= ym <= contract["end_date"][:7]


def contract_state(contract, on_date=None):
    """active / expired (срок вышел, но не закрыт) / closed."""
    on_date = on_date or today()
    if not contract["is_active"]:
        return "closed"
    return "expired" if contract["end_date"] < on_date.isoformat() else "active"


def ranges_overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start <= b_end and b_start <= a_end


def contracts_with_summaries(db, on_date=None):
    """Все договоры; сводка по начислениям/оплатам + состояние. Список словарей."""
    on_date = on_date or today()
    data = load_calc_data(db)
    rows = db.execute(
        "SELECT c.*, t.name AS tenant_name, p.number AS premises_number, "
        "p.floor AS floor, p.area AS area "
        "FROM contracts c JOIN tenants t ON t.id = c.tenant_id "
        "JOIN premises p ON p.id = c.premises_id "
        "ORDER BY c.start_date DESC, c.id DESC").fetchall()
    result = []
    for r in rows:
        c = dict(r)
        c["summary"] = contract_summary(c, data, on_date)
        c["state"] = contract_state(c, on_date)
        c["current_rent"] = rent_in(c["monthly_rent"], data["changes"].get(c["id"], []),
                                    ym_of(on_date))
        result.append(c)
    return result, data


def month_rows(db, ym, on_date=None, precomputed=None):
    """Строки «оплаты за месяц»: по каждому договору, действующему в этом месяце."""
    on_date = on_date or today()
    contracts, data = precomputed or contracts_with_summaries(db, on_date)
    cur_ym = ym_of(on_date)
    rows = []
    for c in contracts:
        if not covers_month(c, ym):
            continue
        rent = rent_for_month(c, data, ym)
        paid = data["paid"].get(c["id"], {}).get(ym, 0)
        if ym > cur_ym:
            status = "future"
        else:
            status = "paid" if paid >= rent else ("partial" if paid > 0 else "unpaid")
        rows.append({"contract_id": c["id"], "number": c["number"], "tenant_id": c["tenant_id"],
                     "tenant_name": c["tenant_name"], "premises_number": c["premises_number"],
                     "rent": rent, "paid": paid,
                     "left": 0 if status == "future" else max(rent - paid, 0),
                     "status": status, "state": c["state"]})
    rows.sort(key=lambda r: (r["premises_number"], r["tenant_name"]))
    return rows
