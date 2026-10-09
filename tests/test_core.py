"""Тесты ядра: деньги, даты, начисления, ИНН, пароли, шифрование."""
import unittest
from datetime import date

from cryptography.fernet import Fernet, InvalidToken

from app import services
from app.security import (FieldCipher, generate_password, password_problem, validate_inn)
from seed import make_inn10, make_inn12


class MoneyAndDates(unittest.TestCase):
    def test_parse_money(self):
        self.assertEqual(services.parse_money("55000"), 5500000)
        self.assertEqual(services.parse_money("55 000,50"), 5500050)
        self.assertEqual(services.parse_money("0.005"), 1)       # округление вверх
        self.assertEqual(services.parse_money("1.234,5"), None)  # два разделителя — не число
        for bad in ("", "abc", "NaN", "inf", None):
            self.assertIsNone(services.parse_money(bad), bad)

    def test_fmt_money(self):
        self.assertEqual(services.fmt_money(5500050), "55 000,50 ₽")
        self.assertEqual(services.fmt_money(0), "0,00 ₽")
        self.assertEqual(services.fmt_money(123456789), "1 234 567,89 ₽")

    def test_add_months_across_year(self):
        self.assertEqual(services.add_months("2026-12", 1), "2027-01")
        self.assertEqual(services.add_months("2026-01", -1), "2025-12")
        self.assertEqual(services.add_months("2026-05", 14), "2027-07")

    def test_months_range(self):
        self.assertEqual(list(services.months_range("2026-11", "2027-02")),
                         ["2026-11", "2026-12", "2027-01", "2027-02"])
        self.assertEqual(list(services.months_range("2026-05", "2026-04")), [])

    def test_parse_month_and_date(self):
        self.assertEqual(services.parse_month("2026-04"), "2026-04")
        for bad in ("2026-13", "2026-00", "26-04", "", None, "2026-4"):
            self.assertIsNone(services.parse_month(bad), bad)
        self.assertEqual(services.parse_date("2026-02-28"), date(2026, 2, 28))
        self.assertIsNone(services.parse_date("2026-02-30"))

    def test_overlap(self):
        f = services.ranges_overlap
        self.assertTrue(f("2026-01-01", "2026-06-30", "2026-06-30", "2026-12-31"))
        self.assertFalse(f("2026-01-01", "2026-06-29", "2026-06-30", "2026-12-31"))


class Accruals(unittest.TestCase):
    def contract(self, start="2026-01-15", end="2026-12-31", rent=5000000):
        return {"id": 1, "start_date": start, "end_date": end, "monthly_rent": rent,
                "is_active": 1}

    def test_rent_change_applies_only_from_month(self):
        ch = [("2026-04", 5500000)]
        self.assertEqual(services.rent_in(5000000, ch, "2026-03"), 5000000)
        self.assertEqual(services.rent_in(5000000, ch, "2026-04"), 5500000)
        self.assertEqual(services.rent_in(5000000, ch, "2027-01"), 5500000)

    def test_scenario_from_report(self):
        """Договор 15.01–31.12.2026, 50 000 ₽, с апреля 55 000 ₽; оплачены янв–март."""
        data = {"changes": {1: [("2026-04", 5500000)]},
                "paid": {1: {"2026-01": 5000000, "2026-02": 5000000, "2026-03": 5000000}}}
        c = self.contract()
        self.assertEqual(services.contract_summary(c, data, date(2026, 3, 20))["debt"], 0)
        s = services.contract_summary(c, data, date(2026, 10, 5))
        self.assertEqual(s["debt"], 38500000)           # 7 мес. по 55 000
        self.assertEqual(s["accrued"], 3 * 5000000 + 7 * 5500000)
        self.assertEqual(len(s["months"]), 10)

    def test_overpayment_is_not_debt(self):
        data = {"changes": {}, "paid": {1: {"2026-01": 9000000}}}
        s = services.contract_summary(self.contract(), data, date(2026, 1, 20))
        self.assertEqual(s["debt"], 0)
        self.assertEqual(s["overpaid"], 4000000)

    def test_before_start_and_after_end(self):
        data = {"changes": {}, "paid": {}}
        c = self.contract(start="2026-06-01", end="2026-08-31")
        self.assertEqual(services.contract_summary(c, data, date(2026, 5, 31))["accrued"], 0)
        s = services.contract_summary(c, data, date(2027, 3, 1))   # начисления заканчиваются
        self.assertEqual(s["accrued"], 3 * 5000000)

    def test_partial_and_status(self):
        data = {"changes": {}, "paid": {1: {"2026-06": 2500000}}}
        c = self.contract(start="2026-06-01", end="2026-07-31")
        s = services.contract_summary(c, data, date(2026, 7, 10))
        self.assertEqual([m["status"] for m in s["months"]], ["partial", "unpaid"])

    def test_contract_state(self):
        c = {"is_active": 1, "end_date": "2026-10-05"}
        self.assertEqual(services.contract_state(c, date(2026, 10, 6)), "expired")
        self.assertEqual(services.contract_state(c, date(2026, 10, 5)), "active")
        self.assertEqual(services.contract_state({"is_active": 0, "end_date": "2030-01-01"},
                                                 date(2026, 1, 1)), "closed")


class InnValidation(unittest.TestCase):
    def test_known_valid(self):
        for inn in ("7707083893", "7736207543", "500100732259"):
            self.assertTrue(validate_inn(inn), inn)

    def test_invalid(self):
        for inn in ("7707083894", "123", "", "77070838931", "abcdefghij", "500100732258", None):
            self.assertFalse(validate_inn(inn), inn)

    def test_generators_produce_valid(self):
        self.assertTrue(validate_inn(make_inn10("667100001")))
        self.assertTrue(validate_inn(make_inn12("6671000002")))


class Passwords(unittest.TestCase):
    def test_generated_composition(self):
        seen = set()
        for _ in range(500):
            p = generate_password()
            seen.add(p)
            self.assertEqual(len(p), 12)
            self.assertTrue(any(c.islower() for c in p) and any(c.isupper() for c in p))
            self.assertTrue(any(c.isdigit() for c in p) and any(c in "!@#$%^&*" for c in p))
        self.assertEqual(len(seen), 500)         # дубликатов нет

    def test_generated_passes_policy(self):
        for _ in range(50):
            self.assertIsNone(password_problem(generate_password()))

    def test_policy(self):
        self.assertIsNotNone(password_problem("abc1"))
        self.assertIsNotNone(password_problem("abcdefghij"))
        self.assertIsNotNone(password_problem("12345678"))
        self.assertIsNone(password_problem("Parol123"))
        self.assertIsNone(password_problem("пароль12345"))


class Encryption(unittest.TestCase):
    def setUp(self):
        self.c = FieldCipher(Fernet.generate_key())

    def test_roundtrip(self):
        self.assertEqual(self.c.decrypt(self.c.encrypt("7707083893")), "7707083893")

    def test_ciphertext_hides_value_and_is_randomized(self):
        a, b = self.c.encrypt("7707083893"), self.c.encrypt("7707083893")
        self.assertNotIn("7707083893", a)
        self.assertNotEqual(a, b)

    def test_tampering_detected(self):
        token = self.c.encrypt("secret")
        broken = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
        with self.assertRaises(InvalidToken):
            self.c.decrypt(broken)

    def test_other_key_cannot_decrypt(self):
        other = FieldCipher(Fernet.generate_key())
        with self.assertRaises(InvalidToken):
            other.decrypt(self.c.encrypt("x"))

    def test_blind_index(self):
        self.assertEqual(self.c.blind_index("1"), self.c.blind_index("1"))
        self.assertNotEqual(self.c.blind_index("1"), self.c.blind_index("2"))
        self.assertNotEqual(self.c.blind_index("1"),
                            FieldCipher(Fernet.generate_key()).blind_index("1"))


if __name__ == "__main__":
    unittest.main()
