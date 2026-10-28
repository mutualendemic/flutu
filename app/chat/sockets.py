from collections import defaultdict, deque
from functools import wraps
import threading
import time

from flask import current_app, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room

from app.services import chat as service
from app.services.push_notifications import notify_users
from app.services.supabase_realtime import publish_conversation_event, publish_user_event


socketio = SocketIO()
_rate_events = defaultdict(deque)
_rate_lock = threading.Lock()


def init_socketio(app):
    origins = app.config.get("SOCKETIO_CORS_ORIGINS") or None
    if isinstance(origins, str):
        origins = [origin.strip() for origin in origins.split(",") if origin.strip()] or None
    external_mode = app.config.get("CHAT_REALTIME_MODE") in {"supabase", "polling"}
    queue = None if external_mode else (app.config.get("REDIS_URL") or None)
    production = str(app.config.get("APP_ENV", "")).lower() == "production" and not external_mode
    async_mode = "threading" if external_mode else "gevent"
    if not external_mode:
        try:
            import gevent  # noqa: F401
        except ImportError:
            async_mode = "threading"
    if production and app.config.get("SOCKETIO_REQUIRE_REDIS", True):
        if not queue:
            raise RuntimeError("REDIS_URL is required for production chat real-time delivery")
        try:
            import redis
            redis.Redis.from_url(queue, socket_connect_timeout=3).ping()
        except Exception as error:
            raise RuntimeError("Redis is required for production chat and is not reachable") from error
    socketio.init_app(
        app,
        async_mode=async_mode,
        message_queue=queue,
        cors_allowed_origins=origins,
        manage_session=True,
    )
    app.extensions["socketio"] = socketio
    return socketio


def _error(code):
    return {"ok": False, "error": code}


def _rate_limited(sid):
    now = time.monotonic()
    with _rate_lock:
        events = _rate_events[sid]
        while events and now - events[0] >= 10:
            events.popleft()
        if len(events) >= 20:
            return True
        events.append(now)
        return False


def _authorized(handler):
    @wraps(handler)
    def wrapped(data=None):
        user = session.get("user")
        if not user:
            return _error("unauthenticated")
        if _rate_limited(request.sid):
            return _error("rate_limited")
        return handler(user, data if isinstance(data, dict) else {})
    return wrapped


def _conversation_for_question(question_id, user_id):
    question = service.question_by_id(question_id)
    if not question:
        return None, None
    conversation_id = str(question["conversation_id"])
    if not service.is_active_member(conversation_id, user_id):
        return None, None
    return question, conversation_id


def emit_to_active_members(event, payload, conversation_id, include_users=()):
    """Fan out invalidations to Supabase, or full Socket.IO events on legacy hosts."""
    recipient_ids = {member["user_id"] for member in service.get_active_members(conversation_id)}
    recipient_ids.update(include_users)
    if current_app.config.get("CHAT_REALTIME_MODE") == "supabase":
        publish_conversation_event(conversation_id, event)
    else:
        for user_id in recipient_ids:
            socketio.emit(event, payload, to=f"user:{user_id}", namespace="/chat")


def emit_to_user(event, payload, user_id):
    if current_app.config.get("CHAT_REALTIME_MODE") == "supabase":
        publish_user_event(user_id, event, payload.get("id") if isinstance(payload, dict) else None)
    else:
        socketio.emit(event, payload, to=f"user:{user_id}", namespace="/chat")


def _closed_payload(conversation_id, question_id):
    graph = service.graph_payload(conversation_id)
    question_node = next((node for node in graph["nodes"] if node["id"] == f"q{question_id}"), {})
    return {
        "question_id": question_id,
        "winning_option_id": question_node.get("winning_option_id"),
        "merge_edges": [edge for edge in graph["edges"] if edge["kind"] == "merge" and edge["from"].startswith("o")],
    }


@socketio.on("connect", namespace="/chat")
def connect_chat(auth=None):
    user = session.get("user")
    if not user or not user.get("sub"):
        return False
    join_room(f"user:{user['sub']}")
    return True


@socketio.on("disconnect", namespace="/chat")
def disconnect_chat(reason=None):
    with _rate_lock:
        _rate_events.pop(request.sid, None)


@socketio.on("join", namespace="/chat")
@_authorized
def join_conversation(user, data):
    conversation_id = data.get("conversation_id")
    if not isinstance(conversation_id, str) or not service.is_active_member(conversation_id, user["sub"]):
        return _error("forbidden")
    try:
        snapshot = service.graph_payload(conversation_id, user["sub"])
    except ValueError:
        return _error("not_found")
    join_room(f"conv:{conversation_id}")
    return {"ok": True, "graph": snapshot}


@socketio.on("leave", namespace="/chat")
@_authorized
def leave_conversation(user, data):
    conversation_id = data.get("conversation_id")
    if not isinstance(conversation_id, str) or not service.is_active_member(conversation_id, user["sub"]):
        return _error("forbidden")
    leave_room(f"conv:{conversation_id}")
    return {"ok": True}


@socketio.on("create_question", namespace="/chat")
@_authorized
def socket_create_question(user, data):
    conversation_id = data.get("conversation_id")
    if not isinstance(conversation_id, str) or not service.is_active_member(conversation_id, user["sub"]):
        return _error("forbidden")
    try:
        question_id = service.create_question(
            conversation_id,
            user["sub"],
            data.get("text"),
            data.get("options"),
            data.get("parent_option_id"),
            data.get("allow_vote_change", True),
        )
        payload = service.question_event_payload(conversation_id, question_id)
        emit_to_active_members("question_created", payload, conversation_id)
        recipients = [member["user_id"] for member in service.get_active_members(conversation_id)]
        notify_users(
            current_app._get_current_object(),
            recipients,
            title="New question in a conversation",
            body="A friend added a question that needs your attention.",
            url=f"/chat/{conversation_id}",
            exclude_ids={user["sub"]},
        )
        return {"ok": True, "question_id": question_id}
    except (ValueError, PermissionError) as error:
        return _error(str(error))


@socketio.on("submit_answer", namespace="/chat")
@_authorized
def socket_submit_answer(user, data):
    question, _ = _conversation_for_question(data.get("question_id"), user["sub"])
    if not question:
        return _error("forbidden")
    return _error("branch_mode_locked")


@socketio.on("close_question", namespace="/chat")
@_authorized
def socket_close_question(user, data):
    question, _ = _conversation_for_question(data.get("question_id"), user["sub"])
    if not question:
        return _error("forbidden")
    return _error("branch_mode_locked")
