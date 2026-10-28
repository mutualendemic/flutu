"""MongoDB-backed Web Push subscriptions and best-effort event delivery."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlsplit
import ipaddress
import json
import logging

from pymongo import ASCENDING

from app.services.mongodb import get_collection


logger = logging.getLogger(__name__)
MAX_SUBSCRIPTIONS_PER_USER = 5
MAX_PUSH_RECIPIENTS = 25
MAX_CONCURRENT_DELIVERIES = 8
MAX_ENDPOINT_LENGTH = 2048
MAX_PAYLOAD_BYTES = 2048
ALLOWED_PUSH_HOSTS = {
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "updates.push.services.mozilla.com",
    "web.push.apple.com",
}


def _subscriptions():
    collection = get_collection("push_subscriptions")
    collection.create_index([("endpoint", ASCENDING)], unique=True)
    collection.create_index([("owner_id", ASCENDING), ("updated_at", ASCENDING)])
    return collection


def validate_endpoint(endpoint):
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > MAX_ENDPOINT_LENGTH:
        raise ValueError("invalid_subscription")
    try:
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            raise ValueError
        if parsed.port not in (None, 443):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        if not any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_PUSH_HOSTS):
            raise ValueError
        if not parsed.path.startswith("/"):
            raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError("invalid_subscription") from None
    return endpoint


def save_subscription(owner_id, payload):
    if not isinstance(owner_id, str) or not owner_id or not isinstance(payload, dict):
        raise ValueError("invalid_subscription")
    endpoint = validate_endpoint(payload.get("endpoint"))
    keys = payload.get("keys")
    if not isinstance(keys, dict):
        raise ValueError("invalid_subscription")
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not isinstance(p256dh, str) or not 16 <= len(p256dh) <= 256:
        raise ValueError("invalid_subscription")
    if not isinstance(auth, str) or not 8 <= len(auth) <= 256:
        raise ValueError("invalid_subscription")

    collection = _subscriptions()
    existing = collection.find_one({"endpoint": endpoint}, {"owner_id": 1})
    if not existing or existing.get("owner_id") != owner_id:
        if collection.count_documents({"owner_id": owner_id}) >= MAX_SUBSCRIPTIONS_PER_USER:
            raise OverflowError("subscription_limit")
    now = datetime.now(timezone.utc)
    collection.update_one(
        {"endpoint": endpoint},
        {
            "$set": {
                "owner_id": owner_id,
                "keys": {"p256dh": p256dh, "auth": auth},
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return True


def remove_subscription(owner_id, endpoint):
    endpoint = validate_endpoint(endpoint)
    result = _subscriptions().delete_one({"owner_id": owner_id, "endpoint": endpoint})
    return result.deleted_count > 0


def _send_one(subscription, payload, config, collection):
    try:
        from pywebpush import WebPushException, webpush

        webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": subscription["keys"],
            },
            data=json.dumps(payload, separators=(",", ":")),
            vapid_private_key=config["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": config["VAPID_CONTACT"]},
            timeout=3,
            ttl=60,
        )
        return "sent"
    except Exception as error:
        response = getattr(error, "response", None)
        if response is not None and getattr(response, "status_code", None) in (404, 410):
            try:
                collection.delete_one({"_id": subscription["_id"]})
            except Exception:
                logger.exception("Could not remove expired Web Push subscription")
            return "expired"
        logger.warning("Web Push delivery failed for a subscription; it remains registered")
        return "failed"


def notify_users(app, recipient_ids, *, title, body, url, exclude_ids=()):
    """Best-effort push for a persisted domain event; never raises to its caller."""
    config = app.config
    if not all(config.get(key) for key in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_CONTACT")):
        return {"sent": 0, "expired": 0, "failed": 0}
    try:
        if not isinstance(title, str) or not title.strip() or len(title) > 80:
            raise ValueError("invalid notification title")
        if not isinstance(body, str) or len(body) > 180:
            raise ValueError("invalid notification body")
        if not isinstance(url, str) or not url.startswith("/") or url.startswith("//") or "\\" in url:
            raise ValueError("invalid notification URL")
        payload = {"title": title.strip(), "body": body, "url": url}
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("notification payload is too large")
        excluded = set(exclude_ids or ())
        recipients = list(dict.fromkeys(
            user_id for user_id in recipient_ids
            if isinstance(user_id, str) and user_id and user_id not in excluded
        ))[:MAX_PUSH_RECIPIENTS]
        if not recipients:
            return {"sent": 0, "expired": 0, "failed": 0}
        collection = _subscriptions()
        subscriptions = list(collection.find({"owner_id": {"$in": recipients}}))
        counts = {"sent": 0, "expired": 0, "failed": 0}
        if not subscriptions:
            return counts
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DELIVERIES) as executor:
            futures = [executor.submit(_send_one, item, payload, config, collection) for item in subscriptions]
            for future in as_completed(futures):
                counts[future.result()] += 1
        return counts
    except Exception:
        logger.exception("Web Push event delivery failed; domain action remains successful")
        return {"sent": 0, "expired": 0, "failed": 0}
