from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING

from app.services.mongodb import get_collection


def _collection():
    return get_collection("contacts")


def _serialize(document):
    return {
        "id": str(document["_id"]),
        "name": document["name"],
        "tel": document["tel"],
        "email": document["email"],
    }


def _serialize_many(documents):
    documents = list(documents)
    emails = {
        (document.get("email") or "").strip().lower()
        for document in documents
        if (document.get("email") or "").strip()
    }
    accounts_by_email = {}
    if emails:
        accounts = get_collection("users").find(
            {"email": {"$in": list(emails)}},
            {"email": 1, "picture": 1},
        )
        accounts_by_email = {
            (account.get("email") or "").strip().lower(): account
            for account in accounts
        }
    result = []
    for document in documents:
        contact = _serialize(document)
        account = accounts_by_email.get((contact["email"] or "").strip().lower())
        contact.update({
            "registered": account is not None,
            "user_id": str(account["_id"]) if account else None,
            "picture": account.get("picture", "") if account else "",
        })
        result.append(contact)
    return result


def list_contacts(owner_id):
    collection = _collection()
    collection.create_index([("owner_id", ASCENDING), ("created_at", ASCENDING)])
    return _serialize_many(collection.find({"owner_id": owner_id}).sort("created_at", ASCENDING))


def add_contacts(owner_id, contacts):
    now = datetime.now(timezone.utc)
    documents = [
        {**contact, "owner_id": owner_id, "created_at": now}
        for contact in contacts
    ]
    result = _collection().insert_many(documents)
    return _serialize_many(
        {**document, "_id": document_id}
        for document_id, document in zip(result.inserted_ids, documents)
    )


def delete_contact(owner_id, contact_id):
    if not ObjectId.is_valid(contact_id):
        return False
    result = _collection().delete_one({"_id": ObjectId(contact_id), "owner_id": owner_id})
    return result.deleted_count == 1


def delete_all_contacts(owner_id):
    result = _collection().delete_many({"owner_id": owner_id})
    return result.deleted_count