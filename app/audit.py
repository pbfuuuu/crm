"""Журнал действий пользователей."""
from flask import g, request

from .services import now_str

ACTIONS = {
    "login": "Вход", "login_failed": "Неудачный вход", "logout": "Выход",
    "create": "Создание", "update": "Изменение", "delete": "Удаление",
    "password_change": "Смена пароля", "password_reset": "Сброс пароля",
    "activate": "Активация", "deactivate": "Блокировка",
    "terminate": "Расторжение", "rent_change": "Изменение ставки",
    "payment_add": "Оплата", "payment_delete": "Удаление оплаты",
    "export": "Экспорт",
}
OBJECTS = {
    "user": "Пользователь", "tenant": "Клиент", "premises": "Помещение",
    "contract": "Договор", "payment": "Платёж", "rent_change": "Ставка", "report": "Отчёт",
}


def log(db, action, object_type=None, object_id=None, details=None, username=None):
    """Пишет событие в журнал. Коммит выполняет вызывающий код вместе с основным действием."""
    user = getattr(g, "user", None)
    db.execute(
        "INSERT INTO audit_log (user_id, username, action, object_type, object_id, "
        "details, ip, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (user["id"] if user else None,
         user["username"] if user else (username or "")[:64],
         action, object_type, object_id, details,
         request.remote_addr if request else None, now_str()))
