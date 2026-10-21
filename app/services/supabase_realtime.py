"""Supabase Realtime Broadcast integration for private chat invalidation events."""

import base64
import hashlib
import hmac
import json
import logging
import time

import requests


logger = logging.getLogger(__name__)
TOKEN_TTL_SECONDS = 300


def _b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def user_topic(user_id):
    encoded_id = _b64url(str(user_id).encode("utf-8"))
    return f"chat-user:{encoded_id}"


def conversation_topic(conversation_id):
    return f"chat-conversation:{conversation_id}"


def create_access_token(user_id, topics, secret, now=None):
    if not isinstance(secret, str) or not secret:
        raise ValueError("supabase_jwt_secret_required")
    issued_at = int(time.time() if now is None else now)
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "aud": "authenticated",
        "role": "authenticated",
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + TOKEN_TTL_SECONDS,
        "chat_topics": sorted(set(topics)),
    }
    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}.{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def publish_messages(messages, config=None):
    """Publish broadcast invalidations. Failure is logged; MongoDB remains authoritative."""
    if config is None:
        from flask import current_app
        config = current_app.config
    project_url = (config.get("SUPABASE_URL") or "").rstrip("/")
    key = config.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not project_url or not key or not messages:
        return False
    try:
        response = requests.post(
            f"{project_url}/realtime/v1/api/broadcast",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            json={"messages": messages},
            timeout=2,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception("Supabase Realtime broadcast failed")
        return False


def publish_conversation_event(conversation_id, event):
    return publish_messages([{
        "topic": conversation_topic(conversation_id),
        "event": "chat_update",
        "payload": {"kind": event},
        "private": True,
    }])


def publish_user_event(user_id, event, conversation_id=None):
    payload = {"kind": event}
    if conversation_id is not None:
        payload["conversation_id"] = str(conversation_id)
    return publish_messages([{
        "topic": user_topic(user_id),
        "event": "chat_update",
        "payload": payload,
        "private": True,
    }])
