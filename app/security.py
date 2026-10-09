"""Механизмы безопасности: пароли, шифрование полей, ИНН, CSRF, заголовки."""
import hashlib
import hmac
import re
import secrets
import string

from cryptography.fernet import Fernet, InvalidToken
from flask import abort, current_app, request, session

SPECIAL = "!@#$%^&*"


def generate_password(length: int = 12) -> str:
    """Криптографически стойкий пароль: строчные, прописные, цифры и спецсимвол."""
    alphabet = string.ascii_letters + string.digits + SPECIAL
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pwd) and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd) and any(c in SPECIAL for c in pwd)):
            return pwd


def password_problem(pwd: str):
    """Возвращает текст ошибки или None, если пароль подходит."""
    if len(pwd) < 8:
        return "Пароль должен содержать не менее 8 символов."
    if not re.search(r"[A-Za-zА-Яа-яЁё]", pwd) or not re.search(r"\d", pwd):
        return "Пароль должен содержать и буквы, и цифры."
    return None


class FieldCipher:
    """Шифрование чувствительных полей (Fernet = AES-128-CBC + HMAC-SHA256)."""

    def __init__(self, key):
        key = key.encode("ascii") if isinstance(key, str) else key
        self._fernet = Fernet(key)
        self._index_key = hashlib.sha256(b"blind-index:" + key).digest()

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")

    def blind_index(self, value: str) -> str:
        """Необратимый индекс: позволяет искать дубликаты, не расшифровывая данные."""
        return hmac.new(self._index_key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def get_cipher() -> FieldCipher:
    app = current_app
    if "cipher" not in app.extensions:
        app.extensions["cipher"] = FieldCipher(app.config["FERNET_KEY"])
    return app.extensions["cipher"]


def safe_decrypt(token: str) -> str:
    try:
        return get_cipher().decrypt(token)
    except (InvalidToken, ValueError):
        return "(не удалось расшифровать)"


def validate_inn(inn: str) -> bool:
    """Проверка формата и контрольной суммы ИНН (10 цифр - организация, 12 - ИП)."""
    if not re.fullmatch(r"\d{10}|\d{12}", inn or ""):
        return False
    d = [int(c) for c in inn]
    if len(d) == 10:
        k = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        return sum(a * b for a, b in zip(k, d)) % 11 % 10 == d[9]
    k1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    k2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    return (sum(a * b for a, b in zip(k1, d)) % 11 % 10 == d[10]
            and sum(a * b for a, b in zip(k2, d)) % 11 % 10 == d[11])


def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
        expected = session.get("_csrf", "")
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, "Недействительный токен формы. Обновите страницу и повторите действие.")


def add_security_headers(response):
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
        "form-action 'self'; base-uri 'self'")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if not request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def init_app(app):
    app.before_request(csrf_protect)
    app.after_request(add_security_headers)
    app.jinja_env.globals["csrf_token"] = csrf_token
