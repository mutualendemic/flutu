import base64
import binascii
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib import request as urllib_request

from bson import ObjectId
from dateutil.rrule import DAILY, MONTHLY, WEEKLY, YEARLY, MO, TU, WE, TH, FR, SA, SU, rrule
from pymongo import ASCENDING, DESCENDING
from pymongo import ReturnDocument

from app.services import blob_storage
from app.services.mongodb import get_collection


STATUSES = {"open", "closed"}
FREQUENCIES = {"daily": DAILY, "weekly": WEEKLY, "monthly": MONTHLY, "yearly": YEARLY}
WEEKDAYS = (MO, TU, WE, TH, FR, SA, SU)
EVENT_MEMBER_ROLES = {"owner", "admin", "editor", "viewer"}
EVENT_MEMBER_STATUSES = {"pending", "accepted", "declined"}
IMAGE_DATA_URL = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$")
MAX_IMAGE_BYTES = 24 * 1024
MAX_COVER_IMAGE_BYTES = 64 * 1024


def _collection():
    collection = get_collection("calendar_events")
    collection.create_index([("owner_id", ASCENDING), ("updated_at", DESCENDING)])
    return collection


def _parse_datetime(value):
    if not isinstance(value, str):
        raise ValueError("invalid_date")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid_date") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid_date")
    return parsed.astimezone(timezone.utc)


def _isoformat(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _recurrence_rule(date, start):
    recurrence = date.get("recurrence")
    if not recurrence:
        return None
    weekdays = recurrence.get("weekdays")
    return rrule(
        FREQUENCIES[recurrence["frequency"]],
        interval=recurrence["interval"],
        dtstart=start,
        until=_parse_datetime(recurrence["until"]),
        byweekday=[WEEKDAYS[day] for day in weekdays] if weekdays is not None else None,
    )


def _nearest_event_occurrence(event, now=None):
    now = now or datetime.now(timezone.utc)
    upcoming = []
    previous = []
    for date in event.get("dates", []):
        start = _parse_datetime(date["start_at"])
        rule = _recurrence_rule(date, start)
        if rule:
            next_start = rule.after(now, inc=True)
            if next_start is not None:
                upcoming.append(next_start)
            else:
                previous_start = rule.before(now, inc=True)
                if previous_start is not None:
                    previous.append(previous_start)
        elif start >= now:
            upcoming.append(start)
        else:
            previous.append(start)
    nearest = min(upcoming) if upcoming else max(previous, default=None)
    return _isoformat(nearest) if nearest else None


def _normalize_recurrence(value, start_at):
    if value in (None, {}, False):
        return None
    if not isinstance(value, dict):
        raise ValueError("invalid_recurrence")
    frequency = value.get("frequency")
    interval = value.get("interval", 1)
    if not isinstance(frequency, str) or frequency not in FREQUENCIES or isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 30:
        raise ValueError("invalid_recurrence")
    weekdays = value.get("weekdays")
    normalized_weekdays = None
    if frequency == "weekly":
        if weekdays is None:
            weekdays = [start_at.weekday()]
        if (
            not isinstance(weekdays, list) or not weekdays or len(weekdays) > 7 or
            any(isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6 for day in weekdays)
        ):
            raise ValueError("invalid_recurrence")
        normalized_weekdays = sorted(set(weekdays))
    elif weekdays not in (None, []):
        raise ValueError("invalid_recurrence")
    until = _parse_datetime(value.get("until"))
    if until <= start_at or until > start_at + timedelta(days=366 * 10):
        raise ValueError("invalid_recurrence")
    rule = rrule(
        FREQUENCIES[frequency], interval=interval, dtstart=start_at, until=until,
        byweekday=[WEEKDAYS[day] for day in normalized_weekdays] if normalized_weekdays is not None else None,
    )
    if sum(1 for _ in rule) > 500:
        raise ValueError("recurrence_limit")
    result = {"frequency": frequency, "interval": interval, "until": _isoformat(until)}
    if normalized_weekdays is not None:
        result["weekdays"] = normalized_weekdays
    return result


def _normalize_dates(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 50:
        raise ValueError("invalid_dates")
    normalized = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("invalid_dates")
        start_at = _parse_datetime(value.get("start_at"))
        end_at = _parse_datetime(value.get("end_at"))
        if end_at <= start_at or end_at - start_at > timedelta(days=31):
            raise ValueError("invalid_dates")
        normalized.append({
            "start_at": _isoformat(start_at),
            "end_at": _isoformat(end_at),
            "recurrence": _normalize_recurrence(value.get("recurrence"), start_at),
        })
    return normalized


def _normalize_contacts(values, owner_id):
    if not isinstance(values, list) or len(values) > 200 or any(not isinstance(value, str) for value in values):
        raise ValueError("invalid_guests")
    ids = list(dict.fromkeys(values))
    if any(not ObjectId.is_valid(value) for value in ids):
        raise ValueError("invalid_guests")
    if ids:
        found = {
            str(item["_id"])
            for item in get_collection("contacts").find(
                {"_id": {"$in": [ObjectId(value) for value in ids]}, "owner_id": owner_id},
                {"_id": 1},
            )
        }
        if found != set(ids):
            raise ValueError("invalid_guests")
    return ids


def _normalize_event_members(values, owner_id):
    if values in (None, []):
        return []
    if not isinstance(values, list) or len(values) > 50:
        raise ValueError("invalid_event_members")
    normalized = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("invalid_event_members")
        user_id = value.get("user_id")
        role = value.get("role", "viewer")
        status = value.get("status", "pending")
        if user_id == owner_id:
            continue
        if not isinstance(user_id, str) or not user_id or role not in EVENT_MEMBER_ROLES or status not in EVENT_MEMBER_STATUSES:
            raise ValueError("invalid_event_members")
        if user_id in seen:
            continue
        seen.add(user_id)
        normalized.append({"user_id": user_id, "role": role, "status": status})
    return normalized


def _normalize_conversations(values, owner_id):
    if not isinstance(values, list) or len(values) > 50 or any(not isinstance(value, str) for value in values):
        raise ValueError("invalid_conversations")
    ids = list(dict.fromkeys(values))
    from app.services.chat import is_active_member

    if any(not is_active_member(conversation_id, owner_id) for conversation_id in ids):
        raise ValueError("invalid_conversations")
    return ids


def _normalize_points(values, existing_points=None):
    if not isinstance(values, list) or len(values) > 20:
        raise ValueError("invalid_map_points")
    existing_points = existing_points or []
    existing_by_id = {point.get("image_id"): point for point in existing_points if point.get("image_id")}
    points = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("invalid_map_points")
        label = value.get("label", "").strip() if isinstance(value.get("label", ""), str) else None
        latitude = value.get("latitude")
        longitude = value.get("longitude")
        if (
            label is None or len(label) > 120 or
            isinstance(latitude, bool) or not isinstance(latitude, (int, float)) or not math.isfinite(latitude) or not -90 <= latitude <= 90 or
            isinstance(longitude, bool) or not isinstance(longitude, (int, float)) or not math.isfinite(longitude) or not -180 <= longitude <= 180
        ):
            raise ValueError("invalid_map_points")
        image = value.get("image", "")
        image_id = value.get("image_id")
        if image:
            match = IMAGE_DATA_URL.fullmatch(image) if isinstance(image, str) else None
            if not match:
                raise ValueError("invalid_pin_image")
            try:
                decoded = base64.b64decode(match.group(2), validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError("invalid_pin_image") from error
            if not decoded or len(decoded) > MAX_IMAGE_BYTES:
                raise ValueError("invalid_pin_image")
        elif image_id:
            try:
                image_id = str(uuid.UUID(image_id))
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError("invalid_pin_image") from error
            previous = existing_by_id.get(image_id)
            if not previous or not previous.get("image_path"):
                raise ValueError("invalid_pin_image")
        point = {
            "label": label or "Event location",
            "latitude": float(latitude),
            "longitude": float(longitude),
        }
        if image:
            point["image_data"] = image
            point["image_content_type"] = f"image/{match.group(1)}"
        elif image_id:
            point.update({
                "image_id": image_id,
                "image_path": previous["image_path"],
                "image_content_type": previous.get("image_content_type", "image/png"),
            })
        points.append(point)
    return points


def _normalize_cover_image(value, existing_cover_image=None):
    existing_cover_image = existing_cover_image or {}
    image = value.get("cover_image", "")
    image_id = value.get("cover_image_id")
    if image:
        match = IMAGE_DATA_URL.fullmatch(image) if isinstance(image, str) else None
        if not match:
            raise ValueError("invalid_event_image")
        try:
            decoded = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("invalid_event_image") from error
        if not decoded or len(decoded) > MAX_COVER_IMAGE_BYTES:
            raise ValueError("invalid_event_image")
        return {
            "cover_image_data": image,
            "cover_image_content_type": f"image/{match.group(1)}",
        }
    if "cover_image_id" not in value:
        if existing_cover_image.get("cover_image_path"):
            return {
                "cover_image_id": existing_cover_image.get("cover_image_id"),
                "cover_image_path": existing_cover_image["cover_image_path"],
                "cover_image_content_type": existing_cover_image.get("cover_image_content_type", "image/png"),
            }
        return {}
    if image_id in (None, ""):
        return {"cover_image_id": None, "cover_image_path": None, "cover_image_content_type": None}
    if image_id:
        try:
            image_id = str(uuid.UUID(image_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("invalid_event_image") from error
        if image_id != existing_cover_image.get("cover_image_id") or not existing_cover_image.get("cover_image_path"):
            raise ValueError("invalid_event_image")
        return {
            "cover_image_id": image_id,
            "cover_image_path": existing_cover_image["cover_image_path"],
            "cover_image_content_type": existing_cover_image.get("cover_image_content_type", "image/png"),
        }
    return {}


def normalize_event(payload, owner_id, existing_points=None, existing_cover_image=None):
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    title = payload.get("title")
    description = payload.get("description", "")
    status = payload.get("status", "open")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
        raise ValueError("invalid_event_title")
    if not isinstance(description, str) or len(description) > 5000:
        raise ValueError("invalid_description")
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError("invalid_status")
    members = _normalize_event_members(payload.get("members", []), owner_id)
    deduped = []
    seen = set()
    for member in members:
        if member["user_id"] in seen:
            continue
        seen.add(member["user_id"])
        deduped.append(member)
    return {
        "title": title.strip(),
        "description": description.strip(),
        "status": status,
        "dates": _normalize_dates(payload.get("dates")),
        "guest_contact_ids": _normalize_contacts(payload.get("guest_contact_ids", []), owner_id),
        "conversation_ids": _normalize_conversations(payload.get("conversation_ids", []), owner_id),
        "map_points": _normalize_points(payload.get("map_points", []), existing_points),
        "members": deduped,
        **_normalize_cover_image(payload, existing_cover_image),
    }


def _serialize(document):
    private_fields = {"_id", "owner_id", "cover_image_data", "cover_image_path", "cover_image_content_type"}
    result = {key: value for key, value in document.items() if key not in private_fields}
    result["id"] = str(document["_id"])
    if result.get("status") not in STATUSES:
        result["status"] = "open"
    result["cover_image_id"] = document.get("cover_image_id")
    result["has_cover_image"] = bool(document.get("cover_image_path"))
    result["members"] = [
        {
            "user_id": member.get("user_id"),
            "role": member.get("role", "viewer"),
            "status": member.get("status", "pending"),
        }
        for member in document.get("members", [])
    ]
    result["map_points"] = [
        {
            "label": point["label"],
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "image_id": point.get("image_id"),
            "has_image": bool(point.get("image_path")),
        }
        for point in document.get("map_points", [])
    ]
    return result


def _store_point_images(event_id, points):
    uploaded_paths = []
    try:
        for point in points:
            image = point.pop("image_data", None)
            if not image:
                continue
            content = base64.b64decode(IMAGE_DATA_URL.fullmatch(image).group(2), validate=True)
            image_id = blob_storage.new_image_id()
            image_path = blob_storage.upload_image(event_id, image_id, point["image_content_type"], content)
            uploaded_paths.append(image_path)
            point["image_id"] = image_id
            point["image_path"] = image_path
    except Exception:
        _cleanup_images(uploaded_paths)
        raise
    return uploaded_paths


def _store_cover_image(event_id, event):
    image = event.pop("cover_image_data", None)
    if not image:
        return []
    content = base64.b64decode(IMAGE_DATA_URL.fullmatch(image).group(2), validate=True)
    image_id = blob_storage.new_image_id()
    image_path = blob_storage.upload_image(event_id, image_id, event["cover_image_content_type"], content)
    event.update({"cover_image_id": image_id, "cover_image_path": image_path})
    return [image_path]


def _cleanup_images(paths):
    for path in paths:
        try:
            blob_storage.delete_image(path)
        except blob_storage.BlobStorageError:
            pass


def _event_member_for_user(event, user_id):
    for member in event.get("members", []):
        if member.get("user_id") == user_id:
            return member
    return None


def can_manage_event(event, user_id):
    if not isinstance(event, dict):
        return False
    if not event.get("owner_id") and not event.get("members"):
        return True
    if event.get("owner_id") == user_id:
        return True
    member = _event_member_for_user(event, user_id)
    return bool(member and member.get("status") == "accepted" and member.get("role") in {"admin", "editor"})


def _pending_event_invite_recipients(event):
    owner_id = event.get("owner_id")
    return [
        member["user_id"]
        for member in event.get("members", [])
        if member.get("user_id") and member.get("user_id") != owner_id and member.get("status") == "pending"
    ]


def _send_event_email(app, event, recipient_user_id):
    if not app or not app.config.get("RESEND_API_KEY"):
        return
    user = get_collection("users").find_one({"_id": recipient_user_id}, {"email": 1, "name": 1})
    if not user or not user.get("email"):
        return
    subject = f"You are invited to {event.get('title', 'an event')}"
    body = (
        f"<p>Hello {user.get('name') or 'there'},</p>"
        f"<p>You were invited to <strong>{event.get('title', 'an event')}</strong>.</p>"
        f"<p>Open the calendar to review it.</p>"
    )
    payload = json.dumps({
        "from": app.config.get("EMAIL_FROM", "Flutu <noreply@flutu.app>"),
        "to": [user["email"]],
        "subject": subject,
        "html": body,
    }).encode("utf-8")
    request = urllib_request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {app.config['RESEND_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=5):
            pass
    except Exception:
        pass


def _notify_event_members(event):
    try:
        from flask import current_app
        app = current_app._get_current_object() if current_app else None
        if app is None:
            return
        recipients = _pending_event_invite_recipients(event)
        if not recipients:
            return
        from app.services.push_notifications import notify_users
        notify_users(
            app,
            recipients,
            title="Event invitation",
            body=f"You were invited to {event.get('title', 'an event')}",
            url=f"/calendar?event={event.get('id')}",
            exclude_ids={event.get("owner_id")},
        )
        for user_id in recipients:
            _send_event_email(app, event, user_id)
    except Exception:
        return


def list_events(user_id):
    query = {
        "$or": [
            {"owner_id": user_id},
            {"members": {"$elemMatch": {"user_id": user_id, "status": "accepted"}}},
        ]
    }
    rows = _collection().find(query)
    if hasattr(rows, "sort") and not isinstance(rows, list):
        rows = rows.sort("updated_at", DESCENDING)
    return [_serialize(item) for item in rows]


def get_event(user_id, event_id):
    if not ObjectId.is_valid(event_id):
        return None
    query = {
        "_id": ObjectId(event_id),
        "$or": [
            {"owner_id": user_id},
            {"members": {"$elemMatch": {"user_id": user_id, "status": "accepted"}}},
        ],
    }
    item = _collection().find_one(query)
    return _serialize(item) if item else None


def create_event(owner_id, payload):
    normalized = normalize_event(payload, owner_id)
    now = datetime.now(timezone.utc)
    event_id = ObjectId()
    uploaded_paths = []
    try:
        uploaded_paths = _store_point_images(str(event_id), normalized["map_points"])
        uploaded_paths.extend(_store_cover_image(str(event_id), normalized))
        document = {**normalized, "_id": event_id, "owner_id": owner_id, "created_at": now, "updated_at": now}
        _collection().insert_one(document)
        _notify_event_members({**document, "id": str(event_id)})
    except Exception:
        _cleanup_images(uploaded_paths)
        raise
    return _serialize(document)


def update_event(owner_id, event_id, payload):
    if not ObjectId.is_valid(event_id):
        return None
    collection = _collection()
    previous = collection.find_one({"_id": ObjectId(event_id)})
    if not previous:
        return None
    if not can_manage_event(previous, owner_id):
        raise PermissionError("forbidden")
    normalized = normalize_event(
        payload, owner_id, previous.get("map_points", []),
        {key: previous.get(key) for key in ("cover_image_id", "cover_image_path", "cover_image_content_type")},
    )
    old_paths = {point.get("image_path") for point in previous.get("map_points", []) if point.get("image_path")}
    if previous.get("cover_image_path"):
        old_paths.add(previous["cover_image_path"])
    uploaded_paths = []
    try:
        uploaded_paths = _store_point_images(event_id, normalized["map_points"])
        uploaded_paths.extend(_store_cover_image(event_id, normalized))
        result = collection.find_one_and_update(
            {"_id": ObjectId(event_id)},
            {"$set": {**normalized, "updated_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        if result:
            _notify_event_members({**result, "id": str(event_id)})
    except Exception:
        _cleanup_images(uploaded_paths)
        raise
    if not result:
        _cleanup_images(uploaded_paths)
        return None
    new_paths = {point.get("image_path") for point in result.get("map_points", []) if point.get("image_path")}
    if result.get("cover_image_path"):
        new_paths.add(result["cover_image_path"])
    _cleanup_images(old_paths - new_paths)
    return _serialize(result) if result else None


def delete_event(owner_id, event_id):
    if not ObjectId.is_valid(event_id):
        return False
    collection = _collection()
    document = collection.find_one({"_id": ObjectId(event_id)})
    if not document or not can_manage_event(document, owner_id):
        return False
    result = collection.delete_one({"_id": ObjectId(event_id)})
    if result.deleted_count != 1:
        return False
    _cleanup_images([point["image_path"] for point in document.get("map_points", []) if point.get("image_path")])
    if document.get("cover_image_path"):
        _cleanup_images([document["cover_image_path"]])
    return True


def get_event_image(owner_id, event_id, image_id):
    if not ObjectId.is_valid(event_id):
        return None
    try:
        normalized_image_id = str(uuid.UUID(image_id))
    except (ValueError, TypeError, AttributeError):
        return None
    event = _collection().find_one(
        {"_id": ObjectId(event_id), "owner_id": owner_id},
        {"map_points": 1},
    )
    if not event:
        return None
    point = next((item for item in event.get("map_points", []) if item.get("image_id") == normalized_image_id), None)
    if not point or not point.get("image_path"):
        return None
    return blob_storage.download_image(point["image_path"])


def get_event_cover_image(owner_id, event_id):
    if not ObjectId.is_valid(event_id):
        return None
    event = _collection().find_one(
        {"_id": ObjectId(event_id), "owner_id": owner_id},
        {"cover_image_path": 1},
    )
    if not event or not event.get("cover_image_path"):
        return None
    return blob_storage.download_image(event["cover_image_path"])


def list_map_points(owner_id, open_only=False):
    query = {"owner_id": owner_id, "map_points.0": {"$exists": True}}
    if open_only:
        query["status"] = {"$in": ["open", "in_progress"]}
    events = _collection().find(query)
    points = []
    for event in events:
        start_at = _nearest_event_occurrence(event)
        for point_index, point in enumerate(event.get("map_points", [])):
            points.append({
                "event_id": str(event["_id"]),
                "start_at": start_at,
                "point_index": point_index,
                "title": event["title"],
                "description": event.get("description", ""),
                "status": event.get("status") if event.get("status") in STATUSES else "open",
                "label": point["label"],
                "latitude": point["latitude"],
                "longitude": point["longitude"],
                "image_id": point.get("image_id"),
                "has_image": bool(point.get("image_path")),
            })
    return points


def list_occurrences(owner_id, range_start, range_end):
    start = _parse_datetime(range_start)
    end = _parse_datetime(range_end)
    if end <= start or end - start > timedelta(days=62):
        raise ValueError("invalid_range")
    occurrences = []
    for event in _collection().find({"owner_id": owner_id}):
        for date in event.get("dates", []):
            base_start = _parse_datetime(date["start_at"])
            base_end = _parse_datetime(date["end_at"])
            rule = _recurrence_rule(date, base_start)
            if rule:
                starts = rule.between(start, end, inc=True)
            else:
                starts = [base_start] if start <= base_start <= end else []
            for occurrence_start in starts:
                occurrences.append({
                    "event_id": str(event["_id"]),
                    "title": event["title"],
                    "description": event.get("description", ""),
                    "status": event.get("status", "open"),
                    "start_at": _isoformat(occurrence_start),
                    "end_at": _isoformat(occurrence_start + (base_end - base_start)),
                })
    return sorted(occurrences, key=lambda item: item["start_at"])