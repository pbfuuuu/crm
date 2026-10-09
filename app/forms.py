"""Небольшие помощники для чтения и проверки полей форм."""
import re


def get_text(form, key, errors, label, required=False, maxlen=200):
    value = (form.get(key) or "").strip()
    if required and not value:
        errors[key] = f"Поле «{label}» обязательно."
    elif len(value) > maxlen:
        errors[key] = f"Поле «{label}» слишком длинное (максимум {maxlen} символов)."
    return value


def check_email(value, errors, key="email"):
    if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        errors[key] = "Укажите корректный адрес электронной почты."


def check_phone(value, errors, key="phone"):
    if value and not (10 <= len(re.sub(r"\D", "", value)) <= 15):
        errors[key] = "Телефон должен содержать от 10 до 15 цифр."


def like(haystack_parts, query):
    """Поиск подстроки без учёта регистра (работает и для кириллицы)."""
    q = query.casefold()
    return any(q in (p or "").casefold() for p in haystack_parts)
