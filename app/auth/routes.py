import secrets

import requests
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from app.services.google_oauth import build_authorization_url, fetch_google_user
from app.services.location_sharing import register_user


auth_bp = Blueprint("auth", __name__)


def google_is_configured():
    return bool(current_app.config["GOOGLE_CLIENT_ID"] and current_app.config["GOOGLE_CLIENT_SECRET"])


@auth_bp.get("/login")
def login():
    if session.get("user"):
        return redirect(url_for("main.dashboard"))
    return render_template("login.html", google_configured=google_is_configured()), (
        200 if google_is_configured() else 503
    )


@auth_bp.get("/google/login")
def google_login():
    if not google_is_configured():
        flash("Google sign-in is not configured. Set the OAuth credentials in .env.", "error")
        return redirect(url_for("auth.login"))

    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    return redirect(
        build_authorization_url(
            current_app.config["GOOGLE_CLIENT_ID"],
            current_app.config["GOOGLE_REDIRECT_URI"],
            state,
        )
    )


@auth_bp.get("/callback")
@auth_bp.get("/google/callback")
def callback():
    if not google_is_configured():
        flash("Google sign-in is not configured. Set the OAuth credentials in .env.", "error")
        return redirect(url_for("auth.login"))

    if request.args.get("error"):
        session.pop("oauth_state", None)
        flash("Google sign-in was not completed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    expected_state = session.pop("oauth_state", None)
    received_state = request.args.get("state", "")
    if not expected_state or not secrets.compare_digest(expected_state, received_state):
        flash("The Google sign-in request could not be verified. Please try again.", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code", "")
    if not code:
        flash("Google did not return an authorization code.", "error")
        return redirect(url_for("auth.login"))

    try:
        google_user = fetch_google_user(
            code,
            current_app.config["GOOGLE_CLIENT_ID"],
            current_app.config["GOOGLE_CLIENT_SECRET"],
            current_app.config["GOOGLE_REDIRECT_URI"],
        )
    except (requests.RequestException, ValueError):
        current_app.logger.exception("Google OAuth authentication failed")
        flash("Google sign-in could not be completed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    session.clear()
    session.permanent = True
    session["user"] = {
        "sub": google_user["sub"],
        "email": google_user["email"].strip().lower(),
        "name": google_user.get("name") or google_user["email"],
        "picture": google_user.get("picture"),
    }
    if current_app.config.get("MONGODB_URI"):
        try:
            register_user(session["user"])
        except Exception:
            current_app.logger.exception("Could not register the signed-in user for location sharing")
    return redirect(url_for("main.dashboard"))


@auth_bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
