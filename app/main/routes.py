from pymongo.errors import PyMongoError
import hmac
import secrets

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory, session

from app.auth.decorators import login_required
from app.services.quantum_random import choose_direction
from app.services.contacts import add_contacts, delete_all_contacts, delete_contact, list_contacts
from app.services.location_sharing import (
    find_user_by_email,
    get_overview,
    get_sharing_status,
    request_location,
    respond_to_request,
    revoke_share,
    save_location,
    register_user,
    set_sharing_enabled,
)
from app.services.push_notifications import remove_subscription, save_subscription
from app.services.push_notifications import notify_users


main_bp = Blueprint("main", __name__)


@main_bp.get("/dashboard")
@login_required
def dashboard():
    token = session.get("_push_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_push_csrf_token"] = token
    return render_template("dashboard.html", user=session["user"], push_csrf_token=token)


def _valid_push_csrf():
    expected = session.get("_push_csrf_token", "")
    supplied = request.headers.get("X-CSRF-Token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return False
    origin = request.headers.get("Origin")
    if origin:
        return origin == request.host_url.rstrip("/")
    referer = request.headers.get("Referer")
    return bool(referer and referer.startswith(request.host_url))


@main_bp.get("/sw.js")
def push_service_worker():
    response = send_from_directory(current_app.static_folder, "sw.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@main_bp.get("/api/push/vapid-public-key")
def api_push_vapid_public_key():
    key = current_app.config.get("VAPID_PUBLIC_KEY")
    if not all(current_app.config.get(name) for name in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_CONTACT")):
        return jsonify(error="push_not_configured"), 503
    return jsonify(key=key)


@main_bp.post("/api/push/subscribe")
@login_required
def api_push_subscribe():
    if not _valid_push_csrf():
        return jsonify(error="csrf_failed"), 400
    payload = request.get_json(silent=True)
    try:
        save_subscription(session["user"]["sub"], payload)
        return jsonify(subscribed=True), 201
    except ValueError:
        return jsonify(error="invalid_subscription"), 400
    except OverflowError:
        return jsonify(error="subscription_limit"), 429
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not save Web Push subscription")
        return jsonify(error="push_unavailable"), 503


@main_bp.post("/api/push/unsubscribe")
@login_required
def api_push_unsubscribe():
    if not _valid_push_csrf():
        return jsonify(error="csrf_failed"), 400
    payload = request.get_json(silent=True)
    endpoint = payload.get("endpoint") if isinstance(payload, dict) else None
    try:
        removed = remove_subscription(session["user"]["sub"], endpoint)
        return jsonify(unsubscribed=removed)
    except ValueError:
        return jsonify(error="invalid_subscription"), 400
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not remove Web Push subscription")
        return jsonify(error="push_unavailable"), 503


@main_bp.get("/contacts")
@login_required
def contacts():
    return render_template("contacts.html", user=session["user"])


@main_bp.get("/map")
@login_required
def location_map():
    return render_template("location_map.html", user=session["user"])


@main_bp.get("/profile")
@login_required
def profile():
    return render_template("profile.html", user=session["user"])


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


@main_bp.get("/api/location/overview")
@login_required
def api_location_overview():
    try:
        if current_app.config.get("MONGODB_URI"):
            register_user(session["user"])
        return jsonify(get_overview(session["user"]["sub"]))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not load location-sharing data")
        return jsonify(error="Location sharing is temporarily unavailable."), 503


@main_bp.get("/api/location/status")
@login_required
def api_location_status():
    try:
        if current_app.config.get("MONGODB_URI"):
            register_user(session["user"])
        return jsonify(get_sharing_status(session["user"]["sub"]))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not load location-sharing status")
        return jsonify(error="Location sharing is temporarily unavailable."), 503


@main_bp.post("/api/location/sharing")
@login_required
def api_set_location_sharing():
    payload = request.get_json(silent=True)
    enabled = payload.get("enabled") if isinstance(payload, dict) else None
    if not isinstance(enabled, bool):
        return jsonify(error="Choose whether location sharing is enabled."), 400
    try:
        if not set_sharing_enabled(session["user"]["sub"], enabled):
            return jsonify(error="Accept a sharing request before enabling location updates."), 403
        return jsonify(get_sharing_status(session["user"]["sub"]))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not update location-sharing status")
        return jsonify(error="Location sharing is temporarily unavailable."), 503


@main_bp.post("/api/location/requests")
@login_required
def api_request_location():
    payload = request.get_json(silent=True)
    contact_id = payload.get("contact_id") if isinstance(payload, dict) else None
    if not isinstance(contact_id, str) or not contact_id.strip():
        return jsonify(error="Choose a saved contact."), 400

    try:
        contact = next(
            (item for item in list_contacts(session["user"]["sub"]) if item["id"] == contact_id),
            None,
        )
        if not contact or not contact["email"]:
            return jsonify(error="Choose a saved contact with an email address."), 400
        recipient = find_user_by_email(contact["email"])
        if not recipient or recipient["id"] == session["user"]["sub"]:
            return jsonify(error="That contact has not signed in to Flutu yet."), 404
        saved, created = request_location(session["user"], recipient)
        if saved["status"] == "accepted":
            return jsonify(error="Location sharing is already authorized."), 409
        if created:
            notify_users(
                current_app._get_current_object(),
                [recipient["id"]],
                title="Location-sharing request",
                body="A friend asked to share location with you.",
                url="/map",
            )
        return jsonify(request=saved, created=created), (201 if created else 200)
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not create a location-sharing request")
        return jsonify(error="Location sharing is temporarily unavailable."), 503


@main_bp.post("/api/location/requests/<request_id>/respond")
@login_required
def api_respond_location_request(request_id):
    payload = request.get_json(silent=True)
    action = payload.get("action") if isinstance(payload, dict) else None
    if action not in {"accept", "decline", "cancel"}:
        return jsonify(error="Choose accept, decline, or cancel."), 400
    try:
        result = respond_to_request(session["user"]["sub"], request_id, action)
        if not result:
            return jsonify(error="Request not found or no longer available."), 404
        if action in {"accept", "decline"}:
            notify_users(
                current_app._get_current_object(),
                [result["requester_id"]],
                title="Location-sharing request updated",
                body="A friend responded to your location-sharing request.",
                url="/map",
            )
        return jsonify(request=result)
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not update a location-sharing request")
        return jsonify(error="Location sharing is temporarily unavailable."), 503


@main_bp.post("/api/location/updates")
@login_required
def api_update_location():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Send a location update."), 400
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    accuracy = payload.get("accuracy")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (latitude, longitude, accuracy)):
        return jsonify(error="Latitude, longitude, and accuracy must be numbers."), 400
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and 0 <= accuracy <= 100000):
        return jsonify(error="The location values are outside the allowed range."), 400
    try:
        if not save_location(
            session["user"]["sub"], latitude, longitude, accuracy, session["user"].get("picture")
        ):
            return jsonify(error="Accept a sharing request before publishing your location."), 403
        return jsonify(updated=True)
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not save a location update")
        return jsonify(error="Location sharing is temporarily unavailable."), 503


@main_bp.delete("/api/location/shares")
@login_required
def api_revoke_all_location_shares():
    try:
        return jsonify(revoked=revoke_share(session["user"]["sub"]))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not stop all location sharing")
        return jsonify(error="Location sharing is temporarily unavailable."), 503


@main_bp.delete("/api/location/shares/<request_id>")
@login_required
def api_revoke_location_share(request_id):
    try:
        revoked = revoke_share(session["user"]["sub"], request_id)
        if not revoked:
            return jsonify(error="Active sharing permission not found."), 404
        return jsonify(revoked=revoked)
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not stop an individual location share")
        return jsonify(error="Location sharing is temporarily unavailable."), 503


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
    except RuntimeError:
        current_app.logger.exception("Could not retrieve a quantum-random decision")
        return jsonify(error="Could not get a new decision right now."), 502


