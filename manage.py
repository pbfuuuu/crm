"""Служебные команды:
    python manage.py init-db                  создать таблицы
    python manage.py create-admin [логин]     создать администратора (пароль генерируется)
    python manage.py seed-demo                заполнить демонстрационными данными
    python manage.py backup                   резервная копия базы в папку backups/
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import create_app, db as dbmod, services
from app.security import generate_password


def cmd_init_db(app):
    with app.app_context():
        dbmod.init_db()
    print("База данных готова:", app.config["DATABASE"])


def create_user(db, username, full_name, role, password=None):
    password = password or generate_password()
    db.execute("INSERT INTO users (username, full_name, password_hash, role, "
               "must_change_password, created_at) VALUES (?,?,?,?,1,?)",
               (username, full_name, generate_password_hash(password), role, services.now_str()))
    db.commit()
    return password


def cmd_create_admin(app, username):
    with app.app_context():
        dbmod.init_db()
        db = dbmod.get_db()
        if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            sys.exit(f"Пользователь «{username}» уже существует.")
        pwd = create_user(db, username, "Администратор", "admin")
    print(f"Администратор создан.\n  Логин:  {username}\n  Пароль: {pwd}\n"
          "Пароль временный — система потребует сменить его при первом входе.")


def cmd_backup(app):
    src = Path(app.config["DATABASE"])
    if not src.exists():
        sys.exit("Базы данных ещё нет — копировать нечего.")
    dst_dir = src.parent.parent / "backups"
    dst_dir.mkdir(exist_ok=True)
    dst = dst_dir / f"crm_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"
    s, d = sqlite3.connect(src), sqlite3.connect(dst)
    with d:
        s.backup(d)     # безопасное копирование даже при работающем приложении
    s.close(); d.close()
    print("Резервная копия:", dst)


def main():
    parser = argparse.ArgumentParser(description="Управление CRM")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    p = sub.add_parser("create-admin"); p.add_argument("username", nargs="?", default="admin")
    sub.add_parser("seed-demo")
    sub.add_parser("backup")
    args = parser.parse_args()
    app = create_app()
    if args.cmd == "init-db":
        cmd_init_db(app)
    elif args.cmd == "create-admin":
        cmd_create_admin(app, args.username)
    elif args.cmd == "backup":
        cmd_backup(app)
    elif args.cmd == "seed-demo":
        from seed import seed
        seed(app)


if __name__ == "__main__":
    main()
