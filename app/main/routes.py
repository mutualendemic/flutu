import json

import requests
from pymongo.errors import PyMongoError
from flask import Blueprint, current_app, jsonify, render_template, request, session

from app.auth.decorators import login_required
from app.services.quantum_random import choose_direction
from app.services.contacts import add_contacts, delete_all_contacts, delete_contact, list_contacts


main_bp = Blueprint("main", __name__)


@main_bp.get("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user=session["user"])


@main_bp.get("/contacts")
@login_required
def contacts():
    return render_template("contacts.html", user=session["user"])


def _normalize_contact(value):
    if not isinstance(value, dict):
        return None

    def field(name, limit):
        item = value.get(name, "")
        if isinstance(item, list):
            item = next((entry for entry in item if isinstance(entry, str) and entry.strip()), "")
        if not isinstance(item, str):
            return None
        item = item.strip()
        return item if len(item) <= limit else None

    name = field("name", 120)
    tel = field("tel", 80)
    email = field("email", 254)
    if name is None or tel is None or email is None:
        return None
    if not name or (not tel and not email):
        return None
    return {"name": name, "tel": tel, "email": email}


@main_bp.get("/api/contacts")
@login_required
def api_contacts():
    try:
        return jsonify(contacts=list_contacts(session["user"]["sub"]))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not load contacts from MongoDB")
        return jsonify(error="Contacts are temporarily unavailable."), 503


@main_bp.post("/api/contacts")
@login_required
def api_add_contacts():
    payload = request.get_json(silent=True)
    values = payload.get("contacts") if isinstance(payload, dict) else None
    if values is None and isinstance(payload, dict):
        values = [payload]
    if not isinstance(values, list) or not values or len(values) > 100:
        return jsonify(error="Send between 1 and 100 contacts."), 400

    normalized = [_normalize_contact(value) for value in values]
    if any(contact is None for contact in normalized):
        return jsonify(error="Each contact needs a name and a phone number or email, within the field limits."), 400

    try:
        saved = add_contacts(session["user"]["sub"], normalized)
        return jsonify(contacts=saved), 201
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not save contacts to MongoDB")
        return jsonify(error="Contacts are temporarily unavailable."), 503


@main_bp.delete("/api/contacts")
@login_required
def api_delete_all_contacts():
    try:
        deleted = delete_all_contacts(session["user"]["sub"])
        return jsonify(deleted=deleted)
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not delete contacts from MongoDB")
        return jsonify(error="Contacts are temporarily unavailable."), 503


@main_bp.delete("/api/contacts/<contact_id>")
@login_required
def api_delete_contact(contact_id):
    try:
        if not delete_contact(session["user"]["sub"], contact_id):
            return jsonify(error="Contact not found."), 404
        return "", 204
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not delete contact from MongoDB")
        return jsonify(error="Contacts are temporarily unavailable."), 503


@main_bp.get("/decision")
@login_required
def decision():
    return render_template("decision.html")


@main_bp.get("/decision/info")
@login_required
def quantum_info():
    return render_template("quantum_info.html")


@main_bp.post("/api/decision")
@login_required
def api_decision():
    try:
        return jsonify(go_right=choose_direction())
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        current_app.logger.exception("Could not retrieve a quantum-random decision")
        return jsonify(error="Could not get a new decision right now."), 502


