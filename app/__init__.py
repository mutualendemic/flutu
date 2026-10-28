from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_babel import Babel

from app.config import Config

def create_app(config_object=Config):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_object)
    app.config.setdefault("BUILD_COMMIT", Config.BUILD_COMMIT)
    app.config.setdefault("SUPPORTED_LOCALES", Config.SUPPORTED_LOCALES)
    app.config.setdefault("BABEL_DEFAULT_LOCALE", Config.BABEL_DEFAULT_LOCALE)

    def select_locale():
        return (
            session.get("locale")
            or request.accept_languages.best_match(app.config["SUPPORTED_LOCALES"])
            or app.config["BABEL_DEFAULT_LOCALE"]
        )

    Babel(app, locale_selector=select_locale)
    app.jinja_env.globals["get_locale"] = select_locale
    from app.i18n import get_ui_messages
    app.jinja_env.globals["get_ui_messages"] = get_ui_messages

    from app.auth.routes import auth_bp
    from app.main.routes import main_bp
    from app.chat import chat_bp
    from app.chat.sockets import init_socketio

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(main_bp)
    app.register_blueprint(chat_bp, url_prefix="/chat")
    init_socketio(app)

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found"), 404
        return "Not found", 404

    @app.get("/")
    def index():
        if "user" in session:
            return redirect(url_for("main.dashboard"))
        return render_template(
            "landing.html",
            google_configured=bool(app.config["GOOGLE_CLIENT_ID"] and app.config["GOOGLE_CLIENT_SECRET"]),
        )

    return app
