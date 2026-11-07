import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.contact_invitations import _get_context, list_invitation_contexts, send_contact_invitation


class ContactInvitationTests(unittest.TestCase):
    def test_context_list_contains_only_owned_events_and_chats(self):
        with patch(
            "app.services.contact_invitations.event_service.list_events",
            return_value=[
                {"id": "event-owner", "title": "Owned", "can_delete": True},
                {"id": "event-shared", "title": "Shared", "can_delete": False},
            ],
        ), patch(
            "app.services.contact_invitations.chat_service.list_conversations",
            return_value=[
                {"id": "chat-owner", "title": "Owned", "is_owner": True},
                {"id": "chat-shared", "title": "Shared", "is_owner": False},
            ],
        ):
            contexts = list_invitation_contexts("owner")
        self.assertEqual(contexts, {
            "events": [{"id": "event-owner", "title": "Owned"}],
            "chats": [{"id": "chat-owner", "title": "Owned"}],
        })

    def test_context_must_be_owned_by_sender(self):
        with patch(
            "app.services.contact_invitations.event_service.get_event",
            return_value={"id": "event-id", "can_delete": False},
        ), self.assertRaises(PermissionError):
            _get_context("owner", "event", "event-id")
        with patch(
            "app.services.contact_invitations.chat_service.get_conversation",
            return_value={"id": "chat-id", "created_by_user_id": "other"},
        ), self.assertRaises(PermissionError):
            _get_context("owner", "chat", "chat-id")

    def test_registered_contact_can_receive_push_without_context(self):
        app = SimpleNamespace(config={})
        contact = {"_id": "contact-id", "email": "member@example.com", "name": "Member"}
        account = {"_id": "member-user"}
        with patch("app.services.contact_invitations._get_contact", return_value=(contact, account)), patch(
            "app.services.contact_invitations.notify_users", return_value={"sent": 1}
        ) as notify, patch("app.services.contact_invitations.event_service.invite_event_member") as invite_event, patch(
            "app.services.contact_invitations.chat_service.add_members"
        ) as add_member:
            result = send_contact_invitation(
                app, "owner", "contact-id", delivery="push", message="A quick update",
                sender_name="Owner", login_url="https://example.test/auth/login",
            )
        self.assertTrue(result["delivered"])
        self.assertIsNone(result["context_type"])
        self.assertFalse(result["context_added"])
        notify.assert_called_once_with(
            app, ["member-user"], title="Message from Owner", body="A quick update",
            url="/contacts", exclude_ids={"owner"},
        )
        invite_event.assert_not_called()
        add_member.assert_not_called()

    def test_registered_contact_can_receive_email_without_context(self):
        app = SimpleNamespace(config={"RESEND_API_KEY": "fake-resend-key"})
        contact = {"_id": "contact-id", "email": "member@example.com", "name": "Member"}
        account = {"_id": "member-user"}
        with patch("app.services.contact_invitations._get_contact", return_value=(contact, account)), patch(
            "app.services.contact_invitations._send_email", return_value=True
        ) as send_email:
            result = send_contact_invitation(
                app, "owner", "contact-id", delivery="email", message="A longer note",
                sender_name="Owner", login_url="https://example.test/auth/login",
            )
        self.assertTrue(result["delivered"])
        self.assertFalse(result["context_added"])
        self.assertEqual(send_email.call_args.args[1:4], ("member@example.com", "Member", "Owner"))
        self.assertEqual(send_email.call_args.args[4:9], (
            True, None, "", "A longer note", "https://example.test/auth/login",
        ))

    def test_registered_contact_can_receive_push_with_chat_context(self):
        app = SimpleNamespace(config={})
        contact = {"_id": "contact-id", "email": "member@example.com", "name": "Member"}
        account = {"_id": "member-user"}
        chat = {"id": "chat-id", "title": "Planning", "created_by_user_id": "owner"}
        member = {"user_id": "member-user", "name": "Member"}
        with patch("app.services.contact_invitations._get_contact", return_value=(contact, account)), patch(
            "app.services.contact_invitations._get_context", return_value=chat
        ), patch(
            "app.services.contact_invitations.chat_service.add_members", return_value=[member]
        ) as add_member, patch(
            "app.services.contact_invitations.notify_users", return_value={"sent": 1}
        ) as notify:
            result = send_contact_invitation(
                app, "owner", "contact-id", context_type="chat", context_id="chat-id",
                delivery="push", message="Let's decide together", sender_name="Owner",
                chat_path="/chat/chat-id", chat_url="https://example.test/chat/chat-id",
            )
        add_member.assert_called_once_with("chat-id", "owner", ["member-user"])
        self.assertTrue(result["context_added"])
        self.assertEqual(result["new_chat_member"], member)
        notify.assert_called_once_with(
            app, ["member-user"], title="Message from Owner", body="Let's decide together",
            url="/chat/chat-id", exclude_ids={"owner"},
        )

    def test_external_contact_can_receive_custom_email_with_event_context(self):
        app = SimpleNamespace(config={"RESEND_API_KEY": "fake-resend-key"})
        contact = {"_id": "contact-id", "email": "external@example.com", "name": "External"}
        event = {"id": "event-id", "title": "Planning"}
        with patch("app.services.contact_invitations._get_contact", return_value=(contact, None)), patch(
            "app.services.contact_invitations._get_context", return_value=event
        ), patch(
            "app.services.contact_invitations.event_service.add_guest_contact", return_value=(event, True)
        ) as add_guest, patch(
            "app.services.contact_invitations._send_email", return_value=True
        ) as send_email:
            result = send_contact_invitation(
                app, "owner", "contact-id", context_type="event", context_id="event-id",
                delivery="email", message="Join my plan", sender_name="Owner",
                event_url="https://example.test/calendar/?event=event-id",
                login_url="https://example.test/auth/login",
            )
        self.assertTrue(result["delivered"])
        self.assertTrue(result["context_added"])
        add_guest.assert_called_once_with("owner", "event-id", "contact-id")
        self.assertEqual(send_email.call_args.args[4:9], (
            False, "event", "Planning", "Join my plan", "https://example.test/auth/login",
        ))

    def test_external_contact_chat_email_does_not_grant_chat_access(self):
        app = SimpleNamespace(config={"RESEND_API_KEY": "fake-resend-key"})
        contact = {"_id": "contact-id", "email": "external@example.com", "name": "External"}
        chat = {"id": "chat-id", "title": "Planning", "created_by_user_id": "owner"}
        with patch("app.services.contact_invitations._get_contact", return_value=(contact, None)), patch(
            "app.services.contact_invitations._get_context", return_value=chat
        ), patch("app.services.contact_invitations.chat_service.add_members") as add_member, patch(
            "app.services.contact_invitations._send_email", return_value=True
        ) as send_email:
            result = send_contact_invitation(
                app, "owner", "contact-id", context_type="chat", context_id="chat-id",
                delivery="email", message="A note about planning", sender_name="Owner",
                chat_url="https://example.test/chat/chat-id",
                login_url="https://example.test/auth/login",
            )
        self.assertTrue(result["delivered"])
        self.assertFalse(result["context_added"])
        add_member.assert_not_called()
        self.assertEqual(send_email.call_args.args[4:9], (
            False, "chat", "Planning", "A note about planning", "https://example.test/auth/login",
        ))

    def test_unregistered_contact_cannot_receive_push(self):
        app = SimpleNamespace(config={})
        contact = {"_id": "contact-id", "email": "external@example.com", "name": "External"}
        with patch("app.services.contact_invitations._get_contact", return_value=(contact, None)), patch(
            "app.services.contact_invitations.notify_users"
        ) as notify:
            with self.assertRaisesRegex(ValueError, "push_requires_account"):
                send_contact_invitation(
                    app, "owner", "contact-id", delivery="push", message="Hello",
                    login_url="https://example.test/auth/login",
                )
        notify.assert_not_called()

    def test_non_scalar_delivery_and_context_values_are_rejected(self):
        app = SimpleNamespace(config={})
        with self.assertRaisesRegex(ValueError, "invalid_invitation"):
            send_contact_invitation(app, "owner", "contact-id", delivery=[], message="Hello")
        with self.assertRaisesRegex(ValueError, "invalid_invitation"):
            _get_context("owner", [], "context-id")