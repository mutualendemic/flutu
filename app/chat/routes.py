import hmac
import secrets

from flask import current_app, jsonify, redirect, render_template, request, session, url_for
from pymongo.errors import PyMongoError

from app.auth.decorators import login_required
from app.chat import chat_bp
from app.chat.sockets import emit_to_active_members, emit_to_user
from app.services import chat as service
from app.services.supabase_realtime import (
    TOKEN_TTL_SECONDS,
    conversation_topic,
    create_access_token,
    user_topic,
)


def _user_id():
    return session["user"]["sub"]


def _api_error(code, status=400):
    return jsonify(error=code), status


def _valid_csrf():
    expected = session.get("_csrf_token", "")
    supplied = request.headers.get("X-CSRF-Token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return False
    origin = request.headers.get("Origin")
    if origin:
        return origin == request.host_url.rstrip("/")
    referer = request.headers.get("Referer")
    return not referer or referer.startswith(request.host_url)


@chat_bp.before_request
def protect_chat_api():
    if request.path.startswith("/chat/api/"):
        if not session.get("user"):
            return jsonify(error="Authentication required."), 401
        if request.method in {"POST", "PATCH", "PUT", "DELETE"} and not _valid_csrf():
            return jsonify(error="csrf_failed"), 400


@chat_bp.app_context_processor
def csrf_context():
    def csrf_token():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token
    return {
        "csrf_token": csrf_token,
        "chat_realtime_mode": current_app.config.get("CHAT_REALTIME_MODE", "socketio"),
    }


def _status_for_error(error):
    if str(error) == "not_found":
        return 404
    if str(error) in {"forbidden", "members_must_be_contacts", "branch_mode_locked"}:
        return 403
    if str(error) in {"already_closed", "question_has_answers", "closed_question", "vote_change_disabled", "winner_must_be_tied", "quantum_path_locked", "root_question_exists"}:
        return 409
    return 400


@chat_bp.get("/")
@login_required
def conversation_list_page():
    return render_template("chat_list.html", user=session["user"])


@chat_bp.get("/<conversation_id>")
@login_required
def conversation_page(conversation_id):
    try:
        if not service.is_active_member(conversation_id, _user_id()):
            return "Not found", 404
        return render_template("chat_conversation.html", user=session["user"], conversation_id=conversation_id)
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not load chat conversation")
        return "Chat is temporarily unavailable", 503


@chat_bp.get("/api/conversations")
def api_conversations():
    try:
        return jsonify(conversations=service.list_conversations(_user_id()))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not list chat conversations")
        return _api_error("chat_unavailable", 503)


@chat_bp.get("/api/realtime-token")
def api_realtime_token():
    config = current_app.config
    required = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_JWT_SECRET")
    if any(not config.get(key) for key in required):
        return _api_error("realtime_not_configured", 503)
    try:
        user_id = _user_id()
        topics = [user_topic(user_id)]
        conversation_id = request.args.get("conversation_id")
        conversation_topics = {}
        if conversation_id:
            if not service.is_active_member(conversation_id, user_id):
                return _api_error("forbidden", 403)
            conversation_topics[conversation_id] = conversation_topic(conversation_id)
            topics.append(conversation_topics[conversation_id])
        access_token = create_access_token(user_id, topics, config["SUPABASE_JWT_SECRET"])
        return jsonify(
            url=config["SUPABASE_URL"],
            anon_key=config["SUPABASE_ANON_KEY"],
            access_token=access_token,
            expires_in=TOKEN_TTL_SECONDS,
            user_topic=user_topic(user_id),
            conversation_topics=conversation_topics,
        )
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not create Supabase Realtime token")
        return _api_error("chat_unavailable", 503)


@chat_bp.post("/api/conversations")
def api_create_conversation():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _api_error("invalid_payload")
    try:
        conversation_id = service.create_conversation(_user_id(), payload.get("title"), payload.get("member_user_ids", []))
        conversation = service.get_conversation(conversation_id)
        member_ids = conversation.get("member_user_ids", [])
        event = {"id": conversation_id, "title": conversation["title"]}
        for uid in member_ids:
            emit_to_user("conversation_added", event, uid)
        return jsonify(conversation_id=conversation_id), 201
    except (ValueError, PermissionError) as error:
        return _api_error(str(error), _status_for_error(error))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not create chat conversation")
        return _api_error("chat_unavailable", 503)


@chat_bp.get("/api/conversations/<conversation_id>")
def api_get_conversation(conversation_id):
    try:
        if not service.is_active_member(conversation_id, _user_id()):
            return _api_error("forbidden", 403)
        return jsonify(service.graph_payload(conversation_id, _user_id()))
    except ValueError as error:
        return _api_error(str(error), _status_for_error(error))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not load chat graph")
        return _api_error("chat_unavailable", 503)


@chat_bp.delete("/api/conversations/<conversation_id>")
def api_delete_conversation(conversation_id):
    try:
        member_ids = service.delete_conversation(conversation_id, _user_id())
        for user_id in member_ids:
            emit_to_user("conversation_removed", {"id": conversation_id}, user_id)
        return jsonify(deleted=True)
    except (ValueError, PermissionError) as error:
        return _api_error(str(error), _status_for_error(error))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not delete chat conversation")
        return _api_error("chat_unavailable", 503)


@chat_bp.post("/api/conversations/<conversation_id>/questions")
def api_create_question(conversation_id):
    if not service.is_active_member(conversation_id, _user_id()):
        return _api_error("forbidden", 403)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _api_error("invalid_payload")
    try:
        question_id = service.create_question(
            conversation_id,
            _user_id(),
            payload.get("text"),
            payload.get("options"),
            payload.get("parent_option_id"),
            payload.get("allow_vote_change", True),
        )
        event = service.question_event_payload(conversation_id, question_id)
        emit_to_active_members("question_created", event, conversation_id)
        return jsonify(question_id=question_id), 201
    except (ValueError, PermissionError) as error:
        return _api_error(str(error), _status_for_error(error))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not create chat question")
        return _api_error("chat_unavailable", 503)


@chat_bp.post("/api/questions/<question_id>/answers")
def api_submit_answer(question_id):
    question = service.question_by_id(question_id)
    if not question:
        return _api_error("not_found", 404)
    conversation_id = str(question["conversation_id"])
    if not service.is_active_member(conversation_id, _user_id()):
        return _api_error("forbidden", 403)
    payload = request.get_json(silent=True)
    option_id = payload.get("option_id") if isinstance(payload, dict) else None
    try:
        result = service.submit_answer(question_id, _user_id(), option_id)
        if result["changed"]:
            event = {
                "question_id": str(question_id),
                "option_id": str(option_id),
                "previous_option_id": result["previous_option_id"],
                "user_id": _user_id(),
                "counts": service.answer_counts(question_id),
            }
            emit_to_active_members("answer_recorded", event, conversation_id)
            if result["closed"]:
                graph = service.graph_payload(conversation_id)
                question_node = next((node for node in graph["nodes"] if node["id"] == f"q{question_id}"), {})
                emit_to_active_members("question_closed", {
                    "question_id": str(question_id),
                    "winning_option_id": question_node.get("winning_option_id"),
                    "merge_edges": [edge for edge in graph["edges"] if edge["kind"] == "merge"],
                }, conversation_id)
        return jsonify(ok=True, **result)
    except (ValueError, PermissionError) as error:
        return _api_error(str(error), _status_for_error(error))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not record chat answer")
        return _api_error("chat_unavailable", 503)


@chat_bp.post("/api/questions/<question_id>/close")
def api_close_question(question_id):
    question = service.question_by_id(question_id)
    if not question:
        return _api_error("not_found", 404)
    conversation_id = str(question["conversation_id"])
    if not service.is_active_member(conversation_id, _user_id()):
        return _api_error("forbidden", 403)
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return _api_error("invalid_payload")
    try:
        closed = service.close_question(question_id, _user_id(), payload.get("winning_option_id"))
        if not closed:
            return _api_error("already_closed", 409)
        graph = service.graph_payload(conversation_id)
        question_node = next((node for node in graph["nodes"] if node["id"] == f"q{question_id}"), {})
        event = {
            "question_id": str(question_id),
            "winning_option_id": question_node.get("winning_option_id"),
            "merge_edges": [edge for edge in graph["edges"] if edge["kind"] == "merge"],
        }
        emit_to_active_members("question_closed", event, conversation_id)
        return jsonify(ok=True, **event)
    except (ValueError, PermissionError) as error:
        return _api_error(str(error), _status_for_error(error))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not close chat question")
        return _api_error("chat_unavailable", 503)


@chat_bp.post("/api/conversations/<conversation_id>/members")
def api_add_members(conversation_id):
    payload = request.get_json(silent=True)
    user_ids = payload.get("user_ids") if isinstance(payload, dict) else None
    try:
        added = service.add_members(conversation_id, _user_id(), user_ids)
        for member in added:
            event = {"id": conversation_id, "title": (service.get_conversation(conversation_id) or {}).get("title", "")}
            emit_to_user("conversation_added", event, member["user_id"])
            emit_to_active_members("member_added", member, conversation_id)
        return jsonify(members=added)
    except (ValueError, PermissionError) as error:
        return _api_error(str(error), _status_for_error(error))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not add chat members")
        return _api_error("chat_unavailable", 503)


@chat_bp.delete("/api/conversations/<conversation_id>/members/<user_id>")
def api_remove_member(conversation_id, user_id):
    try:
        member = service.remove_member(conversation_id, _user_id(), user_id)
        emit_to_active_members("member_removed", member, conversation_id, include_users=(user_id,))
        emit_to_user("conversation_removed", {"id": conversation_id}, user_id)
        return jsonify(member=member)
    except (ValueError, PermissionError) as error:
        return _api_error(str(error), _status_for_error(error))
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not remove chat member")
        return _api_error("chat_unavailable", 503)


@chat_bp.get("/api/contacts/addable")
def api_addable_contacts():
    conversation_id = request.args.get("conversation_id")
    try:
        if conversation_id and not service.is_active_member(conversation_id, _user_id()):
            return _api_error("forbidden", 403)
        contacts = service.addable_contacts(_user_id(), conversation_id)
        return jsonify(contacts=contacts)
    except (PyMongoError, RuntimeError):
        current_app.logger.exception("Could not load addable contacts")
        return _api_error("chat_unavailable", 503)


@chat_bp.patch("/api/questions/<question_id>")
def api_edit_question(question_id):
    question = service.question_by_id(question_id)
    if not question or not service.is_active_member(str(question["conversation_id"]), _user_id()):
        return _api_error("forbidden", 403)
    return _api_error("branch_mode_locked", 403)


@chat_bp.delete("/api/questions/<question_id>")
def api_delete_question(question_id):
    question = service.question_by_id(question_id)
    if not question or not service.is_active_member(str(question["conversation_id"]), _user_id()):
        return _api_error("forbidden", 403)
    return _api_error("branch_mode_locked", 403)
