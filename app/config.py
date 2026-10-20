import os
from pathlib import Path
import re
import subprocess
from datetime import timedelta


def _build_commit():
    for variable in ("FLUTU_BUILD_COMMIT", "VERCEL_GIT_COMMIT_SHA", "GITHUB_SHA", "SOURCE_VERSION"):
        value = os.environ.get(variable, "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", value):
            return value[:12].lower()

    repository_root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


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
    MONGODB_DNS_NAMESERVERS = os.environ.get("MONGODB_DNS_NAMESERVERS", "1.1.1.1,8.8.8.8")
    BUILD_COMMIT = _build_commit()
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    JSON_SORT_KEYS = False
