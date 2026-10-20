from datetime import datetime, timedelta, timezone
import re

from bson import ObjectId
from pymongo import ASCENDING, GEOSPHERE, ReturnDocument

from app.services.mongodb import get_collection


def _now():
    return datetime.now(timezone.utc)


def register_user(user):
    users = get_collection("users")
    users.create_index([("email", ASCENDING)], unique=True)
    users.update_one(
        {"_id": user["sub"]},
        {"$set": {"email": user["email"].strip().lower(), "name": user["name"], "updated_at": _now()}},
        upsert=True,
    )


def find_user_by_email(email):
    user = get_collection("users").find_one({"email": email.strip().lower()})
    if not user:
        return None
    return {"id": user["_id"], "email": user["email"], "name": user["name"]}


def _shares():
    collection = get_collection("location_shares")
    collection.create_index(
        [("requester_id", ASCENDING), ("recipient_id", ASCENDING)], unique=True
    )
    collection.create_index([("recipient_id", ASCENDING), ("status", ASCENDING)])
    collection.create_index([("requester_id", ASCENDING), ("status", ASCENDING)])
    return collection


def get_sharing_status(user_id):
    active_count = _shares().count_documents({"recipient_id": user_id, "status": "accepted"})
    users = get_collection("users")
    user = users.find_one({"_id": user_id}, {"location_sharing_enabled": 1}) or {}
    enabled = bool(active_count and user.get("location_sharing_enabled", False))
    if not active_count and user.get("location_sharing_enabled", False):
        users.update_one({"_id": user_id}, {"$set": {"location_sharing_enabled": False}})
        get_collection("locations").delete_one({"owner_id": user_id})
    return {"enabled": enabled, "active_recipients": active_count}


def set_sharing_enabled(user_id, enabled):
    status = get_sharing_status(user_id)
    if enabled and not status["active_recipients"]:
        return False
    get_collection("users").update_one(
        {"_id": user_id},
        {"$set": {"location_sharing_enabled": bool(enabled)}},
        upsert=True,
    )
    if not enabled:
        get_collection("locations").delete_one({"owner_id": user_id})
    return True


def _serialize_request(document):
    return {
        "id": str(document["_id"]),
        "status": document["status"],
        "requester_id": document["requester_id"],
        "requester_name": document["requester_name"],
        "requester_email": document["requester_email"],
        "recipient_id": document["recipient_id"],
        "recipient_name": document["recipient_name"],
        "recipient_email": document["recipient_email"],
        "updated_at": document["updated_at"].isoformat(),
    }


def request_location(requester, recipient):
    shares = _shares()
    existing = shares.find_one(
        {"requester_id": requester["sub"], "recipient_id": recipient["id"]}
    )
    if existing and existing["status"] in ("pending", "accepted"):
        return _serialize_request(existing), False

    now = _now()
    document = shares.find_one_and_update(
        {"requester_id": requester["sub"], "recipient_id": recipient["id"]},
        {
            "$set": {
                "requester_name": requester["name"],
                "requester_email": requester["email"],
                "recipient_name": recipient["name"],
                "recipient_email": recipient["email"],
                "status": "pending",
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return _serialize_request(document), True


def _ensure_requester_contact(request):
    contacts = get_collection("contacts")
    existing = contacts.find_one(
        {
            "owner_id": request["recipient_id"],
            "email": {"$regex": f"^{re.escape(request['requester_email'])}$", "$options": "i"},
        }
    )
    if existing:
        return
    contacts.insert_one(
        {
            "owner_id": request["recipient_id"],
            "name": request["requester_name"],
            "email": request["requester_email"],
            "tel": "",
            "created_at": _now(),
        }
    )


def respond_to_request(user_id, request_id, action):
    if not ObjectId.is_valid(request_id):
        return None
    shares = _shares()
    document = shares.find_one({"_id": ObjectId(request_id)})
    if not document:
        return None

    if action in ("accept", "decline"):
        if document["recipient_id"] != user_id or document["status"] != "pending":
            return None
        if action == "accept":
            _ensure_requester_contact(document)
        new_status = "accepted" if action == "accept" else "declined"
        updated = shares.find_one_and_update(
            {"_id": document["_id"], "recipient_id": user_id, "status": "pending"},
            {"$set": {"status": new_status, "updated_at": _now()}},
            return_document=ReturnDocument.AFTER,
        )
        return _serialize_request(updated) if updated else None

    if action == "cancel":
        updated = shares.find_one_and_update(
            {"_id": document["_id"], "requester_id": user_id, "status": "pending"},
            {"$set": {"status": "cancelled", "updated_at": _now()}},
            return_document=ReturnDocument.AFTER,
        )
        return _serialize_request(updated) if updated else None
    return None


def get_overview(user_id):
    shares = _shares()
    pending = shares.find({"recipient_id": user_id, "status": "pending"}).sort("updated_at", -1)
    outgoing_pending = shares.find({"requester_id": user_id, "status": "pending"}).sort("updated_at", -1)
    sharing = shares.find({"recipient_id": user_id, "status": "accepted"}).sort("updated_at", -1)
    received = list(shares.find({"requester_id": user_id, "status": "accepted"}))
    recipient_ids = [item["recipient_id"] for item in received]
    locations = {}
    if recipient_ids:
        collection = get_collection("locations")
        collection.create_index([("location", GEOSPHERE)])
        locations = {
            item["owner_id"]: item
            for item in collection.find(
                {
                    "owner_id": {"$in": recipient_ids},
                    "updated_at": {"$gte": _now() - timedelta(seconds=120)},
                }
            )
        }

    visible_locations = []
    for share in received:
        location = locations.get(share["recipient_id"])
        if not location:
            continue
        coordinates = location["location"]["coordinates"]
        visible_locations.append(
            {
                "user_id": share["recipient_id"],
                "name": share["recipient_name"],
                "latitude": coordinates[1],
                "longitude": coordinates[0],
                "accuracy": location["accuracy"],
                "updated_at": location["updated_at"].isoformat(),
            }
        )

    return {
        "incoming_requests": [_serialize_request(item) for item in pending],
        "outgoing_pending": [_serialize_request(item) for item in outgoing_pending],
        "sharing_with": [_serialize_request(item) for item in sharing],
        "locations": visible_locations,
        "sharing_status": get_sharing_status(user_id),
    }


def save_location(user_id, latitude, longitude, accuracy):
    shares = _shares()
    if not shares.find_one({"recipient_id": user_id, "status": "accepted"}, {"_id": 1}):
        return False
    user = get_collection("users").find_one(
        {"_id": user_id}, {"location_sharing_enabled": 1}
    )
    if not user or not user.get("location_sharing_enabled", False):
        return False
    locations = get_collection("locations")
    locations.create_index([("owner_id", ASCENDING)], unique=True)
    locations.create_index([("location", GEOSPHERE)])
    locations.create_index([("updated_at", ASCENDING)], expireAfterSeconds=180)
    locations.update_one(
        {"owner_id": user_id},
        {
            "$set": {
                "location": {"type": "Point", "coordinates": [longitude, latitude]},
                "accuracy": accuracy,
                "updated_at": _now(),
            }
        },
        upsert=True,
    )
    return True


def revoke_share(user_id, request_id=None):
    shares = _shares()
    if request_id is None:
        result = shares.update_many(
            {"recipient_id": user_id, "status": "accepted"},
            {"$set": {"status": "revoked", "updated_at": _now()}},
        )
        revoked = result.modified_count
    else:
        if not ObjectId.is_valid(request_id):
            return 0
        result = shares.update_one(
            {"_id": ObjectId(request_id), "recipient_id": user_id, "status": "accepted"},
            {"$set": {"status": "revoked", "updated_at": _now()}},
        )
        revoked = result.modified_count

    if revoked and not shares.find_one({"recipient_id": user_id, "status": "accepted"}, {"_id": 1}):
        get_collection("users").update_one(
            {"_id": user_id}, {"$set": {"location_sharing_enabled": False}}
        )
        get_collection("locations").delete_one({"owner_id": user_id})
    return revoked
