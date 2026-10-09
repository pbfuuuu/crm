"""CRM-система для автоматизации работы с арендаторами (Flask + SQLite)."""
from datetime import timedelta

from flask import Flask, render_template

from . import config, db, security, services


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(config.build_config(test_config))
    app.config.setdefault("MAX_FAILED_LOGINS", config.MAX_FAILED_LOGINS)
    app.config.setdefault("LOCK_MINUTES", config.LOCK_MINUTES)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=config.SESSION_HOURS)

    db.init_app(app)
    security.init_app(app)

    from . import auth, contracts, journal, payments, premises, reports, tenants, users
    for module in (auth, reports, tenants, premises, contracts, payments, users, journal):
        app.register_blueprint(module.bp)

    app.jinja_env.filters["money"] = services.fmt_money
    app.jinja_env.filters["date_ru"] = services.fmt_date
    app.jinja_env.filters["month_ru"] = services.fmt_month
    app.jinja_env.filters["area"] = lambda v: f"{v:g}".replace(".", ",") + " м²"

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(500)
    def error_page(e):
        code = getattr(e, "code", 500)
        texts = {400: "Некорректный запрос", 403: "Доступ запрещён", 404: "Страница не найдена",
                 500: "Внутренняя ошибка сервера"}
        message = e.description if code == 400 else {
            403: "У вашей роли нет прав на это действие.",
            404: "Такой страницы или записи не существует.",
            500: "Что-то пошло не так. Попробуйте ещё раз."}.get(code, "")
        return render_template("error.html", code=code, title=texts.get(code, "Ошибка"),
                               message=message), code

    return app
