import json
import os
import re
import unittest
from importlib import reload
from pathlib import Path
from unittest.mock import Mock, patch

from app import create_app
from app.i18n import JS_MESSAGE_IDS
import app.config as config_module
from app.services.location_sharing import _isoformat_utc, register_user


class RouteTests(unittest.TestCase):
    def setUp(self):
        class TestConfig:
            SECRET_KEY = "test-secret"
            TESTING = True
            GOOGLE_CLIENT_ID = ""
            GOOGLE_CLIENT_SECRET = ""
            GOOGLE_REDIRECT_URI = "http://localhost/auth/callback"
            SESSION_COOKIE_HTTPONLY = True
            SESSION_COOKIE_SAMESITE = "Lax"
            SESSION_COOKIE_SECURE = False

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def test_register_user_does_not_clear_saved_picture_when_google_omits_it(self):
        users = Mock()
        with patch("app.services.location_sharing.get_collection", return_value=users):
            register_user({"sub": "google-user", "email": "user@example.com", "name": "Test User"})

        update = users.update_one.call_args.args[1]["$set"]
        self.assertNotIn("picture", update)

    def test_register_user_persists_google_profile_picture(self):
        users = Mock()
        with patch("app.services.location_sharing.get_collection", return_value=users):
            register_user({
                "sub": "google-user",
                "email": "user@example.com",
                "name": "Test User",
                "picture": "https://example.com/avatar.png",
            })

        update = users.update_one.call_args.args[1]["$set"]
        self.assertEqual(update["picture"], "https://example.com/avatar.png")

    def test_mongo_utc_timestamps_are_serialized_with_timezone(self):
        from datetime import datetime

        self.assertEqual(
            _isoformat_utc(datetime(2026, 10, 20, 12, 30)),
            "2026-10-20T12:30:00Z",
        )

    def sign_in(self):
        with self.client.session_transaction() as session:
            session["user"] = {
                "sub": "google-user",
                "email": "user@example.com",
                "name": "Test User",
                "picture": "https://example.com/test-user.png",
            }

    def test_root_renders_public_landing_page(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Bring your people and plans together", response.data)
        self.assertIn(b"Private location sharing", response.data)
        self.assertIn(b"ux9.eu", response.data)
        self.assertIn(b'lang="en-GB"', response.data)

    def test_vercel_export_module_exposes_app(self):
        from api.index import app

        self.assertIsNotNone(app)
        response = app.test_client().get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 200)

    def test_standard_google_env_names_are_supported_for_vercel(self):
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CLIENT_ID": "vercel-client-id",
                "GOOGLE_CLIENT_SECRET": "vercel-client-secret",
                "GOOGLE_REDIRECT_URI": "https://example.vercel.app/auth/google/callback",
                "FLASK_SECRET_KEY": "vercel-secret",
                "VERCEL_GIT_COMMIT_SHA": "abcdef1234567890abcdef1234567890abcdef12",
            },
            clear=True,
        ):
            reload(config_module)
            app = create_app(config_module.Config)
            self.assertEqual(app.config["GOOGLE_CLIENT_ID"], "vercel-client-id")
            self.assertEqual(app.config["GOOGLE_CLIENT_SECRET"], "vercel-client-secret")
            self.assertEqual(app.config["GOOGLE_REDIRECT_URI"], "https://example.vercel.app/auth/google/callback")
            self.assertEqual(app.config["BUILD_COMMIT"], "abcdef123456")
            reload(config_module)

    def test_login_is_google_only_and_local_login_is_removed(self):
        response = self.client.get("/auth/login")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Google sign-in is not configured", response.data)
        self.assertIn(b"Version:", response.data)
        self.assertIn(self.app.config["BUILD_COMMIT"].encode(), response.data)
        self.assertNotIn(b"type=\"password\"", response.data)
        self.assertEqual(self.client.post("/login").status_code, 404)

    def test_language_can_be_selected_before_and_after_sign_in(self):
        response = self.client.post("/language/pt_PT", data={"next": "/"})
        self.assertEqual(response.status_code, 302)
        landing = self.client.get("/")
        self.assertIn(b'lang="pt-PT"', landing.data)
        self.assertIn("Junte as suas pessoas".encode(), landing.data)
        self.sign_in()
        with self.client.session_transaction() as browser_session:
            self.assertEqual(browser_session["locale"], "pt_PT")
        denied = self.client.post("/language/fr", data={"next": "/"})
        self.assertEqual(denied.status_code, 400)

    def test_browser_translation_keys_are_catalogued(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "static"
        pattern = re.compile(r"\bt\(\s*(['\"])(.*?)\1\s*\)")
        used = set()
        for script in static_dir.glob("*.js"):
            used.update(match.group(2) for match in pattern.finditer(script.read_text(encoding="utf-8")))
        self.assertEqual(used - set(JS_MESSAGE_IDS), set())

    def test_portuguese_browser_messages_translate_realtime_and_api_errors(self):
        self.client.post("/language/pt_PT", data={"next": "/"})
        self.sign_in()
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        catalogue = response.get_data(as_text=True).split("window.FlutuI18n = ", 1)[1].split(";</script>", 1)[0]
        messages = json.loads(catalogue)
        self.assertIn("O Supabase aceitou um tópico de teste", messages[
            "Supabase accepted an unauthorized private test topic. Realtime RLS is disabled or another SELECT policy is too broad."
        ])
        self.assertEqual(messages["invalid_payload"], "Os dados do pedido são inválidos.")
        self.assertEqual(messages["Invite by email"], "Convidar por email")
        self.assertEqual(messages["Invite by text"], "Convidar por SMS")
        self.assertEqual(messages["Invite {name} by email"], "Convidar {name} por email")
        self.assertEqual(messages["Invite {name} by text message"], "Convidar {name} por SMS")

    def test_authenticated_root_redirects_to_dashboard(self):
        self.sign_in()
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")

    def test_private_html_redirects_without_session(self):
        for path in ("/dashboard", "/contacts", "/decision", "/decision/info", "/map", "/profile"):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/")

    def test_private_apis_return_json_401_without_session(self):
        for path in ("/api/decision", "/api/contacts", "/api/location/requests"):
            with self.subTest(path=path):
                response = self.client.post(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.get_json(), {"error": "Authentication required."})
        for path in ("/api/location/overview", "/api/location/status"):
            with self.subTest(path=path):
                overview = self.client.get(path)
                self.assertEqual(overview.status_code, 401)
                self.assertEqual(overview.get_json(), {"error": "Authentication required."})
        sharing = self.client.post("/api/location/sharing", json={"enabled": True})
        self.assertEqual(sharing.status_code, 401)

    def test_push_service_worker_is_served_from_root_with_scope_headers(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.content_type)
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")
        self.assertIn("no-cache", response.headers["Cache-Control"])
        response.close()

    def test_push_public_key_only_exposes_public_vapid_key(self):
        self.app.config.update(
            VAPID_PUBLIC_KEY="public-key",
            VAPID_PRIVATE_KEY="private-key",
            VAPID_CONTACT="mailto:ops@example.com",
        )
        response = self.client.get("/api/push/vapid-public-key")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"key": "public-key"})
        self.assertNotIn("private-key", response.get_data(as_text=True))

        self.app.config["VAPID_PRIVATE_KEY"] = ""
        self.assertEqual(self.client.get("/api/push/vapid-public-key").status_code, 503)

    def test_push_subscribe_requires_authentication_and_csrf(self):
        subscription = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/token",
            "keys": {"p256dh": "p" * 32, "auth": "a" * 16},
        }
        self.assertEqual(self.client.post("/api/push/subscribe", json=subscription).status_code, 401)
        self.sign_in()
        denied = self.client.post("/api/push/subscribe", json=subscription)
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(denied.get_json(), {"error": "csrf_failed"})

    def test_push_subscribe_and_unsubscribe_use_session_owner_and_csrf(self):
        self.sign_in()
        with self.client.session_transaction() as browser_session:
            browser_session["_push_csrf_token"] = "push-csrf"
        headers = {"X-CSRF-Token": "push-csrf", "Origin": "http://localhost"}
        subscription = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/token",
            "keys": {"p256dh": "p" * 32, "auth": "a" * 16},
        }
        with patch("app.main.routes.save_subscription") as save:
            subscribed = self.client.post("/api/push/subscribe", json=subscription, headers=headers)
        self.assertEqual(subscribed.status_code, 201)
        save.assert_called_once_with("google-user", subscription)

        with patch("app.main.routes.remove_subscription", return_value=True) as remove:
            unsubscribed = self.client.post(
                "/api/push/unsubscribe", json={"endpoint": subscription["endpoint"]}, headers=headers
            )
        self.assertEqual(unsubscribed.status_code, 200)
        remove.assert_called_once_with("google-user", subscription["endpoint"])

    def test_dashboard_exposes_push_opt_in_and_csrf_token(self):
        self.sign_in()
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="push-notifications"', response.data)
        self.assertIn(b'id="push-toggle"', response.data)
        self.assertIn(b"push-notifications.js", response.data)
        with self.client.session_transaction() as browser_session:
            self.assertTrue(browser_session.get("_push_csrf_token"))

    def test_authenticated_dashboard_and_child_navigation(self):
        self.sign_in()
        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Quantum path selector", dashboard.data)
        self.assertIn(b"My contacts", dashboard.data)
        self.assertIn(b"Location map", dashboard.data)
        self.assertIn(b"My profile", dashboard.data)
        self.assertIn(b"location-sharing-indicator", dashboard.data)
        self.assertIn(b"prefers-color-scheme: dark", dashboard.data)
        self.assertIn(b"color-scheme: dark", dashboard.data)
        self.assertIn(b"#0b1220", dashboard.data)
        self.assertNotIn(b"Check a number set", dashboard.data)

        contacts = self.client.get("/contacts")
        self.assertEqual(contacts.status_code, 200)
        self.assertIn(b"Import from phone", contacts.data)
        self.assertIn(b"Import .vcf file", contacts.data)
        self.assertIn(b"parseVcard", contacts.data)
        self.assertIn(b"Saved contacts", contacts.data)
        self.assertIn(b"/dashboard", contacts.data)
        self.assertIn(b'const contactsApi = "/api/contacts"', contacts.data)
        self.assertIn(b'const inviteUrl = "http://localhost/auth/login"', contacts.data)
        self.assertIn(b"Invite by email", contacts.data)
        self.assertIn(b"Invite by text", contacts.data)
        self.assertIn(b"contact-card-actions { width: 100%; justify-content: flex-start; }", contacts.data)
        self.assertIn(b"classList.add(\"contact-action-icon\")", contacts.data)
        self.assertIn(b"aria-label", contacts.data)
        self.assertIn(b"mailto:${encodeURIComponent(contact.email)}", contacts.data)
        self.assertIn(b"sms:${encodeURIComponent(contact.tel)}", contacts.data)

        decision = self.client.get("/decision")
        self.assertEqual(decision.status_code, 200)
        self.assertIn(b"/decision/info", decision.data)
        self.assertIn(b"/dashboard", decision.data)
        self.assertIn(b"const responseText = await response.text()", decision.data)
        self.assertIn(b"non-JSON response (HTTP", decision.data)

        info = self.client.get("/decision/info")
        self.assertEqual(info.status_code, 200)
        self.assertIn(b"Back to the decision", info.data)

        location_map = self.client.get("/map")
        self.assertEqual(location_map.status_code, 200)
        self.assertIn(b"OpenStreetMap", location_map.data)
        self.assertIn(b'id="toggle-map-follow"', location_map.data)
        self.assertIn(b"aria-pressed=\"false\"", location_map.data)
        self.assertIn(b"if (mapFollowingLocations) fitMapToMarkers()", location_map.data)
        self.assertIn(b"locationChanged && mapFollowingLocations", location_map.data)
        self.assertIn(b"Back to dashboard", location_map.data)
        self.assertIn(b"calculateDistanceKm", location_map.data)
        self.assertIn(b"popupContent(location)", location_map.data)
        self.assertIn(b"refreshMarkerPopups", location_map.data)
        self.assertIn(b"Distance unavailable", location_map.data)
        self.assertIn(b"your device location is not current", location_map.data)
        self.assertIn(b"they are not currently sharing their location with you", location_map.data)
        self.assertIn(b"profileMarkerIcon", location_map.data)
        self.assertIn(b"ownProfilePicture", location_map.data)
        self.assertIn(b"https://example.com/test-user.png", location_map.data)
        self.assertIn(b"user-map-avatar", location_map.data)
        self.assertIn(b"user-map-initials", location_map.data)
        self.assertIn(b"safeProfilePicture", location_map.data)
        self.assertNotIn(b"map-icon-select", location_map.data)
        self.assertIn(b"Enable location updates", location_map.data)
        self.assertIn(b"share-controls button:disabled", location_map.data)
        self.assertIn(b"id=\"toggle-sharing\" class=\"button small-button\" type=\"button\" disabled", location_map.data)
        self.assertIn(b"id=\"stop-all\" class=\"button button-danger small-button\" type=\"button\" disabled", location_map.data)
        self.assertIn(b"every 30 seconds", location_map.data)
        self.assertIn(b"No one has authorized a request to receive your location yet", location_map.data)
        self.assertIn(b"own-location-status", location_map.data)
        self.assertIn(b"Your marker is private on this device", location_map.data)
        self.assertIn(b"startPrivateLocationTracking", location_map.data)
        self.assertIn(b"setInterval(updatePrivateLocation, 30000)", location_map.data)
        self.assertIn(b"Private on this device", location_map.data)
        self.assertIn(b"startPrivateLocationTracking();", location_map.data)
        self.assertIn(b"navigator.geolocation.getCurrentPosition", location_map.data)
        self.assertIn(b"Requesting your device location", location_map.data)
        self.assertIn(b"Location requires HTTPS", location_map.data)
        self.assertIn(b"Location permission was denied", location_map.data)
        self.assertIn(b"could not determine its location", location_map.data)

        profile = self.client.get("/profile")
        self.assertEqual(profile.status_code, 200)
        self.assertIn(b"Your map marker", profile.data)
        self.assertIn(b"Google profile photo", profile.data)
        self.assertIn(b"profile-photo", profile.data)
        self.assertIn(b"profilePhoto.replaceWith(fallback)", profile.data)
        self.assertNotIn(b"map-icon-select", profile.data)
        self.assertIn(b"Back to dashboard", profile.data)

        removed_page = self.client.get("/permutation-checker")
        self.assertEqual(removed_page.status_code, 404)
        removed_api = self.client.post("/api/check-last-number", json={"set": [1, 2]})
        self.assertEqual(removed_api.status_code, 404)

    def test_authenticated_decision_api(self):
        self.sign_in()
        with patch("app.main.routes.choose_direction", return_value=True):
            response = self.client.post("/api/decision")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"go_right": True})

    def test_decision_api_returns_json_when_quantum_provider_fails(self):
        self.sign_in()
        with patch(
            "app.main.routes.choose_direction",
            side_effect=RuntimeError("IBM Quantum job failed"),
        ):
            response = self.client.post("/api/decision")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.get_json(),
            {"error": "Could not get a new decision right now."},
        )

    def test_contacts_api_scopes_every_operation_to_signed_in_user(self):
        self.sign_in()
        saved_contacts = [{"id": "contact-1", "name": "Alex", "tel": "+15551234567", "email": "alex@example.com"}]
        with patch("app.main.routes.list_contacts", return_value=saved_contacts) as list_mock:
            response = self.client.get("/api/contacts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"contacts": saved_contacts})
        list_mock.assert_called_once_with("google-user")

        with patch("app.main.routes.add_contacts", return_value=saved_contacts) as add_mock:
            response = self.client.post("/api/contacts", json={"name": "Alex", "tel": "+15551234567"})
        self.assertEqual(response.status_code, 201)
        add_mock.assert_called_once_with("google-user", [{"name": "Alex", "tel": "+15551234567", "email": ""}])

        contact_id = "65b0e7a3a6c6f166f1c3a001"
        with patch("app.main.routes.delete_contact", return_value=True) as delete_mock:
            response = self.client.delete(f"/api/contacts/{contact_id}")
        self.assertEqual(response.status_code, 204)
        delete_mock.assert_called_once_with("google-user", contact_id)

        with patch("app.main.routes.delete_all_contacts", return_value=1) as delete_all_mock:
            response = self.client.delete("/api/contacts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"deleted": 1})
        delete_all_mock.assert_called_once_with("google-user")

    def test_contacts_api_rejects_invalid_payload_without_saving(self):
        self.sign_in()
        with patch("app.main.routes.add_contacts") as add_mock:
            response = self.client.post("/api/contacts", json={"name": "No contact details"})
        self.assertEqual(response.status_code, 400)
        add_mock.assert_not_called()

    def test_location_request_uses_only_signed_in_users_saved_contacts(self):
        self.sign_in()
        contact = {"id": "contact-1", "name": "Alex", "tel": "", "email": "alex@example.com"}
        recipient = {"id": "other-google-user", "name": "Alex", "email": "alex@example.com"}
        saved_request = {"id": "request-1", "status": "pending"}
        with patch("app.main.routes.list_contacts", return_value=[contact]), patch(
            "app.main.routes.find_user_by_email", return_value=recipient
        ) as find_mock, patch("app.main.routes.request_location", return_value=(saved_request, True)) as request_mock, patch(
            "app.main.routes.notify_users"
        ) as notify:
            response = self.client.post("/api/location/requests", json={"contact_id": "contact-1"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json(), {"request": saved_request, "created": True})
        find_mock.assert_called_once_with("alex@example.com")
        request_mock.assert_called_once_with(
            {
                "sub": "google-user",
                "email": "user@example.com",
                "name": "Test User",
                "picture": "https://example.com/test-user.png",
            },
            recipient,
        )
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1], ["other-google-user"])
        self.assertEqual(notify.call_args.kwargs["url"], "/map")

    def test_duplicate_location_request_does_not_send_push(self):
        self.sign_in()
        contact = {"id": "contact-1", "name": "Alex", "tel": "", "email": "alex@example.com"}
        recipient = {"id": "other-google-user", "name": "Alex", "email": "alex@example.com"}
        with patch("app.main.routes.list_contacts", return_value=[contact]), patch(
            "app.main.routes.find_user_by_email", return_value=recipient
        ), patch("app.main.routes.request_location", return_value=({"id": "request", "status": "pending"}, False)), patch(
            "app.main.routes.notify_users"
        ) as notify:
            response = self.client.post("/api/location/requests", json={"contact_id": "contact-1"})
        self.assertEqual(response.status_code, 200)
        notify.assert_not_called()

    def test_location_request_rejects_contact_not_owned_by_user(self):
        self.sign_in()
        with patch("app.main.routes.list_contacts", return_value=[]), patch(
            "app.main.routes.find_user_by_email"
        ) as find_mock:
            response = self.client.post("/api/location/requests", json={"contact_id": "someone-elses-contact"})
        self.assertEqual(response.status_code, 400)
        find_mock.assert_not_called()

    def test_location_sharing_requires_valid_coordinates_and_authorization(self):
        self.sign_in()
        with patch("app.main.routes.save_location", return_value=False) as save_mock:
            invalid = self.client.post(
                "/api/location/updates", json={"latitude": 91, "longitude": 0, "accuracy": 4}
            )
            self.assertEqual(invalid.status_code, 400)
            save_mock.assert_not_called()

            forbidden = self.client.post(
                "/api/location/updates", json={"latitude": 45.2, "longitude": -73.5, "accuracy": 12}
            )
        self.assertEqual(forbidden.status_code, 403)
        save_mock.assert_called_once_with(
            "google-user", 45.2, -73.5, 12, "https://example.com/test-user.png"
        )

    def test_location_request_response_is_scoped_to_signed_in_user(self):
        self.sign_in()
        accepted = {"id": "request-1", "status": "accepted", "requester_id": "requester"}
        with patch("app.main.routes.respond_to_request", return_value=accepted) as respond_mock, patch(
            "app.main.routes.notify_users"
        ) as notify:
            response = self.client.post("/api/location/requests/request-1/respond", json={"action": "accept"})
        self.assertEqual(response.status_code, 200)
        respond_mock.assert_called_once_with("google-user", "request-1", "accept")
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1], ["requester"])

    def test_cancelled_location_request_does_not_notify(self):
        self.sign_in()
        cancelled = {"id": "request-1", "status": "cancelled", "requester_id": "google-user"}
        with patch("app.main.routes.respond_to_request", return_value=cancelled), patch(
            "app.main.routes.notify_users"
        ) as notify:
            response = self.client.post("/api/location/requests/request-1/respond", json={"action": "cancel"})
        self.assertEqual(response.status_code, 200)
        notify.assert_not_called()

    def test_location_sharing_can_be_revoked_individually_or_all(self):
        self.sign_in()
        with patch("app.main.routes.revoke_share", return_value=1) as revoke_mock:
            individual = self.client.delete("/api/location/shares/request-1")
            all_shares = self.client.delete("/api/location/shares")
        self.assertEqual(individual.get_json(), {"revoked": 1})
        self.assertEqual(all_shares.get_json(), {"revoked": 1})
        revoke_mock.assert_any_call("google-user", "request-1")
        revoke_mock.assert_any_call("google-user")

    def test_location_status_and_opt_in_are_scoped_to_signed_in_user(self):
        self.sign_in()
        status = {
            "enabled": True,
            "active_recipients": 2,
            "picture": "https://example.com/avatar.png",
        }
        with patch("app.main.routes.get_sharing_status", return_value=status) as status_mock:
            response = self.client.get("/api/location/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), status)
        status_mock.assert_called_once_with("google-user")

        with patch("app.main.routes.set_sharing_enabled", return_value=True) as set_mock, patch(
            "app.main.routes.get_sharing_status", return_value=status
        ):
            enabled = self.client.post("/api/location/sharing", json={"enabled": True})
        self.assertEqual(enabled.status_code, 200)
        set_mock.assert_called_once_with("google-user", True)

    def test_location_opt_in_requires_an_active_recipient(self):
        self.sign_in()
        with patch("app.main.routes.set_sharing_enabled", return_value=False) as set_mock:
            response = self.client.post("/api/location/sharing", json={"enabled": True})
        self.assertEqual(response.status_code, 403)
        set_mock.assert_called_once_with("google-user", True)

    def test_google_oauth_state_and_callback(self):
        class GoogleConfig:
            SECRET_KEY = "test-secret"
            TESTING = True
            GOOGLE_CLIENT_ID = "test-client-id"
            GOOGLE_CLIENT_SECRET = "test-client-secret"
            GOOGLE_REDIRECT_URI = "http://localhost/auth/google/callback"
            SESSION_COOKIE_HTTPONLY = True
            SESSION_COOKIE_SAMESITE = "Lax"
            SESSION_COOKIE_SECURE = False

        app = create_app(GoogleConfig)
        client = app.test_client()
        authorization = client.get("/auth/google/login")
        self.assertEqual(authorization.status_code, 302)
        self.assertIn("accounts.google.com/o/oauth2/v2/auth", authorization.headers["Location"])
        self.assertIn("state=", authorization.headers["Location"])

        with client.session_transaction() as session:
            state = session["oauth_state"]

        google_user = {
            "sub": "google-subject",
            "email": "user@example.com",
            "email_verified": True,
            "name": "Test User",
        }
        with patch("app.auth.routes.fetch_google_user", return_value=google_user) as fetch_user:
            callback = client.get(f"/auth/google/callback?code=auth-code&state={state}")
        self.assertEqual(callback.status_code, 302)
        self.assertEqual(callback.headers["Location"], "/dashboard")
        fetch_user.assert_called_once_with(
            "auth-code",
            "test-client-id",
            "test-client-secret",
            "http://localhost/auth/google/callback",
        )
        dashboard = client.get("/dashboard")
        self.assertIn(b"user@example.com", dashboard.data)

    def test_google_oauth_rejects_invalid_state(self):
        class GoogleConfig:
            SECRET_KEY = "test-secret"
            TESTING = True
            GOOGLE_CLIENT_ID = "test-client-id"
            GOOGLE_CLIENT_SECRET = "test-client-secret"
            GOOGLE_REDIRECT_URI = "http://localhost/auth/callback"

        client = create_app(GoogleConfig).test_client()
        client.get("/auth/google/login")
        response = client.get("/auth/callback?code=auth-code&state=attacker-state")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/auth/login")
        with client.session_transaction() as session:
            self.assertNotIn("user", session)


if __name__ == "__main__":
    unittest.main()
