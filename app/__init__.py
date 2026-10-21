from flask import Flask, jsonify, redirect, request, session, url_for

from app.config import Config

def create_app(config_object=Config):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_object)
    app.config.setdefault("BUILD_COMMIT", Config.BUILD_COMMIT)

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
        return redirect(url_for("auth.login"))

    return app
