import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = Path(os.environ.get("CRM_INSTANCE", BASE_DIR / "instance"))

EXPIRY_WARN_DAYS = 60       # за сколько дней предупреждать об окончании договора
MAX_FAILED_LOGINS = 5       # неудачных входов до блокировки
LOCK_MINUTES = 10           # длительность блокировки учётной записи
SESSION_HOURS = 8           # время жизни сессии


def _load_or_create(filename, env_name, factory):
    value = os.environ.get(env_name)
    if value:
        return value
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    path = INSTANCE_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = factory()
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


def build_config(overrides=None):
    from cryptography.fernet import Fernet
    import secrets

    cfg = dict(overrides or {})
    cfg.setdefault("DATABASE", str(INSTANCE_DIR / "crm.sqlite3"))
    if "SECRET_KEY" not in cfg:
        cfg["SECRET_KEY"] = _load_or_create(
            "secret_key", "CRM_SECRET_KEY", lambda: secrets.token_hex(32))
    if "FERNET_KEY" not in cfg:
        cfg["FERNET_KEY"] = _load_or_create(
            "fernet.key", "CRM_FERNET_KEY",
            lambda: Fernet.generate_key().decode("ascii"))
    cfg.setdefault("SESSION_COOKIE_HTTPONLY", True)
    cfg.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    cfg.setdefault("SESSION_COOKIE_SECURE", os.environ.get("CRM_HTTPS") == "1")
    cfg.setdefault("MAX_CONTENT_LENGTH", 1024 * 1024)
    return cfg
