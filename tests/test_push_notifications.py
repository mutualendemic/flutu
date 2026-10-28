import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from app.services import push_notifications as push


class PushNotificationServiceTests(unittest.TestCase):
    def test_accepts_known_https_push_endpoints_only(self):
        endpoint = "https://fcm.googleapis.com/fcm/send/subscription-token"
        self.assertEqual(push.validate_endpoint(endpoint), endpoint)
        for invalid in (
            "http://fcm.googleapis.com/fcm/send/token",
            "https://127.0.0.1/push",
            "https://localhost/push",
            "https://evil.example/fcm/send/token",
            "https://user@fcm.googleapis.com/push",
            "https://fcm.googleapis.com:8443/push",
        ):
            with self.subTest(endpoint=invalid), self.assertRaisesRegex(ValueError, "invalid_subscription"):
                push.validate_endpoint(invalid)

    def test_save_subscription_upserts_endpoint_and_transfers_owner(self):
        collection = Mock()
        collection.find_one.return_value = {"owner_id": "previous-user"}
        collection.count_documents.return_value = 0
        payload = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/token",
            "keys": {"p256dh": "p" * 32, "auth": "a" * 16},
        }
        with patch("app.services.push_notifications._subscriptions", return_value=collection):
            self.assertTrue(push.save_subscription("google-user", payload))
        collection.update_one.assert_called_once()
        query, update = collection.update_one.call_args.args
        self.assertEqual(query, {"endpoint": payload["endpoint"]})
        self.assertEqual(update["$set"]["owner_id"], "google-user")
        self.assertEqual(update["$set"]["keys"], payload["keys"])
        self.assertIsInstance(update["$set"]["updated_at"], datetime)
        self.assertEqual(update["$setOnInsert"]["created_at"], update["$set"]["updated_at"])

    def test_save_subscription_enforces_per_user_device_limit(self):
        collection = Mock()
        collection.find_one.return_value = None
        collection.count_documents.return_value = push.MAX_SUBSCRIPTIONS_PER_USER
        payload = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/token",
            "keys": {"p256dh": "p" * 32, "auth": "a" * 16},
        }
        with patch("app.services.push_notifications._subscriptions", return_value=collection):
            with self.assertRaisesRegex(OverflowError, "subscription_limit"):
                push.save_subscription("google-user", payload)
        collection.update_one.assert_not_called()

    def test_unsubscribe_is_scoped_to_current_owner(self):
        collection = Mock()
        collection.delete_one.return_value.deleted_count = 1
        endpoint = "https://fcm.googleapis.com/fcm/send/token"
        with patch("app.services.push_notifications._subscriptions", return_value=collection):
            self.assertTrue(push.remove_subscription("google-user", endpoint))
        collection.delete_one.assert_called_once_with({"owner_id": "google-user", "endpoint": endpoint})

    def test_notify_deduplicates_recipients_excludes_actor_and_is_best_effort(self):
        app = Mock()
        app.config = {
            "VAPID_PUBLIC_KEY": "public",
            "VAPID_PRIVATE_KEY": "private",
            "VAPID_CONTACT": "mailto:ops@example.com",
        }
        collection = Mock()
        collection.find.return_value = [{"_id": "sub1"}, {"_id": "sub2"}]
        with patch("app.services.push_notifications._subscriptions", return_value=collection), patch(
            "app.services.push_notifications._send_one", side_effect=["sent", "failed"]
        ) as send:
            counts = push.notify_users(
                app,
                ["actor", "friend", "friend", None],
                title="New question",
                body="A friend added a question that needs your attention.",
                url="/chat/abc",
                exclude_ids={"actor"},
            )
        collection.find.assert_called_once_with({"owner_id": {"$in": ["friend"]}})
        self.assertEqual(send.call_count, 2)
        self.assertEqual(counts, {"sent": 1, "expired": 0, "failed": 1})

    def test_notify_does_nothing_when_vapid_is_not_configured(self):
        app = Mock()
        app.config = {"VAPID_PUBLIC_KEY": "public"}
        with patch("app.services.push_notifications._subscriptions") as subscriptions:
            result = push.notify_users(app, ["friend"], title="Hi", body="Body", url="/map")
        self.assertEqual(result, {"sent": 0, "expired": 0, "failed": 0})
        subscriptions.assert_not_called()

    def test_expired_endpoint_is_removed_but_transient_failures_are_kept(self):
        import sys
        from types import SimpleNamespace

        class FakeWebPushException(Exception):
            def __init__(self, message, response):
                super().__init__(message)
                self.response = response

        collection = Mock()
        config = {"VAPID_PRIVATE_KEY": "secret", "VAPID_CONTACT": "mailto:ops@example.com"}
        subscription = {"_id": "sub-id", "endpoint": "https://fcm.googleapis.com/fcm/send/token", "keys": {}}
        gone_response = Mock(status_code=410)
        with patch.dict(sys.modules, {"pywebpush": SimpleNamespace(WebPushException=FakeWebPushException, webpush=Mock(side_effect=FakeWebPushException("gone", gone_response)))}):
            self.assertEqual(push._send_one(subscription, {"title": "Hi", "body": "", "url": "/map"}, config, collection), "expired")
        collection.delete_one.assert_called_once_with({"_id": "sub-id"})

        transient_response = Mock(status_code=503)
        with patch.dict(sys.modules, {"pywebpush": SimpleNamespace(WebPushException=FakeWebPushException, webpush=Mock(side_effect=FakeWebPushException("temporary", transient_response)))}):
            self.assertEqual(push._send_one(subscription, {"title": "Hi", "body": "", "url": "/map"}, config, collection), "failed")
        collection.delete_one.assert_called_once_with({"_id": "sub-id"})

    def test_notify_rejects_external_click_urls(self):
        app = Mock()
        app.config = {
            "VAPID_PUBLIC_KEY": "public",
            "VAPID_PRIVATE_KEY": "private",
            "VAPID_CONTACT": "mailto:ops@example.com",
        }
        with patch("app.services.push_notifications._subscriptions") as subscriptions:
            result = push.notify_users(app, ["friend"], title="Hi", body="", url="https://evil.example")
        self.assertEqual(result, {"sent": 0, "expired": 0, "failed": 0})
        subscriptions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
