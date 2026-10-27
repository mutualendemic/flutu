from datetime import datetime, timezone
import secrets

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.services.mongodb import get_collection
from app.services.quantum_random import choose_direction


DEFAULT_OPTIONS = ["Yes", "No"]
MEMBER_COLORS = [
    "#7F77DD", "#E07A5F", "#3D8B7D", "#D4A72C", "#3973AC", "#B65C9A",
    "#668C3A", "#C75D5D", "#4E9AA8", "#8B6FB1", "#D27B31", "#567D9A",
    "#A45168", "#7A8540", "#6C64A8", "#B06A45", "#3E8064", "#9A6C9A",
    "#A38A32", "#4F7291",
]


def now():
    return datetime.now(timezone.utc)


def _id(value):
    return ObjectId(value) if ObjectId.is_valid(str(value)) else None


def _collections():
    conversations = get_collection("chat_conversations")
    members = get_collection("chat_members")
    questions = get_collection("chat_questions")
    options = get_collection("chat_options")
    answers = get_collection("chat_answers")
    conversations.create_index([("created_by_user_id", ASCENDING), ("created_at", DESCENDING)])
    conversations.create_index([("member_user_ids", ASCENDING), ("last_activity", DESCENDING)])
    members.create_index([("conversation_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
    members.create_index([("user_id", ASCENDING), ("left_at", ASCENDING)])
    questions.create_index([("conversation_id", ASCENDING), ("created_at", ASCENDING)])
    questions.create_index([("parent_option_id", ASCENDING)])
    options.create_index([("question_id", ASCENDING), ("position", ASCENDING)], unique=True)
    options.create_index([("question_id", ASCENDING), ("label_lower", ASCENDING)], unique=True)
    answers.create_index([("question_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
    answers.create_index([("option_id", ASCENDING)])
    return conversations, members, questions, options, answers


def validate_question(text, labels):
    if not isinstance(text, str):
        raise ValueError("invalid_text")
    text = text.strip()
    if not text or len(text) > 280:
        raise ValueError("invalid_text")
    if labels is None:
        labels = DEFAULT_OPTIONS
    if not isinstance(labels, list) or not 2 <= len(labels) <= 10:
        raise ValueError("invalid_option_count")
    normalized = []
    seen = set()
    for label in labels:
        if not isinstance(label, str):
            raise ValueError("invalid_option")
        label = label.strip()
        key = label.casefold()
        if not label or len(label) > 60 or key in seen:
            raise ValueError("invalid_option")
        seen.add(key)
        normalized.append(label)
    return text, normalized


def _serialize_member(document):
    return {
        "user_id": document["user_id"],
        "name": document.get("name", "Former member"),
        "picture": document.get("picture", ""),
        "color": document.get("color", "#8A8F98"),
        "role": document.get("role", "member"),
        "active": document.get("left_at") is None,
        "joined_at": document.get("joined_at"),
    }


def is_active_member(conversation_id, user_id):
    cid = _id(conversation_id)
    if cid is None:
        return False
    conversations, members, *_ = _collections()
    if conversations.find_one({"_id": cid, "deleted_at": None}, {"_id": 1}) is None:
        return False
    return members.find_one({"conversation_id": cid, "user_id": user_id, "left_at": None}, {"_id": 1}) is not None


def get_conversation(conversation_id):
    cid = _id(conversation_id)
    if cid is None:
        return None
    conversations, *_ = _collections()
    return conversations.find_one({"_id": cid, "deleted_at": None})


def addable_contacts(user_id, conversation_id=None):
    contacts = list(get_collection("contacts").find({"owner_id": user_id}).sort("created_at", ASCENDING))
    users = get_collection("users")
    existing = set()
    if conversation_id:
        cid = _id(conversation_id)
        if cid:
            _, members, *_ = _collections()
            existing = {item["user_id"] for item in members.find({"conversation_id": cid, "left_at": None})}
    result = []
    seen = set()
    for contact in contacts:
        email = (contact.get("email") or "").strip().lower()
        account = users.find_one({"email": email}) if email else None
        linked_id = account.get("_id") if account else None
        if linked_id == user_id or (linked_id and linked_id in seen):
            continue
        if linked_id:
            seen.add(linked_id)
        result.append({
            "id": str(contact["_id"]),
            "name": contact.get("name", ""),
            "email": email,
            "user_id": linked_id,
            "account_name": account.get("name") if account else None,
            "addable": bool(linked_id and linked_id not in existing),
        })
    return result


def _member_snapshot(user_id):
    user = get_collection("users").find_one(
        {"_id": user_id}, {"name": 1, "email": 1, "picture": 1}
    ) or {}
    return {
        "name": user.get("name") or user.get("email") or "Flutu member",
        "picture": user.get("picture", ""),
    }


def _assign_color(members, conversation_id):
    used = {item.get("color") for item in members.find({"conversation_id": conversation_id, "left_at": None})}
    for color in MEMBER_COLORS:
        if color not in used:
            return color
    # Expand the fixed palette without reusing a color in unusually large conversations.
    while True:
        color = "#" + secrets.token_hex(3).upper()
        if color not in used:
            return color


def _add_member(conversation_id, user_id, role="member"):
    _, members, *_ = _collections()
    existing = members.find_one({"conversation_id": conversation_id, "user_id": user_id})
    if existing and existing.get("left_at") is None:
        return _serialize_member(existing), False
    now_value = now()
    color = existing.get("color") if existing else _assign_color(members, conversation_id)
    document = {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "role": role,
        **_member_snapshot(user_id),
        "color": color,
        "joined_at": now_value,
        "left_at": None,
    }
    if existing:
        members.update_one({"_id": existing["_id"]}, {"$set": document})
        saved = members.find_one({"_id": existing["_id"]})
    else:
        saved = {**document, "_id": ObjectId()}
        try:
            members.insert_one(saved)
        except DuplicateKeyError:
            saved = members.find_one({"conversation_id": conversation_id, "user_id": user_id})
    return _serialize_member(saved), True


def create_conversation(owner_id, title, member_user_ids=None):
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 100:
        raise ValueError("invalid_title")
    member_user_ids = member_user_ids or []
    if not isinstance(member_user_ids, list) or len(member_user_ids) > 20 or any(not isinstance(x, str) for x in member_user_ids):
        raise ValueError("invalid_members")
    conversations, *_ = _collections()
    addable = {item["user_id"] for item in addable_contacts(owner_id) if item["user_id"]}
    requested = list(dict.fromkeys(member_user_ids))
    if any(user_id not in addable for user_id in requested):
        raise ValueError("members_must_be_contacts")
    timestamp = now()
    doc = {
        "title": title.strip(), "created_by_user_id": owner_id,
        "created_at": timestamp, "last_activity": timestamp, "archived_at": None,
    }
    inserted = conversations.insert_one(doc)
    conversation_id = inserted.inserted_id
    conversations.update_one({"_id": conversation_id}, {"$set": {"member_user_ids": [owner_id, *requested]}})
    _add_member(conversation_id, owner_id, "owner")
    for user_id in requested:
        _add_member(conversation_id, user_id)
    return str(conversation_id)


def list_conversations(user_id):
    conversations, members, questions, answers = _collections()[0:3] + (_collections()[4],)
    rows = conversations.find({"member_user_ids": user_id, "archived_at": None, "deleted_at": None}).sort("last_activity", DESCENDING)
    result = []
    for conversation in rows:
        cid = conversation["_id"]
        member_docs = list(members.find({"conversation_id": cid}))
        open_questions = list(questions.find({"conversation_id": cid, "status": "open"}, {"_id": 1}))
        unanswered = 0
        for question in open_questions:
            if not answers.find_one({"question_id": question["_id"], "user_id": user_id}, {"_id": 1}):
                unanswered += 1
        result.append({
            "id": str(cid), "title": conversation["title"],
            "is_owner": conversation.get("created_by_user_id") == user_id,
            "last_activity": conversation.get("last_activity"),
            "members": [_serialize_member(item) for item in member_docs],
            "unanswered_count": unanswered,
        })
    return result


def get_active_members(conversation_id):
    _, members, *_ = _collections()
    cid = _id(conversation_id)
    if cid is None:
        return []
    return [_serialize_member(item) for item in members.find({"conversation_id": cid, "left_at": None})]


def _depth(question, options, cache):
    qid = question["_id"]
    if qid in cache:
        return cache[qid]
    parent_option = question.get("parent_option_id")
    if not parent_option:
        cache[qid] = 0
        return 0
    parent = options.find_one({"_id": parent_option})
    parent_question = get_collection("chat_questions").find_one({"_id": parent["question_id"]}) if parent else None
    value = 1 + (_depth(parent_question, options, cache) if parent_question else 0)
    cache[qid] = value
    return value


def create_question(conversation_id, author_id, text, labels=None, parent_option_id=None, allow_vote_change=True):
    text, labels = validate_question(text, labels)
    if not isinstance(allow_vote_change, bool):
        raise ValueError("invalid_allow_vote_change")
    cid = _id(conversation_id)
    if cid is None:
        raise ValueError("not_found")
    conversations, _, questions, options, _ = _collections()
    conversation = conversations.find_one({"_id": cid, "archived_at": None, "deleted_at": None})
    if not conversation:
        raise ValueError("not_found")
    parent = None
    if parent_option_id is not None:
        oid = _id(parent_option_id)
        parent = options.find_one({"_id": oid, "conversation_id": cid}) if oid else None
        if not parent:
            raise ValueError("invalid_parent_option")
        parent_question = questions.find_one({"_id": parent["question_id"], "conversation_id": cid})
        if not parent_question or _depth(parent_question, options, {}) >= 3:
            raise ValueError("max_depth")
        selected = _quantum_path_for_question(parent["question_id"])
        if not selected or selected["_id"] != parent["_id"]:
            raise ValueError("quantum_path_locked")
        parent_option_id = oid
    else:
        if author_id != conversation.get("created_by_user_id"):
            raise PermissionError("forbidden")
        if questions.find_one({"conversation_id": cid, "parent_option_id": None}, {"_id": 1}):
            raise ValueError("root_question_exists")
    timestamp = now()
    doc = {
        "conversation_id": cid, "author_user_id": author_id, "text": text,
        "parent_option_id": parent_option_id, "status": "open",
        "allow_vote_change": allow_vote_change, "winning_option_id": None,
        "created_at": timestamp, "closed_at": None,
    }
    qid = questions.insert_one(doc).inserted_id
    option_docs = []
    for position, label in enumerate(labels):
        option_doc = {
            "question_id": qid, "conversation_id": cid, "label": label,
            "label_lower": label.casefold(), "position": position, "created_at": timestamp,
        }
        option_docs.append({**option_doc, "_id": ObjectId()})
    if option_docs:
        options.insert_many(option_docs)
    conversations.update_one({"_id": cid}, {"$set": {"last_activity": timestamp}})
    return str(qid)


def _winning_option(question_id, preferred=None):
    _, _, _, options, answers = _collections()
    option_docs = list(options.find({"question_id": question_id}).sort("position", ASCENDING))
    counts = {str(option["_id"]): answers.count_documents({"question_id": question_id, "option_id": option["_id"]}) for option in option_docs}
    if preferred and str(preferred) in counts:
        top = max(counts.values(), default=0)
        tied = [oid for oid, count in counts.items() if count == top]
        if len(tied) > 1 and str(preferred) in tied:
            return _id(preferred)
        raise ValueError("winner_must_be_tied")
    top = max(counts.values(), default=0)
    winners = [oid for oid, count in counts.items() if count == top]
    return _id(winners[0]) if len(winners) == 1 else None


def _close(question, preferred=None):
    _, _, questions, _, _ = _collections()
    winner = _winning_option(question["_id"], preferred)
    closed_at = now()
    updated = questions.find_one_and_update(
        {"_id": question["_id"], "status": "open"},
        {"$set": {"status": "closed", "winning_option_id": winner, "closed_at": closed_at}},
        return_document=ReturnDocument.AFTER,
    )
    return updated


def close_question(question_id, user_id, winning_option_id=None):
    qid = _id(question_id)
    if qid is None:
        raise ValueError("not_found")
    _, _, questions, _, _ = _collections()
    question = questions.find_one({"_id": qid})
    if not question:
        raise ValueError("not_found")
    conversation = get_conversation(question["conversation_id"])
    if user_id not in (question["author_user_id"], conversation.get("created_by_user_id")):
        raise PermissionError("forbidden")
    if question["status"] != "open":
        raise ValueError("already_closed")
    return _close(question, winning_option_id)


def _auto_close_if_complete(question_id):
    _, members, questions, _, answers = _collections()
    question = questions.find_one({"_id": question_id, "status": "open"})
    if not question:
        return None
    active_count = members.count_documents({"conversation_id": question["conversation_id"], "left_at": None})
    answered_count = answers.count_documents({"question_id": question_id, "user_id": {"$in": [m["user_id"] for m in members.find({"conversation_id": question["conversation_id"], "left_at": None}, {"user_id": 1})]}})
    return _close(question) if active_count and answered_count >= active_count else None


def _quantum_path_for_question(question_id):
    qid = _id(question_id)
    if qid is None:
        return None
    _, _, questions, options, _ = _collections()
    question = questions.find_one({"_id": qid})
    if not question:
        return None
    candidates = list(options.find({"question_id": qid}).sort("position", ASCENDING))
    if not candidates:
        return None
    candidate_ids = [option["_id"] for option in candidates]
    selected_id = question.get("quantum_selected_option_id")
    existing = next((option for option in candidates if option["_id"] == selected_id), None)
    if existing:
        return existing
    if len(candidates) == 1:
        selected = candidates[0]
    else:
        bits_needed = (len(candidates) - 1).bit_length()
        while True:
            index = 0
            for _ in range(bits_needed):
                index = (index << 1) | int(choose_direction())
            if index < len(candidates):
                selected = candidates[index]
                break
    questions.update_one(
        {
            "_id": qid,
            "$or": [
                {"quantum_selected_option_id": {"$exists": False}},
                {"quantum_selected_option_id": {"$nin": candidate_ids}},
            ],
        },
        {"$set": {"quantum_selected_option_id": selected["_id"]}},
    )
    saved = questions.find_one({"_id": qid}, {"quantum_selected_option_id": 1}) or {}
    saved_id = saved.get("quantum_selected_option_id")
    return next((option for option in candidates if option["_id"] == saved_id), selected)


def submit_answer(question_id, user_id, option_id):
    qid, oid = _id(question_id), _id(option_id)
    if qid is None or oid is None:
        raise ValueError("not_found")
    _, _, questions, options, answers = _collections()
    question = questions.find_one({"_id": qid})
    option = options.find_one({"_id": oid, "question_id": qid})
    if not question or not option:
        raise ValueError("invalid_option")
    if question["status"] != "open":
        raise ValueError("closed_question")
    quantum_choice = _quantum_path_for_question(question_id)
    if quantum_choice and str(quantum_choice["_id"]) != str(oid):
        raise ValueError("quantum_path_locked")
    existing = answers.find_one({"question_id": qid, "user_id": user_id})
    if existing and existing["option_id"] == oid:
        return {"changed": False, "previous_option_id": str(oid), "closed": False}
    if existing and not question.get("allow_vote_change", True):
        raise ValueError("vote_change_disabled")
    timestamp = now()
    try:
        answers.update_one(
            {"question_id": qid, "user_id": user_id},
            {"$set": {"option_id": oid, "updated_at": timestamp}, "$setOnInsert": {"answered_at": timestamp}},
            upsert=True,
        )
    except DuplicateKeyError:
        # The unique (question, user) index serializes concurrent first votes.
        answers.update_one({"question_id": qid, "user_id": user_id}, {"$set": {"option_id": oid, "updated_at": timestamp}})
    previous = str(existing["option_id"]) if existing else None
    closed = _auto_close_if_complete(qid)
    return {"changed": True, "previous_option_id": previous, "closed": bool(closed)}


def add_members(conversation_id, owner_id, user_ids):
    cid = _id(conversation_id)
    if cid is None or not isinstance(user_ids, list) or len(user_ids) > 20 or any(not isinstance(x, str) for x in user_ids):
        raise ValueError("invalid_members")
    conversation = get_conversation(cid)
    if not conversation:
        raise ValueError("not_found")
    if conversation["created_by_user_id"] != owner_id:
        raise PermissionError("forbidden")
    allowed = {item["user_id"] for item in addable_contacts(owner_id) if item["user_id"]}
    # Existing former members are eligible to rejoin if they remain a saved contact.
    _, members, *_ = _collections()
    allowed |= {item["user_id"] for item in members.find({"conversation_id": cid, "left_at": {"$ne": None}})}
    requested = list(dict.fromkeys(user_ids))
    if any(user_id not in allowed for user_id in requested):
        raise ValueError("members_must_be_contacts")
    added = []
    for uid in requested:
        member, changed = _add_member(cid, uid)
        if changed:
            added.append(member)
    get_collection("chat_conversations").update_one({"_id": cid}, {"$addToSet": {"member_user_ids": {"$each": requested}}, "$set": {"last_activity": now()}})
    return added


def remove_member(conversation_id, actor_id, target_id):
    cid = _id(conversation_id)
    if cid is None:
        raise ValueError("not_found")
    conversation = get_conversation(cid)
    if not conversation:
        raise ValueError("not_found")
    if actor_id != target_id and actor_id != conversation["created_by_user_id"]:
        raise PermissionError("forbidden")
    if target_id == conversation["created_by_user_id"]:
        raise ValueError("owner_cannot_leave")
    _, members, *_ = _collections()
    updated = members.find_one_and_update(
        {"conversation_id": cid, "user_id": target_id, "left_at": None},
        {"$set": {"left_at": now()}}, return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise ValueError("not_found")
    get_collection("chat_conversations").update_one({"_id": cid}, {"$pull": {"member_user_ids": target_id}, "$set": {"last_activity": now()}})
    return _serialize_member(updated)


def delete_conversation(conversation_id, actor_id):
    """Permanently remove a conversation and its content; only its creator may do so."""
    cid = _id(conversation_id)
    if cid is None:
        raise ValueError("not_found")
    conversations, members, questions, options, answers = _collections()
    conversation = conversations.find_one({"_id": cid})
    if not conversation:
        raise ValueError("not_found")
    if conversation.get("created_by_user_id") != actor_id:
        raise PermissionError("forbidden")

    # Mark first: all access checks deny this conversation before cascading deletes.
    if conversation.get("deleted_at") is None:
        conversation = conversations.find_one_and_update(
            {"_id": cid, "created_by_user_id": actor_id, "deleted_at": None},
            {"$set": {"deleted_at": now()}},
            return_document=ReturnDocument.AFTER,
        )
        if conversation is None:
            raise ValueError("not_found")

    member_ids = list(conversation.get("member_user_ids", []))
    question_ids = [item["_id"] for item in questions.find({"conversation_id": cid}, {"_id": 1})]
    if question_ids:
        answers.delete_many({"question_id": {"$in": question_ids}})
    options.delete_many({"conversation_id": cid})
    questions.delete_many({"conversation_id": cid})
    members.delete_many({"conversation_id": cid})
    conversations.delete_one({"_id": cid, "deleted_at": {"$ne": None}})
    return member_ids


def edit_question(question_id, author_id, text=None, labels=None):
    qid = _id(question_id)
    _, _, questions, options, answers = _collections()
    question = questions.find_one({"_id": qid}) if qid else None
    if not question:
        raise ValueError("not_found")
    if question["author_user_id"] != author_id:
        raise PermissionError("forbidden")
    if answers.count_documents({"question_id": qid}):
        raise ValueError("question_has_answers")
    if question["status"] != "open":
        raise ValueError("closed_question")
    update = {}
    if text is not None:
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 280:
            raise ValueError("invalid_text")
        update["text"] = text.strip()
    if labels is not None:
        _, cleaned = validate_question(question.get("text", "Question"), labels)
        options.delete_many({"question_id": qid})
        options.insert_many([{
            "question_id": qid, "conversation_id": question["conversation_id"], "label": label,
            "label_lower": label.casefold(), "position": index, "created_at": now(),
        } for index, label in enumerate(cleaned)])
    if update:
        questions.update_one({"_id": qid}, {"$set": update})
    return str(qid)


def delete_question(question_id, author_id):
    qid = _id(question_id)
    _, _, questions, options, answers = _collections()
    question = questions.find_one({"_id": qid}) if qid else None
    if not question:
        raise ValueError("not_found")
    if question["author_user_id"] != author_id:
        raise PermissionError("forbidden")
    if answers.count_documents({"question_id": qid}):
        raise ValueError("question_has_answers")
    options.delete_many({"question_id": qid})
    questions.delete_one({"_id": qid})
    return str(question["conversation_id"])


def graph_payload(conversation_id, viewer_id=None):
    cid = _id(conversation_id)
    conversation = get_conversation(cid) if cid else None
    if not conversation:
        raise ValueError("not_found")
    _, members, questions, options, answers = _collections()
    member_docs = list(members.find({"conversation_id": cid}))
    member_by_id = {item["user_id"]: _serialize_member(item) for item in member_docs}
    question_docs = list(questions.find({"conversation_id": cid}).sort([("created_at", ASCENDING), ("_id", ASCENDING)]))
    has_root_question = any(not question.get("parent_option_id") for question in question_docs)
    option_docs = list(options.find({"conversation_id": cid}).sort([("position", ASCENDING), ("_id", ASCENDING)]))
    options_by_question = {}
    for option in option_docs:
        options_by_question.setdefault(option["question_id"], []).append(option)
    answer_docs = list(answers.find({"question_id": {"$in": [q["_id"] for q in question_docs]}})) if question_docs else []
    answers_by_option = {}
    for answer in answer_docs:
        answers_by_option.setdefault(answer["option_id"], []).append(answer)
    quantum_choices = {}
    for question in question_docs:
        question_options = options_by_question.get(question["_id"], [])
        if question_options:
            quantum_choices[question["_id"]] = _quantum_path_for_question(question["_id"]) or question_options[0]
    depth_cache = {}
    qmeta, nodes, edges = {}, [], []
    cursor_row = 0
    for question in question_docs:
        depth = _depth(question, options, depth_cache)
        parent = options.find_one({"_id": question.get("parent_option_id")}) if question.get("parent_option_id") else None
        lane = depth if not parent else qmeta.get(parent["question_id"], {}).get("lane", 0) + 1
        row = cursor_row
        qmeta[question["_id"]] = {"lane": lane, "row": row, "depth": depth}
        qid = str(question["_id"])
        selected_option = quantum_choices.get(question["_id"])
        nodes.append({
            "id": f"q{qid}", "type": "question", "label": question["text"],
            "status": question["status"], "author_user_id": question["author_user_id"],
            "author_name": member_by_id.get(question["author_user_id"], {}).get("name", "Former member"),
            "author_picture": member_by_id.get(question["author_user_id"], {}).get("picture", ""),
            "lane": lane, "row": row, "winning_option_id": str(question["winning_option_id"]) if question.get("winning_option_id") else None,
            "created_at": question["created_at"].isoformat(), "allow_vote_change": question.get("allow_vote_change", True),
            "quantum_selected_option_id": str(selected_option["_id"]) if selected_option else None,
        })
        if parent:
            edges.append({"from": f"o{parent['_id']}", "to": f"q{qid}", "kind": "follow_up"})
        question_options = options_by_question.get(question["_id"], [])
        for index, option in enumerate(question_options):
            option_answers = answers_by_option.get(option["_id"], [])
            option_lane = lane + index + 1
            option_row = row
            oid = str(option["_id"])
            quantum_selected = bool(selected_option and selected_option["_id"] == option["_id"])
            nodes.append({
                "id": f"o{oid}", "type": "option", "label": option["label"],
                "question_id": str(question["_id"]), "option_id": oid,
                "lane": option_lane, "row": option_row, "count": len(option_answers),
                "voter_user_ids": [answer["user_id"] for answer in option_answers],
                "voter_names": [member_by_id.get(answer["user_id"], {"name": "Former member"})["name"] for answer in option_answers],
                "is_winner": bool(question.get("winning_option_id") == option["_id"]),
                "is_my_vote": any(answer["user_id"] == viewer_id for answer in option_answers),
                "is_tied": question.get("status") == "closed" and not question.get("winning_option_id") and len(question_options) > 1 and len(option_answers) == max((len(answers_by_option.get(item["_id"], [])) for item in question_options), default=0),
                "quantum_selected": quantum_selected,
            })
            edges.append({"from": f"q{qid}", "to": f"o{oid}", "kind": "branch"})
        cursor_row = row + len(question_options) + 2
    # Main-thread continuity and close/merge edges are deterministic across clients.
    main_questions = [q for q in question_docs if not q.get("parent_option_id")]
    for index, question in enumerate(main_questions[:-1]):
        edges.append({"from": f"q{question['_id']}", "to": f"q{main_questions[index + 1]['_id']}", "kind": "main_thread"})
    for question in question_docs:
        if question.get("status") != "closed":
            continue
        opts = options_by_question.get(question["_id"], [])
        if not opts:
            continue
        next_question = None
        if question.get("parent_option_id"):
            parent_option = options.find_one({"_id": question["parent_option_id"]})
            siblings = [q for q in question_docs if q.get("parent_option_id") == question.get("parent_option_id") and q["created_at"] > question["created_at"]]
            if siblings:
                next_question = siblings[0]
            elif parent_option:
                parent_question = next((q for q in question_docs if q["_id"] == parent_option["question_id"]), None)
                next_question = next((q for q in main_questions if parent_question and q["created_at"] > parent_question["created_at"]), None)
        else:
            next_question = next((q for q in main_questions if q["created_at"] > question["created_at"]), None)
        if next_question:
            edges.append({"from": f"o{opts[-1]['_id']}", "to": f"q{next_question['_id']}", "kind": "merge"})
        else:
            marker_id = f"end{question['_id']}"
            nodes.append({"id": marker_id, "type": "end", "label": "End", "lane": qmeta[question["_id"]]["lane"], "row": qmeta[question["_id"]]["row"] + len(opts) + 1})
            edges.append({"from": f"o{opts[-1]['_id']}", "to": marker_id, "kind": "merge"})
    return {
        "conversation_id": str(cid), "title": conversation["title"],
        "members": [_serialize_member(item) for item in member_docs], "nodes": nodes, "edges": edges,
        "branch_mode": "quantum_random",
        "can_create_initial_question": not has_root_question and conversation.get("created_by_user_id") == viewer_id,
        "can_manage_members": conversation.get("created_by_user_id") == viewer_id,
    }


def question_event_payload(conversation_id, question_id):
    graph = graph_payload(conversation_id)
    qid = str(question_id)
    question_node = next(node for node in graph["nodes"] if node["id"] == f"q{qid}")
    option_ids = {node["id"] for node in graph["nodes"] if node.get("question_id") == qid}
    relevant_ids = {f"q{qid}", *option_ids}
    return {
        "question": question_node,
        "options": [node for node in graph["nodes"] if node["id"] in option_ids],
        "edges": [edge for edge in graph["edges"] if edge["from"] in relevant_ids or edge["to"] in relevant_ids],
    }


def answer_counts(question_id):
    qid = _id(question_id)
    _, _, _, options, answers = _collections()
    return {str(option["_id"]): answers.count_documents({"question_id": qid, "option_id": option["_id"]}) for option in options.find({"question_id": qid})}


def question_by_id(question_id):
    qid = _id(question_id)
    if qid is None:
        return None
    _, _, questions, *_ = _collections()
    return questions.find_one({"_id": qid})


def member_by_id(conversation_id, user_id):
    cid = _id(conversation_id)
    if cid is None:
        return None
    _, members, *_ = _collections()
    doc = members.find_one({"conversation_id": cid, "user_id": user_id})
    return _serialize_member(doc) if doc else None
