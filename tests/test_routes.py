import os
import unittest
from importlib import reload
from unittest.mock import patch

from app import create_app
import app.config as config_module


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

    def sign_in(self):
        with self.client.session_transaction() as session:
            session["user"] = {
                "sub": "google-user",
                "email": "user@example.com",
                "name": "Test User",
            }

    def test_root_redirects_to_google_sign_in(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/auth/login")

    def test_vercel_export_module_exposes_app(self):
        from api.index import app

        self.assertIsNotNone(app)
        response = app.test_client().get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/auth/login")

    def test_standard_google_env_names_are_supported_for_vercel(self):
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CLIENT_ID": "vercel-client-id",
                "GOOGLE_CLIENT_SECRET": "vercel-client-secret",
                "GOOGLE_REDIRECT_URI": "https://example.vercel.app/auth/google/callback",
                "FLASK_SECRET_KEY": "vercel-secret",
            },
            clear=True,
        ):
            reload(config_module)
            app = create_app(config_module.Config)
            self.assertEqual(app.config["GOOGLE_CLIENT_ID"], "vercel-client-id")
            self.assertEqual(app.config["GOOGLE_CLIENT_SECRET"], "vercel-client-secret")
            self.assertEqual(app.config["GOOGLE_REDIRECT_URI"], "https://example.vercel.app/auth/google/callback")
            reload(config_module)

    def test_login_is_google_only_and_local_login_is_removed(self):
        response = self.client.get("/auth/login")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Google sign-in is not configured", response.data)
        self.assertNotIn(b"type=\"password\"", response.data)
        self.assertEqual(self.client.post("/login").status_code, 404)

    def test_private_html_redirects_without_session(self):
        for path in ("/dashboard", "/contacts", "/decision", "/decision/info"):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/")

    def test_private_apis_return_json_401_without_session(self):
        for path in ("/api/decision", "/api/contacts"):
            with self.subTest(path=path):
                response = self.client.post(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.get_json(), {"error": "Authentication required."})

    def test_authenticated_dashboard_and_child_navigation(self):
        self.sign_in()
        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Choose a path", dashboard.data)
        self.assertIn(b"My contacts", dashboard.data)
        self.assertNotIn(b"Check a number set", dashboard.data)

        contacts = self.client.get("/contacts")
        self.assertEqual(contacts.status_code, 200)
        self.assertIn(b"Import from phone", contacts.data)
        self.assertIn(b"Import .vcf file", contacts.data)
        self.assertIn(b"parseVcard", contacts.data)
        self.assertIn(b"Saved contacts", contacts.data)
        self.assertIn(b"/dashboard", contacts.data)
        self.assertIn(b'const contactsApi = "/api/contacts"', contacts.data)

        decision = self.client.get("/decision")
        self.assertEqual(decision.status_code, 200)
        self.assertIn(b"/decision/info", decision.data)
        self.assertIn(b"/dashboard", decision.data)

        info = self.client.get("/decision/info")
        self.assertEqual(info.status_code, 200)
        self.assertIn(b"Back to the decision", info.data)

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
