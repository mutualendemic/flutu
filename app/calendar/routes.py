import hmac
import secrets
from urllib.parse import urlsplit

from flask import Response, current_app, jsonify, render_template, request, session, url_for
from pymongo.errors import PyMongoError

from app.auth.decorators import login_required
from app.calendar import calendar_bp
from app.services.blob_storage import BlobStorageError
from app.services import events, location_search


def _user_id():
    return session["user"]["sub"]


def _valid_csrf():
    expected = session.get("_calendar_csrf_token", "")
    supplied = request.headers.get("X-CSRF-Token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return False
    origin = request.headers.get("Origin")
    if origin:
        return origin == request.host_url.rstrip("/")
    referer = request.headers.get("Referer")
    if not referer:
        return True
    parsed_referer = urlsplit(referer)
    return parsed_referer.scheme in {"http", "https"} and parsed_referer.netloc == request.host


@calendar_bp.before_request
def protect_calendar_api():
    if request.path.startswith("/calendar/api/"):
        if not session.get("user"):
            return jsonify(error="Authentication required."), 401
        if request.method in {"POST", "PATCH", "PUT", "DELETE"} and not _valid_csrf():
            return jsonify(error="csrf_failed"), 400


@calendar_bp.app_context_processor
def calendar_csrf_context():
    def calendar_csrf_token():
        token = session.get("_calendar_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_calendar_csrf_token"] = token
        return token
    return {"calendar_csrf_token": calendar_csrf_token}


def _event_response(event):
    if not event:
        return event
    event["cover_image_url"] = url_for(
        "calendar.api_event_cover_image", event_id=event["id"]
    ) if event.get("cover_image_id") else ""
    for point in event.get("map_points", []):
        point["image_url"] = url_for(
            "calendar.api_event_image", event_id=event["id"], image_id=point["image_id"]
        ) if point.get("image_id") else ""
    return event


@calendar_bp.get("/")
@login_required
def page():
    return render_template("calendar.html", user=session["user"])


@calendar_bp.get("/api/events")
def api_list_events():
    try:
        return jsonify(events=[_event_response(event) for event in events.list_events(_user_id())])
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not load calendar events")
        return jsonify(error="calendar_unavailable"), 503


@calendar_bp.post("/api/events")
def api_create_event():
    try:
        event = events.create_event(_user_id(), request.get_json(silent=True))
        return jsonify(event=_event_response(event)), 201
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except BlobStorageError:
        return jsonify(error="blob_unavailable"), 503
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not create calendar event")
        return jsonify(error="calendar_unavailable"), 503


@calendar_bp.patch("/api/events/<event_id>")
def api_update_event(event_id):
    try:
        event = events.update_event(_user_id(), event_id, request.get_json(silent=True))
        if not event:
            return jsonify(error="not_found"), 404
        return jsonify(event=_event_response(event))
    except PermissionError:
        return jsonify(error="forbidden"), 403
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except BlobStorageError:
        return jsonify(error="blob_unavailable"), 503
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not update calendar event")
        return jsonify(error="calendar_unavailable"), 503


@calendar_bp.delete("/api/events/<event_id>")
def api_delete_event(event_id):
    try:
        if not events.delete_event(_user_id(), event_id):
            return jsonify(error="forbidden" if events.get_event(_user_id(), event_id) else "not_found"), 403 if events.get_event(_user_id(), event_id) else 404
        return jsonify(deleted=True)
    except PermissionError:
        return jsonify(error="forbidden"), 403
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not delete calendar event")
        return jsonify(error="calendar_unavailable"), 503


@calendar_bp.get("/api/map-points")
def api_map_points():
    try:
        points = events.list_map_points(_user_id(), open_only=request.args.get("status") == "open")
        for point in points:
            point["image_url"] = url_for(
                "calendar.api_event_image", event_id=point["event_id"], image_id=point["image_id"]
            ) if point.get("image_id") else ""
        return jsonify(points=points)
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not load event map points")
        return jsonify(error="calendar_unavailable"), 503


@calendar_bp.get("/api/location-search")
def api_location_search():
    try:
        return jsonify(locations=location_search.search_locations(request.args.get("q", "")))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except location_search.LocationSearchError as error:
        status = 429 if str(error) == "location_search_rate_limited" else 502
        return jsonify(error=str(error)), status


@calendar_bp.get("/api/events/<event_id>/images/<image_id>")
def api_event_image(event_id, image_id):
    try:
        image = events.get_event_image(_user_id(), event_id, image_id)
        if not image:
            return jsonify(error="not_found"), 404
        content_type, content = image
        response = Response(content, mimetype=content_type)
        response.headers["Cache-Control"] = "private, no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response
    except BlobStorageError:
        return jsonify(error="blob_unavailable"), 503


@calendar_bp.get("/api/events/<event_id>/cover-image")
def api_event_cover_image(event_id):
    try:
        image = events.get_event_cover_image(_user_id(), event_id)
        if not image:
            return jsonify(error="not_found"), 404
        content_type, content = image
        response = Response(content, mimetype=content_type)
        response.headers["Cache-Control"] = "private, no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response
    except BlobStorageError:
        return jsonify(error="blob_unavailable"), 503


@calendar_bp.get("/api/occurrences")
def api_occurrences():
    try:
        return jsonify(occurrences=events.list_occurrences(
            _user_id(), request.args.get("from", ""), request.args.get("to", "")
        ))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not load calendar occurrences")
        return jsonify(error="calendar_unavailable"), 503