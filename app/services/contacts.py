from datetime import datetime, timezone

from bson import ObjectId
from flask import current_app
from pymongo import ASCENDING, MongoClient


def _collection():
    uri = current_app.config.get("MONGODB_URI")
    if not uri:
        raise RuntimeError("MongoDB is not configured")

    client = current_app.extensions.get("mongodb_client")
    if client is None:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        current_app.extensions["mongodb_client"] = client

    database_name = current_app.config.get("MONGODB_DATABASE", "flutu")
    return client[database_name]["contacts"]


def _serialize(document):
    return {
        "id": str(document["_id"]),
        "name": document["name"],
        "tel": document["tel"],
        "email": document["email"],
    }


def list_contacts(owner_id):
    collection = _collection()
    collection.create_index([("owner_id", ASCENDING), ("created_at", ASCENDING)])
    return [_serialize(item) for item in collection.find({"owner_id": owner_id}).sort("created_at", ASCENDING)]


def add_contacts(owner_id, contacts):
    now = datetime.now(timezone.utc)
    documents = [
        {**contact, "owner_id": owner_id, "created_at": now}
        for contact in contacts
    ]
    result = _collection().insert_many(documents)
    return [
        {"id": str(document_id), "name": contact["name"], "tel": contact["tel"], "email": contact["email"]}
        for document_id, contact in zip(result.inserted_ids, contacts)
    ]


def delete_contact(owner_id, contact_id):
    if not ObjectId.is_valid(contact_id):
        return False
    result = _collection().delete_one({"_id": ObjectId(contact_id), "owner_id": owner_id})
    return result.deleted_count == 1


def delete_all_contacts(owner_id):
    result = _collection().delete_many({"owner_id": owner_id})
    return result.deleted_count