import os
import re
import sqlite3
import tempfile
import unittest
from datetime import date
from unittest import mock

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from app import create_app, db as dbmod, services

TODAY = date(2026, 10, 6)
TOKEN = "test-csrf-token"
INN_A = "7707083893"      # корректные ИНН (проверены по контрольной сумме)
INN_B = "7736207543"
INN_C = "500100732259"


class WebTestCase(unittest.TestCase):
    """Приложение с временной базой, фиксированной «сегодняшней» датой и двумя пользователями."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.sqlite3")
        self.app = create_app({"DATABASE": self.db_path, "SECRET_KEY": "test-secret",
                               "FERNET_KEY": Fernet.generate_key().decode(), "TESTING": True})
        patcher = mock.patch("app.services.today", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        with self.app.app_context():
            dbmod.init_db()
            db = dbmod.get_db()
            self._user(db, "admin", "admin", "AdminPass1")
            self._user(db, "manager", "manager", "ManagerPass1")
            db.commit()
        self.admin = self.login("admin", "AdminPass1")
        self.manager = self.login("manager", "ManagerPass1")

    @staticmethod
    def _user(db, username, role, password, must_change=0):
        db.execute("INSERT INTO users (username, full_name, password_hash, role, "
                   "must_change_password, created_at) VALUES (?,?,?,?,?,?)",
                   (username, username.title(), generate_password_hash(password, method="pbkdf2:sha256:1000"), role,
                    must_change, services.now_str()))

    # ---- клиент
    def login(self, username, password, expect_ok=True):
        client = self.app.test_client()
        self.post(client, "/login", {"username": username, "password": password})
        return client

    def post(self, client, url, data=None, follow=False):
        with client.session_transaction() as s:
            s["_csrf"] = TOKEN
        payload = dict(data or {})
        payload["csrf_token"] = TOKEN
        return client.post(url, data=payload, follow_redirects=follow)

    def text(self, response):
        html = response.get_data(as_text=True)
        html = re.sub(r"<(script|style).*?</\1>", "", html, flags=re.S)
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))

    # ---- работа с БД напрямую
    def q(self, sql, params=()):
        with self.app.app_context():
            return [dict(r) for r in dbmod.get_db().execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=()):
        with self.app.app_context():
            db = dbmod.get_db()
            db.execute(sql, params)
            db.commit()

    # ---- быстрые фабрики через интерфейс
    def add_tenant(self, name="ООО «Ромашка»", inn=INN_A, client=None):
        r = self.post(client or self.manager, "/tenants/new",
                      {"name": name, "inn": inn, "phone": "+7 912 345-67-89"})
        self.assertEqual(r.status_code, 302, self.text(r)[:300])
        return self.one("SELECT id FROM tenants ORDER BY id DESC LIMIT 1")["id"]

    def add_premises(self, number="101", floor="1", area="50", client=None):
        r = self.post(client or self.manager, "/premises/new",
                      {"number": number, "floor": floor, "area": area, "status": "free"})
        self.assertEqual(r.status_code, 302, self.text(r)[:300])
        return self.one("SELECT id FROM premises WHERE number = ?", (number,))["id"]

    def add_contract(self, tenant_id, premises_id, number="Д-1", start="2026-01-01",
                     end="2026-12-31", rent="50000", client=None):
        r = self.post(client or self.manager, "/contracts/new",
                      {"tenant_id": tenant_id, "premises_id": premises_id, "number": number,
                       "start_date": start, "end_date": end, "monthly_rent": rent})
        self.assertEqual(r.status_code, 302, self.text(r)[:400])
        return self.one("SELECT id FROM contracts WHERE number = ?", (number,))["id"]

    def pay(self, contract_id, period, amount, paid_at="2026-10-05", client=None):
        return self.post(client or self.manager, "/payments/new",
                         {"contract_id": contract_id, "period": period, "amount": amount,
                          "paid_at": paid_at})

    def setup_contract(self, **kw):
        t = self.add_tenant()
        p = self.add_premises()
        return t, p, self.add_contract(t, p, **kw)
