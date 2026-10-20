import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY", "dev-only-change-this-secret")
    GOOGLE_CLIENT_ID = os.environ.get("FLUTU_GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = (
        os.environ.get("FLUTU_GOOGLE_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET", "")
    )
    GOOGLE_REDIRECT_URI = (
        os.environ.get("FLUTU_GOOGLE_REDIRECT_URI")
        or os.environ.get("GOOGLE_REDIRECT_URI")
        or "http://127.0.0.1:8000/auth/google/callback"
    )
    MONGODB_URI = os.environ.get("MONGODB_URI", "")
    MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "flutu")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    JSON_SORT_KEYS = False
