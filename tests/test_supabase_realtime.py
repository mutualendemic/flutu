import base64
import json
import unittest
from unittest.mock import Mock, patch

from flask import Flask
import requests

from app.services.supabase_realtime import (
    conversation_topic,
    create_access_token,
    publish_conversation_event,
    user_topic,
)


class SupabaseRealtimeTests(unittest.TestCase):
    def decode_claims(self, token):
        encoded = token.split(".")[1]
        encoded += "=" * (-len(encoded) % 4)
        return json.loads(base64.urlsafe_b64decode(encoded))

    def test_access_token_is_short_lived_and_scoped_to_allowed_topics(self):
        token = create_access_token(
            "google-user",
            [user_topic("google-user"), conversation_topic("65b0e7a3a6c6f166f1c3a001")],
            "jwt-secret",
            now=1_800_000_000,
        )
        claims = self.decode_claims(token)
        self.assertEqual(claims["sub"], "google-user")
        self.assertEqual(claims["role"], "authenticated")
        self.assertEqual(claims["exp"] - claims["iat"], 300)
        self.assertEqual(len(claims["chat_topics"]), 2)
        self.assertEqual(user_topic("a:b"), "chat-user:YTpi")

    def test_broadcast_sends_only_private_invalidation_payload(self):
        response = Mock()
        response.raise_for_status.return_value = None
        app = Flask(__name__)
        app.config.update(
            SUPABASE_URL="https://project.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-secret",
        )
        with patch("app.services.supabase_realtime.requests.post", return_value=response) as post:
            with app.app_context():
                result = publish_conversation_event(
                    "65b0e7a3a6c6f166f1c3a001", "answer_recorded",
                )
        self.assertTrue(result)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://project.supabase.co/realtime/v1/api/broadcast")
        self.assertEqual(kwargs["headers"]["apikey"], "service-secret")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer service-secret")
        self.assertEqual(kwargs["json"], {
            "messages": [{
                "topic": "chat-conversation:65b0e7a3a6c6f166f1c3a001",
                "event": "chat_update",
                "payload": {"kind": "answer_recorded"},
                "private": True,
            }]
        })
        self.assertEqual(kwargs["timeout"], 2)

    def test_broadcast_failure_is_non_fatal(self):
        app = Flask(__name__)
        app.config.update(
            SUPABASE_URL="https://project.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-secret",
        )
        with patch(
            "app.services.supabase_realtime.requests.post",
            side_effect=requests.Timeout("offline"),
        ), app.app_context():
            self.assertFalse(publish_conversation_event("conversation", "question_created"))


if __name__ == "__main__":
    unittest.main()
