import html
import json
from urllib import request as urllib_request

from bson import ObjectId
from flask_babel import gettext

from app.services import chat as chat_service
from app.services import events as event_service
from app.services.contacts import _collection as contacts_collection
from app.services.mongodb import get_collection
from app.services.push_notifications import notify_users


MAX_EMAIL_MESSAGE_LENGTH = 1000
MAX_PUSH_MESSAGE_LENGTH = 180


def list_invitation_contexts(owner_id):
    return {
        "events": [
            {"id": event["id"], "title": event["title"]}
            for event in event_service.list_events(owner_id)
            if event.get("can_delete")
        ],
        "chats": [
            {"id": conversation["id"], "title": conversation["title"]}
            for conversation in chat_service.list_conversations(owner_id)
            if conversation.get("is_owner")
        ],
    }


def _get_contact(owner_id, contact_id):
    if not ObjectId.is_valid(contact_id):
        raise ValueError("contact_not_found")
    contact = contacts_collection().find_one(
        {"_id": ObjectId(contact_id), "owner_id": owner_id}
    )
    if not contact:
        raise ValueError("contact_not_found")
    email = (contact.get("email") or "").strip().casefold()
    if not email or email.count("@") != 1 or any(character.isspace() for character in email):
        raise ValueError("contact_email_required")
    account = get_collection("users").find_one(
        {"email": email}, {"_id": 1, "name": 1, "email": 1, "picture": 1}
    )
    return contact, account


def _get_context(owner_id, context_type, context_id):
    if context_type is None and context_id in (None, ""):
        return None
    if not isinstance(context_type, str) or context_type not in {"event", "chat"} or not isinstance(context_id, str) or not context_id:
        raise ValueError("invalid_invitation")
    if context_type == "event":
        context = event_service.get_event(owner_id, context_id)
        if not context:
            raise ValueError("context_not_found")
        if not context.get("can_delete"):
            raise PermissionError("forbidden")
        return context
    context = chat_service.get_conversation(context_id)
    if not context:
        raise ValueError("context_not_found")
    if context.get("created_by_user_id") != owner_id:
        raise PermissionError("forbidden")
    return context


def _send_email(app, recipient_email, recipient_name, sender_name, registered, context_type, context_title, message, destination):
    if not app.config.get("RESEND_API_KEY"):
        raise RuntimeError("email_not_configured")
    if context_type == "event":
        subject = gettext("Invitation to event: {title}").format(title=context_title)
        context_copy = (
            gettext("You have a pending invitation to the event {title} on Flutu.")
            if registered else gettext("Your contact shared the event {title} with you on Flutu.")
        ).format(title=context_title)
    elif context_type == "chat":
        if registered:
            subject = gettext("Invitation to branching chat: {title}").format(title=context_title)
            context_copy = gettext("You were added to the branching chat {title} on Flutu.").format(title=context_title)
        else:
            subject = gettext("A message about branching chat: {title}").format(title=context_title)
            context_copy = gettext(
                "Your contact shared a message about the branching chat {title} on Flutu. Sign in and ask them to add you."
            ).format(title=context_title)
    else:
        subject = gettext("A message from {name} on Flutu").format(name=sender_name)
        context_copy = gettext("Your contact sent you a message on Flutu.")
    subject = " ".join(subject.splitlines())[:180]
    body = (
        f"<p>{html.escape(gettext('Hello {name},').format(name=recipient_name or ''))}</p>"
        f"<p>{html.escape(message).replace(chr(10), '<br>')}</p>"
        f"<p>{html.escape(context_copy)}</p>"
        f"<p><a href=\"{html.escape(destination, quote=True)}\">{html.escape(gettext('Open Flutu'))}</a></p>"
    )
    payload = json.dumps({
        "from": app.config.get("EMAIL_FROM", "Flutu <noreply@flutu.app>"),
        "to": [recipient_email],
        "subject": subject,
        "html": body,
    }).encode("utf-8")
    email_request = urllib_request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {app.config['RESEND_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(email_request, timeout=5):
            return True
    except Exception:
        app.logger.warning("Contact invitation email delivery failed")
        raise RuntimeError("email_delivery_failed") from None


def send_contact_invitation(
    app,
    owner_id,
    contact_id,
    *,
    context_type=None,
    context_id=None,
    delivery,
    message,
    sender_name="",
    event_url="",
    event_path="",
    chat_url="",
    chat_path="",
    login_url="",
):
    if not isinstance(delivery, str) or delivery not in {"push", "email"} or not isinstance(message, str):
        raise ValueError("invalid_invitation")
    message = message.strip()
    max_length = MAX_PUSH_MESSAGE_LENGTH if delivery == "push" else MAX_EMAIL_MESSAGE_LENGTH
    if not message or len(message) > max_length:
        raise ValueError("invalid_invitation_message")
    contact, account = _get_contact(owner_id, contact_id)
    registered = account is not None
    if delivery == "push" and not registered:
        raise ValueError("push_requires_account")
    if delivery == "email" and not app.config.get("RESEND_API_KEY"):
        raise RuntimeError("email_not_configured")
    context = _get_context(owner_id, context_type, context_id)
    context_title = context.get("title", "") if context else ""
    context_key = str(context_id) if context_id else None
    new_chat_member = None
    context_added = False

    if context_type == "event" and context:
        if registered:
            _, context_added = event_service.invite_event_member(owner_id, context_key, str(account["_id"]))
        else:
            _, context_added = event_service.add_guest_contact(owner_id, context_key, str(contact["_id"]))
    elif context_type == "chat" and context and registered:
        added = chat_service.add_members(context_key, owner_id, [str(account["_id"])])
        new_chat_member = added[0] if added else None
        context_added = bool(added)

    if delivery == "email":
        destination = login_url if not registered or not context else (event_url if context_type == "event" else chat_url)
        _send_email(
            app,
            (contact.get("email") or "").strip(),
            contact.get("name", ""),
            sender_name,
            registered,
            context_type,
            context_title,
            message,
            destination,
        )
        delivered = True
    else:
        title = gettext("Message from {name}").format(name=sender_name or gettext("a Flutu friend"))
        destination = event_path if context_type == "event" else chat_path if context_type == "chat" else "/contacts"
        counts = notify_users(
            app,
            [str(account["_id"])],
            title=title[:80],
            body=message,
            url=destination,
            exclude_ids={owner_id},
        )
        delivered = bool(counts.get("sent"))

    return {
        "delivery": delivery,
        "delivered": delivered,
        "registered": registered,
        "context_type": context_type,
        "context_id": context_key,
        "context_title": context_title,
        "context_added": context_added,
        "new_chat_member": new_chat_member,
    }
