import base64
import binascii
from html import escape as html_escape
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib import request as urllib_request

from bson import ObjectId
from dateutil.rrule import DAILY, MONTHLY, WEEKLY, YEARLY, MO, TU, WE, TH, FR, SA, SU, rrule
from flask_babel import gettext
from pymongo import ASCENDING, DESCENDING
from pymongo import ReturnDocument

from app.services import blob_storage
from app.services.mongodb import get_collection


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


def _event_status(event, now=None):
    now = now or datetime.now(timezone.utc)
    for date in event.get("dates", []):
        start = _parse_datetime(date["start_at"])
        end = _parse_datetime(date["end_at"])
        duration = end - start
        rule = _recurrence_rule(date, start)
        if not rule:
            if end >= now:
                return "open"
            continue
        if rule.after(now, inc=True) is not None:
            return "open"
        previous = rule.before(now, inc=True)
        if previous is not None and previous + duration >= now:
            return "open"
    return "closed"


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


def list_addable_members(owner_id):
    from app.services.chat import addable_contacts

    return [
        {
            "contact_id": item["id"],
            "user_id": item["user_id"],
            "name": item.get("account_name") or item.get("name") or item["email"],
            "email": item["email"],
            "picture": item.get("picture", ""),
            "registered": True,
        }
        for item in addable_contacts(owner_id)
        if item.get("user_id") and item.get("email")
    ]


def _event_members_from_guest_contacts(contact_ids, owner_id, existing_members=None):
    if not contact_ids:
        return []
    candidates = {
        item["contact_id"]: item
        for item in list_addable_members(owner_id)
    }
    existing_by_user = {member.get("user_id"): member for member in existing_members or []}
    members = []
    for contact_id in contact_ids:
        candidate = candidates.get(contact_id)
        if not candidate:
            continue
        previous = existing_by_user.get(candidate["user_id"])
        if previous:
            members.append({
                **previous,
                "picture": previous.get("picture") or candidate.get("picture", ""),
                "status": previous.get("status") if previous.get("status") in {"pending", "accepted"} else "pending",
            })
        else:
            members.append({
                "user_id": candidate["user_id"],
                "name": candidate["name"],
                "email": candidate["email"],
                "picture": candidate.get("picture", ""),
                "role": "viewer",
                "status": "pending",
            })
    return members


def _normalize_event_members(values, owner_id, existing_members=None):
    if values is None:
        return list(existing_members or [])
    if values == []:
        return []
    if not isinstance(values, list) or len(values) > 50:
        raise ValueError("invalid_event_members")
    eligible = {item["user_id"]: item for item in list_addable_members(owner_id)}
    existing = {item.get("user_id"): item for item in existing_members or []}
    normalized = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("invalid_event_members")
        user_id = value.get("user_id")
        if user_id == owner_id:
            continue
        previous = existing.get(user_id) if isinstance(user_id, str) else None
        role = value.get("role", previous.get("role", "viewer") if previous else "viewer")
        if role == "admin" and previous and previous.get("role") == "admin":
            role = "editor"
        if not isinstance(user_id, str) or not user_id or not isinstance(role, str) or role not in {"editor", "viewer"}:
            raise ValueError("invalid_event_members")
        account = eligible.get(user_id)
        if not account and not previous:
            raise ValueError("invalid_event_members")
        profile = account or previous
        if user_id in seen:
            continue
        seen.add(user_id)
        normalized.append({
            "user_id": user_id,
            "name": profile.get("name") or profile.get("email", ""),
            "email": profile.get("email", ""),
            "picture": profile.get("picture", ""),
            "role": role,
            "status": previous.get("status") if previous and previous.get("status") in {"pending", "accepted"} else "pending",
        })
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


def normalize_event(payload, owner_id, existing_points=None, existing_cover_image=None, existing_members=None):
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    title = payload.get("title")
    description = payload.get("description", "")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
        raise ValueError("invalid_event_title")
    if not isinstance(description, str) or len(description) > 5000:
        raise ValueError("invalid_description")
    raw_guest_contact_ids = _normalize_contacts(payload.get("guest_contact_ids", []), owner_id)
    linked_guest_ids = {item["contact_id"] for item in list_addable_members(owner_id) if item.get("contact_id")}
    guest_contact_ids = [contact_id for contact_id in raw_guest_contact_ids if contact_id not in linked_guest_ids]
    members = _normalize_event_members(payload.get("members", existing_members), owner_id, existing_members)
    member_ids = {member["user_id"] for member in members}
    for guest_member in _event_members_from_guest_contacts(
        [contact_id for contact_id in raw_guest_contact_ids if contact_id in linked_guest_ids],
        owner_id,
        existing_members,
    ):
        if guest_member["user_id"] not in member_ids:
            member_ids.add(guest_member["user_id"])
            members.append(guest_member)
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
        "dates": _normalize_dates(payload.get("dates")),
        "guest_contact_ids": guest_contact_ids,
        "conversation_ids": _normalize_conversations(payload.get("conversation_ids", []), owner_id),
        "map_points": _normalize_points(payload.get("map_points", []), existing_points),
        "members": deduped,
        **_normalize_cover_image(payload, existing_cover_image),
    }


def _serialize(document, now=None, user_id=None):
    private_fields = {"_id", "owner_id", "cover_image_data", "cover_image_path", "cover_image_content_type"}
    result = {key: value for key, value in document.items() if key not in private_fields}
    result["id"] = str(document["_id"])
    result["status"] = _event_status(document, now)
    result["cover_image_id"] = document.get("cover_image_id")
    result["has_cover_image"] = bool(document.get("cover_image_path"))
    member_documents = document.get("members", [])
    missing_profile_ids = [
        member.get("user_id") for member in member_documents
        if member.get("user_id") and (not member.get("email") or not member.get("picture") or not member.get("name"))
    ]
    profiles = {}
    if missing_profile_ids:
        profiles = {
            profile["_id"]: profile
            for profile in get_collection("users").find(
                {"_id": {"$in": missing_profile_ids}}, {"name": 1, "email": 1, "picture": 1}
            )
        }
    result["members"] = [
        {
            "user_id": member.get("user_id"),
            "name": member.get("name") or profiles.get(member.get("user_id"), {}).get("name", ""),
            "email": member.get("email") or profiles.get(member.get("user_id"), {}).get("email", ""),
            "picture": member.get("picture") or profiles.get(member.get("user_id"), {}).get("picture", ""),
            "registered": True,
            "role": member.get("role", "viewer"),
            "status": member.get("status", "pending"),
        }
        for member in member_documents
    ]
    member = _event_member_for_user(document, user_id) if user_id else None
    result["viewer_role"] = "owner" if document.get("owner_id") == user_id else member.get("role") if member else None
    result["viewer_status"] = "accepted" if document.get("owner_id") == user_id else member.get("status") if member else None
    result["can_edit"] = can_manage_event(document, user_id) if user_id else False
    result["can_delete"] = document.get("owner_id") == user_id if user_id else False
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


def _event_access_query(user_id):
    return {
        "$or": [
            {"owner_id": user_id},
            {"members": {"$elemMatch": {"user_id": user_id, "status": {"$in": ["pending", "accepted"]}}}},
        ]
    }


def _can_view_event(event, user_id):
    return bool(
        event.get("owner_id") == user_id
        or any(member.get("user_id") == user_id and member.get("status") in {"pending", "accepted"}
               for member in event.get("members", []))
    )


def _pending_event_invite_recipients(event):
    owner_id = event.get("owner_id")
    return [
        member["user_id"]
        for member in event.get("members", [])
        if member.get("user_id") and member.get("user_id") != owner_id and member.get("status") == "pending"
    ]


def _send_event_email(app, event, recipient_email, recipient_name="", invitation=False, guest=False):
    if not app:
        return
    if not app.config.get("RESEND_API_KEY"):
        app.logger.info("Calendar email skipped because Resend is not configured")
        return
    if not isinstance(recipient_email, str) or "@" not in recipient_email:
        return
    event_title = event.get("title", "an event")
    name = recipient_name or "there"
    if guest and invitation:
        subject = gettext("Event invitation: {title}").format(title=event_title)
        message = gettext("You have been added as a guest to {title}.").format(title=event_title)
        next_step = gettext("Please contact the event organizer for details.")
    elif guest:
        subject = gettext("Event update: {title}").format(title=event_title)
        message = gettext("An event where you are listed as a guest was updated: {title}.").format(title=event_title)
        next_step = gettext("Please contact the event organizer for details.")
    elif invitation:
        subject = gettext("Event invitation: {title}").format(title=event_title)
        message = gettext("You were invited to {title}.").format(title=event_title)
        next_step = gettext("Open the calendar to review it.")
    else:
        subject = gettext("Event updated: {title}").format(title=event_title)
        message = gettext("An event you are a member of was updated: {title}.").format(title=event_title)
        next_step = gettext("Open the calendar to review it.")
    body = (
        f"<p>{html_escape(gettext('Hello {name},').format(name=name))}</p>"
        f"<p>{html_escape(message)}</p>"
        f"<p>{html_escape(next_step)}</p>"
    )
    payload = json.dumps({
        "from": app.config.get("EMAIL_FROM", "Flutu <noreply@flutu.app>"),
        "to": [recipient_email],
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
        app.logger.warning("Calendar event email delivery failed")


def _event_guest_contacts(event):
    contact_ids = [value for value in event.get("guest_contact_ids", []) if ObjectId.is_valid(value)]
    if not contact_ids:
        return []
    return list(get_collection("contacts").find(
        {"owner_id": event.get("owner_id"), "_id": {"$in": [ObjectId(value) for value in contact_ids]}},
        {"name": 1, "email": 1},
    ))


def _event_member_profile(member):
    profile = {}
    if not member.get("email") and member.get("user_id"):
        profile = get_collection("users").find_one({"_id": member["user_id"]}, {"name": 1, "email": 1}) or {}
    return member.get("email") or profile.get("email", ""), member.get("name") or profile.get("name", "")


def _notify_event_push(app, recipient_ids, title, body, event_url, actor_id):
    required_keys = ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_CONTACT")
    if not all(app.config.get(key) for key in required_keys):
        app.logger.warning("Calendar Web Push skipped because VAPID configuration is incomplete")
        return
    from app.services.push_notifications import notify_users
    result = notify_users(
        app, recipient_ids, title=title, body=body, url=event_url,
        exclude_ids={actor_id},
    ) or {}
    if result.get("failed"):
        app.logger.warning("Calendar Web Push delivery failed for %s subscription(s)", result["failed"])
    elif not result.get("sent") and not result.get("expired"):
        app.logger.info("Calendar Web Push had no active recipient subscriptions")


def _notify_event_members(event, actor_id=None, invitation_ids=(), created=False):
    try:
        from flask import current_app
        app = current_app._get_current_object() if current_app else None
        if app is None:
            return
        owner_id = event.get("owner_id")
        invitation_ids = list(dict.fromkeys(
            user_id for user_id in invitation_ids
            if user_id and user_id != actor_id and user_id != owner_id
        ))
        update_ids = list(dict.fromkeys(
            member.get("user_id")
            for member in event.get("members", [])
            if member.get("user_id") and member.get("status") == "accepted"
            and member.get("user_id") not in invitation_ids
            and member.get("user_id") != actor_id
        ))
        if owner_id and owner_id != actor_id and owner_id not in update_ids:
            update_ids.append(owner_id)
        event_url = f"/calendar?event={event.get('id')}"
        if invitation_ids:
            _notify_event_push(
                app, invitation_ids, "Event invitation",
                "You have a new event invitation.", event_url, actor_id,
            )
        if update_ids:
            _notify_event_push(
                app, update_ids, "Event updated",
                "An event you are a member of was updated.", event_url, actor_id,
            )

        member_ids = set(invitation_ids) | set(update_ids)
        member_emails = set()
        notification_members = list(event.get("members", []))
        if owner_id in update_ids and not any(member.get("user_id") == owner_id for member in notification_members):
            notification_members.append({"user_id": owner_id})
        for member in notification_members:
            user_id = member.get("user_id")
            if not user_id or user_id not in member_ids:
                continue
            email, name = _event_member_profile(member)
            if email:
                member_emails.add(email.casefold())
                _send_event_email(app, event, email, name, invitation=user_id in invitation_ids)

        actor_email = ""
        if actor_id:
            actor = get_collection("users").find_one({"_id": actor_id}, {"email": 1}) or {}
            actor_email = (actor.get("email") or "").casefold()
        for contact in _event_guest_contacts(event):
            email = (contact.get("email") or "").strip()
            if not email or email.casefold() == actor_email or email.casefold() in member_emails:
                continue
            _send_event_email(
                app, event, email, contact.get("name", ""),
                invitation=created, guest=not created,
            )
    except Exception:
        current_app.logger.exception("Event notification dispatch failed")

def _event_payload_changed(previous, normalized):
    fields = (
        "title", "description", "dates", "guest_contact_ids", "conversation_ids",
        "map_points", "members", "cover_image_id", "cover_image_path",
    )
    return any(previous.get(field, [] if field in {"dates", "guest_contact_ids", "conversation_ids", "map_points", "members"} else "")
               != normalized.get(field, [] if field in {"dates", "guest_contact_ids", "conversation_ids", "map_points", "members"} else "")
               for field in fields)


def list_events(user_id):
    rows = _collection().find(_event_access_query(user_id))
    if hasattr(rows, "sort") and not isinstance(rows, list):
        rows = rows.sort("updated_at", DESCENDING)
    return [_serialize(item, user_id=user_id) for item in rows]


def get_event(user_id, event_id):
    if not ObjectId.is_valid(event_id):
        return None
    query = {"_id": ObjectId(event_id), **_event_access_query(user_id)}
    item = _collection().find_one(query)
    return _serialize(item, user_id=user_id) if item else None


def respond_to_invitation(user_id, event_id, action):
    if not ObjectId.is_valid(event_id):
        return None
    if not isinstance(action, str) or action not in {"accept", "decline"}:
        raise ValueError("invalid_invitation_action")
    status = "accepted" if action == "accept" else "declined"
    result = _collection().find_one_and_update(
        {
            "_id": ObjectId(event_id),
            "members": {"$elemMatch": {"user_id": user_id, "status": "pending"}},
        },
        {"$set": {"members.$.status": status, "updated_at": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )
    return _serialize(result, user_id=user_id) if result else None


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
        _notify_event_members(
            {**document, "id": str(event_id)}, owner_id,
            _pending_event_invite_recipients(document), created=True,
        )
    except Exception:
        _cleanup_images(uploaded_paths)
        raise
    return _serialize(document, user_id=owner_id)


def update_event(owner_id, event_id, payload):
    if not ObjectId.is_valid(event_id):
        return None
    collection = _collection()
    previous = collection.find_one({"_id": ObjectId(event_id)})
    if not previous:
        return None
    if not can_manage_event(previous, owner_id):
        raise PermissionError("forbidden")
    is_owner = previous.get("owner_id") == owner_id
    event_owner_id = previous.get("owner_id") or owner_id
    normalized = normalize_event(
        payload, event_owner_id, previous.get("map_points", []),
        {key: previous.get(key) for key in ("cover_image_id", "cover_image_path", "cover_image_content_type")},
        previous.get("members", []),
    )
    if not is_owner:
        normalized["guest_contact_ids"] = previous.get("guest_contact_ids", [])
        normalized["conversation_ids"] = previous.get("conversation_ids", [])
        normalized["members"] = previous.get("members", [])
    changed = _event_payload_changed(previous, normalized)
    previous_pending = set(_pending_event_invite_recipients(previous))
    old_paths = {point.get("image_path") for point in previous.get("map_points", []) if point.get("image_path")}
    if previous.get("cover_image_path"):
        old_paths.add(previous["cover_image_path"])
    uploaded_paths = []
    try:
        uploaded_paths = _store_point_images(event_id, normalized["map_points"])
        uploaded_paths.extend(_store_cover_image(event_id, normalized))
        result = collection.find_one_and_update(
            {"_id": ObjectId(event_id)},
            {"$set": {**normalized, "updated_at": datetime.now(timezone.utc)}, "$unset": {"status": ""}},
            return_document=ReturnDocument.AFTER,
        )
        if result and changed:
            new_pending = set(_pending_event_invite_recipients(result)) - previous_pending
            _notify_event_members({**result, "id": str(event_id)}, owner_id, new_pending)
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
    return _serialize(result, user_id=owner_id) if result else None


def delete_event(owner_id, event_id):
    if not ObjectId.is_valid(event_id):
        return False
    collection = _collection()
    document = collection.find_one({"_id": ObjectId(event_id)})
    if not document or document.get("owner_id") != owner_id:
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
    event = _collection().find_one({"_id": ObjectId(event_id), **_event_access_query(owner_id)}, {"map_points": 1})
    if not event:
        return None
    point = next((item for item in event.get("map_points", []) if item.get("image_id") == normalized_image_id), None)
    if not point or not point.get("image_path"):
        return None
    return blob_storage.download_image(point["image_path"])


def get_event_cover_image(owner_id, event_id):
    if not ObjectId.is_valid(event_id):
        return None
    event = _collection().find_one({"_id": ObjectId(event_id), **_event_access_query(owner_id)}, {"cover_image_path": 1})
    if not event or not event.get("cover_image_path"):
        return None
    return blob_storage.download_image(event["cover_image_path"])


def list_map_points(owner_id, open_only=False):
    query = {"owner_id": owner_id, "map_points.0": {"$exists": True}}
    events = _collection().find(query)
    points = []
    for event in events:
        status = _event_status(event)
        if open_only and status != "open":
            continue
        start_at = _nearest_event_occurrence(event)
        for point_index, point in enumerate(event.get("map_points", [])):
            points.append({
                "event_id": str(event["_id"]),
                "start_at": start_at,
                "point_index": point_index,
                "title": event["title"],
                "description": event.get("description", ""),
                "status": status,
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
    for event in _collection().find(_event_access_query(owner_id)):
        status = _event_status(event)
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
                    "status": status,
                    "start_at": _isoformat(occurrence_start),
                    "end_at": _isoformat(occurrence_start + (base_end - base_start)),
                })
    return sorted(occurrences, key=lambda item: item["start_at"])