"""Демонстрационные данные (вымышленные организации) для показа и скриншотов."""
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from app import db as dbmod, services
from app.security import generate_password, get_cipher
from app.services import add_months, months_range, rent_in, ym_of


def make_inn10(base9: str) -> str:
    k = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    d = [int(c) for c in base9]
    return base9 + str(sum(a * b for a, b in zip(k, d)) % 11 % 10)


def make_inn12(base10: str) -> str:
    k1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    k2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    d = [int(c) for c in base10]
    n11 = sum(a * b for a, b in zip(k1, d)) % 11 % 10
    d.append(n11)
    n12 = sum(a * b for a, b in zip(k2, d)) % 11 % 10
    return base10 + str(n11) + str(n12)


def first_of(ym):
    y, m = map(int, ym.split("-"))
    return date(y, m, 1)


def last_of(ym):
    return first_of(add_months(ym, 1)) - timedelta(days=1)


def seed(app):
    with app.app_context():
        dbmod.init_db()
        db = dbmod.get_db()
        if db.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]:
            print("В базе уже есть данные — демо-данные не добавлены.")
            return
        cipher = get_cipher()
        today = services.today()
        cur = ym_of(today)
        now = services.now_str()

        creds = {}
        for username, name, role in (("admin", "Иванова Мария Сергеевна", "admin"),
                                     ("manager", "Петров Алексей Игоревич", "manager")):
            pwd = generate_password()
            creds[username] = pwd
            db.execute("INSERT INTO users (username, full_name, password_hash, role, "
                       "must_change_password, created_at) VALUES (?,?,?,?,1,?)",
                       (username, name, generate_password_hash(pwd), role, now))

        premises = {}
        for number, floor, area, status in [
                ("101", 1, 64.5, "free"), ("102", 1, 38.0, "free"), ("103", 1, 92.3, "free"),
                ("104", 1, 41.2, "free"), ("105", 1, 210.0, "free"), ("201", 2, 55.0, "free"),
                ("202", 2, 72.8, "free"), ("203", 2, 47.5, "free"), ("204", 2, 60.0, "repair"),
                ("205", 2, 33.4, "free"), ("301", 3, 58.0, "free"), ("302", 3, 44.0, "free"),
                ("303", 3, 120.0, "free")]:
            cur_ = db.execute("INSERT INTO premises (number, floor, area, status) VALUES (?,?,?,?)",
                              (number, floor, area, status))
            premises[number] = cur_.lastrowid

        tenant_specs = [
            ("ООО «Ромашка»", "Соколова Ирина", "+7 (343) 200-11-01", "sokolova@romashka.example", make_inn10("667100001")),
            ("ИП Смирнов А. В.", "Смирнов Андрей", "+7 (912) 345-67-89", "smirnov@example.org", make_inn12("6671000002")),
            ("ООО «Вектор»", "Крылов Денис", "+7 (343) 200-22-02", "info@vektor.example", make_inn10("667100003")),
            ("ИП Кузнецова Е. П.", "Кузнецова Елена", "+7 (922) 111-22-33", "kuznetsova@example.org", make_inn12("6671000004")),
            ("ООО «ТехноСервис»", "Мартынов Павел", "+7 (343) 200-33-03", "office@technoservice.example", make_inn10("667100005")),
            ("ООО «Альфа-Трейд»", "Орлов Сергей", "+7 (343) 200-44-04", "alfa@trade.example", make_inn10("667100006")),
            ("ИП Волков Д. С.", "Волков Дмитрий", "+7 (908) 777-88-99", "volkov@example.org", make_inn12("6671000007")),
            ("АО «Урал-Ритейл»", "Жукова Наталья", "+7 (343) 200-55-05", "zhukova@uralretail.example", make_inn10("667100008")),
            ("ИП Орлова Н. М.", "Орлова Наталья", "+7 (950) 000-11-22", "orlova@example.org", make_inn12("6671000009")),
        ]
        tenants = []
        for name, contact, phone, email, inn in tenant_specs:
            c = db.execute("INSERT INTO tenants (name, contact_person, phone, email, inn_encrypted, "
                           "inn_hash, created_at) VALUES (?,?,?,?,?,?,?)",
                           (name, contact, phone, email, cipher.encrypt(inn),
                            cipher.blind_index(inn), now))
            tenants.append(c.lastrowid)

        # (клиент, помещение, номер, мес. назад начало, конец (мес. вперёд или дата), ставка,
        #  пропуск последних оплат, частичная оплата последнего, смена ставки (мес. назад, сумма))
        specs = [
            (0, "101", "А-014/24", 14, 10, 85000, 0, False, (6, 92000)),
            (1, "102", "А-021/25", 8, 4, 60000, 2, False, None),
            (2, "103", "А-009/24", 20, ("date", today + timedelta(days=45)), 120000, 0, False, None),
            (3, "201", "А-030/26", 5, 7, 48000, 0, True, None),
            (4, "202", "А-018/25", 11, ("date", today - timedelta(days=20)), 75000, 1, False, None),
            (5, "203", "А-005/25", 12, ("terminate", 2), 56000, 0, False, None),
            (6, "301", "А-033/26", 3, 9, 52000, 0, False, None),
            (7, "105", "А-002/24", 24, 6, 250000, 0, False, (12, 265000)),
        ]
        for ti, pnum, number, back, fwd, rent, skip, partial, change in specs:
            start_ym = add_months(cur, -back)
            start = first_of(start_ym)
            terminate_ym = None
            if isinstance(fwd, tuple) and fwd[0] == "date":
                end = fwd[1]
            elif isinstance(fwd, tuple) and fwd[0] == "terminate":
                terminate_ym = add_months(cur, -fwd[1])
                end = last_of(terminate_ym)
            else:
                end = last_of(add_months(cur, fwd))
            is_active = 0 if terminate_ym else 1
            cid = db.execute(
                "INSERT INTO contracts (number, tenant_id, premises_id, start_date, end_date, "
                "monthly_rent, is_active, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (number, tenants[ti], premises[pnum], start.isoformat(), end.isoformat(),
                 rent * 100, is_active, now)).lastrowid
            if is_active:
                db.execute("UPDATE premises SET status='rented' WHERE id=?", (premises[pnum],))
            changes = []
            if change:
                vf = add_months(cur, -change[0])
                changes = [(vf, change[1] * 100)]
                db.execute("INSERT INTO rent_changes (contract_id, new_rent, valid_from, created_at) "
                           "VALUES (?,?,?,?)", (cid, change[1] * 100, vf, now))
            months = list(months_range(start_ym, min(end.isoformat()[:7], cur)))
            for i, ym in enumerate(months):
                from_end = len(months) - 1 - i
                if from_end < skip:
                    continue
                amount = rent_in(rent * 100, changes, ym)
                if partial and from_end == 0:
                    amount = amount // 2
                paid_at = min(date(int(ym[:4]), int(ym[5:]), 5), today)
                db.execute("INSERT INTO payments (contract_id, period, amount, paid_at, note, "
                           "created_at) VALUES (?,?,?,?,?,?)",
                           (cid, ym, amount, paid_at.isoformat(), "Платёжное поручение", now))
        db.commit()
    print("Демо-данные добавлены.")
    for u, p in creds.items():
        print(f"  Логин: {u:<8} Временный пароль: {p}")
    print("  (при первом входе система попросит задать новый пароль)")
