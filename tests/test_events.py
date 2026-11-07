import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from bson import ObjectId
from app import create_app
from app.services.blob_storage import BlobStorageError, delete_image, download_image, upload_image
from app.services.location_search import search_locations
from app.services.events import _event_status, _nearest_event_occurrence, _normalize_dates, _normalize_points, _notify_event_members, _send_event_email, can_manage_event, create_event, delete_event, get_event, list_events, list_map_points, list_occurrences, normalize_event, respond_to_invitation, update_event


class CalendarTests(unittest.TestCase):
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
        with self.client.session_transaction() as browser_session:
            browser_session["user"] = {"sub": "google-user", "name": "Test User", "email": "user@example.com"}

    def test_calendar_page_and_apis_require_authentication(self):
        page = self.client.get("/calendar/", follow_redirects=False)
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], "/")
        for response in (
            self.client.get("/calendar/api/events"),
            self.client.get("/calendar/api/map-points"),
            self.client.post("/calendar/api/events", json={}),
        ):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.get_json(), {"error": "Authentication required."})

    def test_mutations_require_calendar_csrf_token(self):
        self.sign_in()
        response = self.client.post("/calendar/api/events", json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "csrf_failed"})

        with self.client.session_transaction() as browser_session:
            browser_session["_calendar_csrf_token"] = "calendar-csrf"
        spoofed = self.client.post(
            "/calendar/api/events", json={},
            headers={"X-CSRF-Token": "calendar-csrf", "Referer": "http://localhost.attacker.invalid/"},
        )
        self.assertEqual(spoofed.status_code, 400)

    def test_create_event_uses_authenticated_owner_and_valid_csrf(self):
        self.sign_in()
        with self.client.session_transaction() as browser_session:
            browser_session["_calendar_csrf_token"] = "calendar-csrf"
        with patch("app.calendar.routes.events.create_event", return_value={"id": "event-1"}) as create:
            response = self.client.post(
                "/calendar/api/events",
                json={"title": "Planning", "owner_id": "attacker"},
                headers={"X-CSRF-Token": "calendar-csrf", "Origin": "http://localhost"},
            )
        self.assertEqual(response.status_code, 201)
        create.assert_called_once_with("google-user", {"title": "Planning", "owner_id": "attacker"})

    def test_calendar_page_loads_authenticated_event_editor(self):
        self.sign_in()
        response = self.client.get("/calendar/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"event-location-map", response.data)
        self.assertIn(b"calendar.js", response.data)
        self.assertIn(b"__id__", response.data)
        self.assertIn(b'id="event-invitations"', response.data)
        self.assertIn(b'id="event-member-picker"', response.data)
        self.assertIn(b'.check-grid { grid-template-columns:minmax(0,1fr); }', response.data)
        self.assertIn(b'.event-detail-header { display:grid; grid-template-columns:minmax(0, 1fr) auto;', response.data)
        self.assertIn(b'.event-detail-header.has-cover { grid-template-columns:76px minmax(0, 1fr) auto; }', response.data)
        self.assertNotIn(b'event-detail-cover-placeholder', response.data)
        calendar_script = self.client.get("/static/calendar.js")
        self.assertIn(b"getPropertyValue('--link')", calendar_script.data)
        calendar_script.close()

    def test_event_member_picker_returns_linked_account_email(self):
        self.sign_in()
        linked_member = {"user_id": "member-1", "name": "Alex", "email": "alex@example.com"}
        with patch("app.calendar.routes.events.list_addable_members", return_value=[linked_member]):
            response = self.client.get("/calendar/api/event-members")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"members": [linked_member]})

    def test_event_invitation_response_requires_csrf_and_updates_current_member(self):
        self.sign_in()
        denied = self.client.post("/calendar/api/events/event-1/invitation", json={"action": "accept"})
        self.assertEqual(denied.status_code, 400)
        with self.client.session_transaction() as browser_session:
            browser_session["_calendar_csrf_token"] = "calendar-csrf"
        accepted = {"id": "event-1", "title": "Planning", "members": [], "map_points": []}
        with patch("app.calendar.routes.events.respond_to_invitation", return_value=accepted) as respond:
            response = self.client.post(
                "/calendar/api/events/event-1/invitation", json={"action": "accept"},
                headers={"X-CSRF-Token": "calendar-csrf", "Origin": "http://localhost"},
            )
        self.assertEqual(response.status_code, 200)
        respond.assert_called_once_with("google-user", "event-1", "accept")

    def test_event_invitation_requires_authentication(self):
        response = self.client.post("/calendar/api/events/event-1/invitation", json={"action": "accept"})
        self.assertEqual(response.status_code, 401)

    def test_calendar_page_is_translated_into_portuguese(self):
        self.client.post("/language/pt_PT", data={"next": "/"})
        self.sign_in()
        response = self.client.get("/calendar/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Calendário de eventos".encode(), response.data)
        self.assertIn("Datas e horas".encode(), response.data)
        self.assertIn("Diariamente".encode(), response.data)
        self.assertNotIn(b'id="event-status"', response.data)
        page = response.get_data(as_text=True)
        catalogue = page.split("window.FlutuI18n = ", 1)[1].split(";</script>", 1)[0]
        messages = json.loads(catalogue)
        self.assertEqual(messages["Monday"], "segunda-feira")
        self.assertEqual(messages["Sunday"], "domingo")
        self.assertEqual(messages["Event members"], "Membros do evento")
        self.assertEqual(messages["Invitation pending"], "Convite pendente")
        self.assertIn(".weekday-picker[hidden] { display:none; }", page)

    def test_location_map_renders_event_marker_layer_endpoint(self):
        self.client.post("/language/pt_PT", data={"next": "/"})
        self.sign_in()
        response = self.client.get("/map")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/calendar/api/map-points", response.data)
        self.assertIn(b'id="show-open-events"', response.data)
        self.assertIn("Mostrar eventos abertos".encode(), response.data)
        self.assertIn(b"...markers.values(), ...eventMarkers.values()", response.data)
        self.assertIn(b"await loadEventMapPoints();\n      fitMapToMarkers();", response.data)
        self.assertIn(b"Open event calendar", response.data)
        self.assertIn(b"location.email", response.data)

    def test_private_blob_image_requires_authentication_and_sets_safe_headers(self):
        event_id = "507f1f77bcf86cd799439011"
        image_id = "550e8400-e29b-41d4-a716-446655440000"
        denied = self.client.get(f"/calendar/api/events/{event_id}/images/{image_id}")
        self.assertEqual(denied.status_code, 401)
        self.sign_in()
        with patch("app.calendar.routes.events.get_event_image", return_value=("image/png", b"image-bytes")) as load:
            response = self.client.get(f"/calendar/api/events/{event_id}/images/{image_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"image-bytes")
        self.assertEqual(response.headers["Cache-Control"], "private, no-cache")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        load.assert_called_once_with("google-user", event_id, image_id)

    def test_event_api_returns_authentication_proxy_not_blob_path(self):
        self.sign_in()
        event = {
            "id": "507f1f77bcf86cd799439011",
            "cover_image_id": "550e8400-e29b-41d4-a716-446655440001",
            "has_cover_image": True,
            "map_points": [{"image_id": "550e8400-e29b-41d4-a716-446655440000", "has_image": True}],
        }
        with patch("app.calendar.routes.events.list_events", return_value=[event]):
            response = self.client.get("/calendar/api/events")
        self.assertEqual(response.status_code, 200)
        point = response.get_json()["events"][0]["map_points"][0]
        self.assertEqual(point["image_url"], "/calendar/api/events/507f1f77bcf86cd799439011/images/550e8400-e29b-41d4-a716-446655440000")
        self.assertNotIn("image_path", point)
        self.assertEqual(
            response.get_json()["events"][0]["cover_image_url"],
            "/calendar/api/events/507f1f77bcf86cd799439011/cover-image",
        )

    def test_event_cover_image_route_is_private_and_sets_safe_headers(self):
        event_id = "507f1f77bcf86cd799439011"
        denied = self.client.get(f"/calendar/api/events/{event_id}/cover-image")
        self.assertEqual(denied.status_code, 401)
        self.sign_in()
        with patch("app.calendar.routes.events.get_event_cover_image", return_value=("image/webp", b"small-image")) as load:
            response = self.client.get(f"/calendar/api/events/{event_id}/cover-image")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"small-image")
        self.assertEqual(response.headers["Cache-Control"], "private, no-cache")
        load.assert_called_once_with("google-user", event_id)

    def test_map_points_api_can_filter_to_open_events(self):
        self.sign_in()
        with patch("app.calendar.routes.events.list_map_points", return_value=[]) as list_points:
            response = self.client.get("/calendar/api/map-points?status=open")
        self.assertEqual(response.status_code, 200)
        list_points.assert_called_once_with("google-user", open_only=True)

    def test_map_points_api_does_not_filter_when_open_events_toggle_is_off(self):
        self.sign_in()
        with patch("app.calendar.routes.events.list_map_points", return_value=[]) as list_points:
            response = self.client.get("/calendar/api/map-points")
        self.assertEqual(response.status_code, 200)
        list_points.assert_called_once_with("google-user", open_only=False)

    def test_map_points_include_the_next_event_occurrence(self):
        start_at = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
        event = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "title": "Planning",
            "status": "open",
            "dates": [{
                "start_at": start_at.isoformat(),
                "end_at": (start_at + timedelta(hours=1)).isoformat(),
            }],
            "map_points": [{"label": "Venue", "latitude": 38.7, "longitude": -9.1}],
        }
        collection = Mock()
        collection.find.return_value = [event]
        with patch("app.services.events.get_collection", return_value=collection):
            points = list_map_points("google-user", open_only=True)
        self.assertEqual(points[0]["start_at"], start_at.isoformat(timespec="seconds").replace("+00:00", "Z"))

    def test_open_map_points_filter_uses_date_derived_status(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        events = [
            {
                "_id": ObjectId("507f1f77bcf86cd799439011"),
                "title": "Future event",
                "status": "closed",
                "dates": [{"start_at": (now + timedelta(days=1)).isoformat(), "end_at": (now + timedelta(days=1, hours=1)).isoformat()}],
                "map_points": [{"label": "Future", "latitude": 38.7, "longitude": -9.1}],
            },
            {
                "_id": ObjectId("507f1f77bcf86cd799439012"),
                "title": "Past event",
                "status": "open",
                "dates": [{"start_at": (now - timedelta(days=2)).isoformat(), "end_at": (now - timedelta(days=2) + timedelta(hours=1)).isoformat()}],
                "map_points": [{"label": "Past", "latitude": 38.8, "longitude": -9.2}],
            },
        ]
        collection = Mock()
        collection.find.return_value = events
        with patch("app.services.events.get_collection", return_value=collection):
            points = list_map_points("google-user", open_only=True)
        self.assertEqual([point["title"] for point in points], ["Future event"])
        self.assertEqual(points[0]["status"], "open")
        self.assertNotIn("status", collection.find.call_args.args[0])

    def test_map_points_choose_the_next_matching_recurrence(self):
        event = {"dates": [{
            "start_at": "2026-11-02T10:00:00Z",
            "end_at": "2026-11-02T11:00:00Z",
            "recurrence": {
                "frequency": "weekly",
                "interval": 1,
                "weekdays": [0],
                "until": "2026-11-30T10:00:00Z",
            },
        }]}
        now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
        self.assertEqual(_nearest_event_occurrence(event, now), "2026-11-09T10:00:00Z")

    def test_location_search_requires_auth_and_returns_normalized_results(self):
        denied = self.client.get("/calendar/api/location-search?q=Lisbon")
        self.assertEqual(denied.status_code, 401)
        self.sign_in()
        response_data = [{"lat": "38.7223", "lon": "-9.1393", "display_name": "Lisbon, Portugal"}]
        with patch("app.services.location_search.requests.get") as get:
            get.return_value.json.return_value = response_data
            response = self.client.get("/calendar/api/location-search?q=Lisbon")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["locations"], [{
            "label": "Lisbon, Portugal", "latitude": 38.7223, "longitude": -9.1393,
        }])
        self.assertEqual(get.call_args.kwargs["params"]["q"], "Lisbon")

    def test_location_search_rejects_empty_query(self):
        with self.assertRaisesRegex(ValueError, "invalid_location_query"):
            search_locations(" ")

    def test_create_event_uploads_image_and_persists_only_blob_reference(self):
        collection = Mock()
        with patch("app.services.events.get_collection", return_value=collection), \
             patch("app.services.events.blob_storage.new_image_id", return_value="550e8400-e29b-41d4-a716-446655440000"), \
             patch("app.services.events.blob_storage.upload_image", return_value="calendar/event/image.png") as upload:
            result = create_event("google-user", {
                "title": "Planning",
                "dates": [{"start_at": "2026-11-05T10:00:00Z", "end_at": "2026-11-05T11:00:00Z"}],
                "map_points": [{
                    "label": "Venue", "latitude": 38.7, "longitude": -9.1,
                    "image": "data:image/png;base64,eA==",
                }],
            })
        saved = collection.insert_one.call_args.args[0]
        self.assertNotIn("image_data", saved["map_points"][0])
        self.assertEqual(saved["map_points"][0]["image_path"], "calendar/event/image.png")
        self.assertTrue(result["map_points"][0]["has_image"])
        upload.assert_called_once_with(
            str(saved["_id"]), "550e8400-e29b-41d4-a716-446655440000", "image/png", b"x"
        )

    def test_create_event_stores_cover_image_as_private_blob_reference(self):
        collection = Mock()
        with patch("app.services.events.get_collection", return_value=collection), \
             patch("app.services.events.blob_storage.new_image_id", return_value="550e8400-e29b-41d4-a716-446655440000"), \
             patch("app.services.events.blob_storage.upload_image", return_value="calendar/event/cover.webp") as upload:
            result = create_event("google-user", {
                "title": "Planning",
                "dates": [{"start_at": "2026-11-05T10:00:00Z", "end_at": "2026-11-05T11:00:00Z"}],
                "cover_image": "data:image/webp;base64,eA==",
            })

        saved = collection.insert_one.call_args.args[0]
        self.assertNotIn("cover_image_data", saved)
        self.assertEqual(saved["cover_image_path"], "calendar/event/cover.webp")
        self.assertEqual(result["cover_image_id"], "550e8400-e29b-41d4-a716-446655440000")
        self.assertTrue(result["has_cover_image"])
        upload.assert_called_once_with(
            str(saved["_id"]), "550e8400-e29b-41d4-a716-446655440000", "image/webp", b"x"
        )

    def test_deleting_event_deletes_all_associated_images(self):
        event_id = "507f1f77bcf86cd799439011"
        image_paths = [
            "calendar/event/first-pin.webp",
            "calendar/event/second-pin.jpg",
            "calendar/event/cover.png",
        ]
        collection = Mock()
        collection.find_one.return_value = {
            "owner_id": "google-user",
            "map_points": [
                {"image_path": image_paths[0]},
                {"image_path": image_paths[1]},
                {"label": "No photo"},
            ],
            "cover_image_path": image_paths[2],
        }
        collection.delete_one.return_value.deleted_count = 1
        with patch("app.services.events.get_collection", return_value=collection), \
             patch("app.services.events.blob_storage.delete_image") as delete_image:
            deleted = delete_event("google-user", event_id)

        self.assertTrue(deleted)
        self.assertEqual(
            [call.args[0] for call in delete_image.call_args_list], image_paths
        )

    def test_event_cover_accepts_ui_limit_above_pin_image_limit(self):
        image = "data:image/webp;base64," + base64.b64encode(b"x" * (32 * 1024)).decode("ascii")
        normalized = normalize_event({
            "title": "Planning",
            "dates": [{"start_at": "2026-11-05T10:00:00Z", "end_at": "2026-11-05T11:00:00Z"}],
            "cover_image": image,
        }, "google-user")
        self.assertEqual(normalized["cover_image_data"], image)

    def test_create_event_allows_multiple_events_on_same_date(self):
        collection = Mock()
        payload = {
            "title": "Planning",
            "dates": [{"start_at": "2026-11-05T10:00:00Z", "end_at": "2026-11-05T11:00:00Z"}],
        }
        with patch("app.services.events.get_collection", return_value=collection):
            first = create_event("google-user", payload)
            second = create_event("google-user", payload)

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(collection.insert_one.call_count, 2)

    def test_blob_sdk_uses_private_access_for_uploads_and_downloads(self):
        sdk = Mock()
        sdk.put_blob.return_value.pathname = "calendar/event/pin.webp"
        sdk.get_blob.return_value.metadata.content_type = "image/webp"
        sdk.get_blob.return_value.body = b"compressed-image"
        with patch("app.services.blob_storage._sdk", return_value=sdk):
            path = upload_image("event", "image", "image/webp", b"compressed-image")
            downloaded = download_image(path)
            delete_image(path)
        self.assertEqual(path, "calendar/event/pin.webp")
        self.assertEqual(downloaded, ("image/webp", b"compressed-image"))
        sdk.put_blob.assert_called_once_with(
            "calendar/event/image.webp", b"compressed-image", access="private",
            content_type="image/webp", add_random_suffix=True,
        )
        sdk.get_blob.assert_called_once_with(path, access="private")
        sdk.delete_blob.assert_called_once_with(path)

    def test_blob_download_rejects_non_image_content_types(self):
        sdk = Mock()
        sdk.get_blob.return_value.metadata.content_type = "text/html"
        with patch("app.services.blob_storage._sdk", return_value=sdk), \
             self.assertRaises(BlobStorageError):
            download_image("calendar/event/pin.webp")

    def test_blob_http_fallback_uploads_to_private_store(self):
        response = Mock()
        response.json.return_value = {"pathname": "calendar/event/pin.webp"}
        fake_token = "vercel_blob_rw_teststore_faketoken"
        with patch("app.services.blob_storage._sdk", return_value=None), \
             patch.dict("os.environ", {"BLOB_READ_WRITE_TOKEN": fake_token}), \
             patch("app.services.blob_storage.requests.put", return_value=response) as put:
            path = upload_image("event", "image", "image/webp", b"compressed-image")

        self.assertEqual(path, "calendar/event/pin.webp")
        headers = put.call_args.kwargs["headers"]
        self.assertEqual(headers["x-vercel-blob-access"], "private")
        self.assertEqual(headers["Authorization"], f"Bearer {fake_token}")
        self.assertEqual(headers["x-content-type"], "image/webp")

    def test_blob_http_fallback_downloads_private_image(self):
        response = Mock()
        response.headers = {"Content-Type": "image/webp"}
        response.iter_content.return_value = [b"compressed-image"]
        fake_token = "vercel_blob_rw_teststore_faketoken"
        with patch("app.services.blob_storage._sdk", return_value=None), \
             patch.dict("os.environ", {"BLOB_READ_WRITE_TOKEN": fake_token}), \
             patch("app.services.blob_storage.requests.get", return_value=response) as get:
            image = download_image("calendar/event/pin.webp")

        self.assertEqual(image, ("image/webp", b"compressed-image"))
        self.assertEqual(
            get.call_args.args[0],
            "https://teststore.private.blob.vercel-storage.com/calendar/event/pin.webp",
        )
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], f"Bearer {fake_token}")
        response.close.assert_called_once()

    def test_blob_http_fallback_downloads_event_cover_above_pin_image_limit(self):
        response = Mock()
        response.headers = {"Content-Type": "image/webp"}
        response.iter_content.return_value = [b"x" * (32 * 1024)]
        fake_token = "vercel_blob_rw_teststore_faketoken"
        with patch("app.services.blob_storage._sdk", return_value=None), \
             patch.dict("os.environ", {"BLOB_READ_WRITE_TOKEN": fake_token}), \
             patch("app.services.blob_storage.requests.get", return_value=response):
            image = download_image("calendar/event/cover.webp")

        self.assertEqual(image, ("image/webp", b"x" * (32 * 1024)))

    def test_blob_http_fallback_deletes_blob_path(self):
        response = Mock()
        fake_token = "vercel_blob_rw_teststore_faketoken"
        with patch("app.services.blob_storage._sdk", return_value=None), \
             patch.dict("os.environ", {"BLOB_READ_WRITE_TOKEN": fake_token}), \
             patch("app.services.blob_storage.requests.post", return_value=response) as post:
            delete_image("calendar/event/pin.webp")

        self.assertEqual(post.call_args.kwargs["json"], {"urls": ["calendar/event/pin.webp"]})
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], f"Bearer {fake_token}")

    def test_calendar_date_requires_timezone_and_end_after_start(self):
        dates = [{"start_at": "2026-11-05T10:00:00Z", "end_at": "2026-11-05T12:00:00Z"}]
        self.assertEqual(_normalize_dates(dates)[0]["start_at"], "2026-11-05T10:00:00Z")
        for invalid in (
            [{"start_at": "2026-11-05T10:00:00", "end_at": "2026-11-05T12:00:00Z"}],
            [{"start_at": "2026-11-05T12:00:00Z", "end_at": "2026-11-05T10:00:00Z"}],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                _normalize_dates(invalid)
        with self.assertRaisesRegex(ValueError, "invalid_recurrence"):
            _normalize_dates([{
                "start_at": "2026-11-05T10:00:00Z",
                "end_at": "2026-11-05T11:00:00Z",
                "recurrence": {"frequency": [], "until": "2026-11-12T10:00:00Z"},
            }])

    def test_daily_recurrence_is_bounded_and_normalized(self):
        date = {
            "start_at": "2026-11-05T10:00:00Z",
            "end_at": "2026-11-05T11:00:00Z",
            "recurrence": {"frequency": "daily", "interval": 2, "until": "2026-11-12T10:00:00Z"},
        }
        normalized = _normalize_dates([date])[0]
        self.assertEqual(normalized["recurrence"]["frequency"], "daily")
        self.assertEqual(normalized["recurrence"]["interval"], 2)

    def test_daily_recurrence_expands_only_dates_in_requested_range(self):
        collection = Mock()
        collection.find.return_value = [{
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "title": "Planning",
            "status": "open",
            "dates": [{
                "start_at": "2026-11-05T10:00:00Z",
                "end_at": "2026-11-05T11:00:00Z",
                "recurrence": {"frequency": "daily", "interval": 1, "until": "2026-11-10T10:00:00Z"},
            }],
        }]
        with patch("app.services.events.get_collection", return_value=collection):
            result = list_occurrences("google-user", "2026-11-06T00:00:00Z", "2026-11-10T00:00:00Z")
        self.assertEqual([item["start_at"] for item in result], [
            "2026-11-06T10:00:00Z", "2026-11-07T10:00:00Z", "2026-11-08T10:00:00Z", "2026-11-09T10:00:00Z"
        ])

    def test_weekly_recurrence_normalizes_selected_weekdays(self):
        normalized = normalize_event({
            "title": "Planning",
            "dates": [{
                "start_at": "2026-11-02T10:00:00Z",
                "end_at": "2026-11-02T11:00:00Z",
                "recurrence": {
                    "frequency": "weekly",
                    "interval": 1,
                    "until": "2026-11-11T10:00:00Z",
                    "weekdays": [0, 2],
                },
            }],
        }, "google-user")

        self.assertEqual(normalized["dates"][0]["recurrence"]["weekdays"], [0, 2])

    def test_weekly_recurrence_expands_selected_weekdays_only(self):
        collection = Mock()
        collection.find.return_value = [{
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "title": "Planning",
            "status": "open",
            "dates": [{
                "start_at": "2026-11-02T10:00:00Z",
                "end_at": "2026-11-02T11:00:00Z",
                "recurrence": {
                    "frequency": "weekly",
                    "interval": 1,
                    "until": "2026-11-11T10:00:00Z",
                    "weekdays": [0, 2],
                },
            }],
        }]
        with patch("app.services.events.get_collection", return_value=collection):
            result = list_occurrences("google-user", "2026-11-02T00:00:00Z", "2026-11-11T23:59:59Z")

        self.assertEqual([item["start_at"] for item in result], [
            "2026-11-02T10:00:00Z", "2026-11-04T10:00:00Z",
            "2026-11-09T10:00:00Z", "2026-11-11T10:00:00Z",
        ])

    def test_event_status_is_derived_from_all_dates_and_occurrence_end(self):
        now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
        self.assertEqual(_event_status({"dates": [
            {"start_at": "2026-11-05T10:00:00Z", "end_at": "2026-11-05T11:00:00Z"},
            {"start_at": "2026-11-06T11:30:00Z", "end_at": "2026-11-06T12:30:00Z"},
        ]}, now), "open")
        self.assertEqual(_event_status({"dates": [
            {"start_at": "2026-11-05T10:00:00Z", "end_at": "2026-11-05T11:00:00Z"},
        ]}, now), "closed")

    def test_recurring_event_status_stays_open_until_last_occurrence_ends(self):
        now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
        event = {"dates": [{
            "start_at": "2026-11-02T10:00:00Z",
            "end_at": "2026-11-02T11:00:00Z",
            "recurrence": {
                "frequency": "weekly",
                "interval": 1,
                "weekdays": [0],
                "until": "2026-11-30T10:00:00Z",
            },
        }]}
        self.assertEqual(_event_status(event, now), "open")
        event["dates"][0]["recurrence"]["until"] = "2026-11-02T10:00:00Z"
        self.assertEqual(_event_status(event, now), "closed")

    def test_event_status_input_is_ignored(self):
        normalized = normalize_event({
            "title": "Planning",
            "status": "closed",
            "dates": [{"start_at": "2026-11-07T10:00:00Z", "end_at": "2026-11-07T11:00:00Z"}],
        }, "google-user")
        self.assertNotIn("status", normalized)

    def test_guests_and_conversations_must_belong_to_existing_relationships(self):
        contact_id = "507f1f77bcf86cd799439012"
        contacts = Mock()
        contacts.find.return_value = [{"_id": ObjectId(contact_id)}]
        payload = {
            "title": "Planning",
            "dates": [{"start_at": "2026-11-05T10:00:00Z", "end_at": "2026-11-05T11:00:00Z"}],
            "guest_contact_ids": [contact_id],
            "conversation_ids": ["507f1f77bcf86cd799439013"],
        }
        with patch("app.services.events.get_collection", return_value=contacts), \
               patch("app.services.events.list_addable_members", return_value=[]), \
             patch("app.services.chat.is_active_member", return_value=True) as is_member:
            result = normalize_event(payload, "google-user")
        self.assertEqual(result["guest_contact_ids"], [contact_id])
        is_member.assert_called_once_with("507f1f77bcf86cd799439013", "google-user")

        contacts.find.return_value = []
        with patch("app.services.events.get_collection", return_value=contacts), \
               patch("app.services.events.list_addable_members", return_value=[]), \
             patch("app.services.chat.is_active_member", return_value=True), \
             self.assertRaisesRegex(ValueError, "invalid_guests"):
            normalize_event(payload, "google-user")

    def test_guest_contact_linked_to_account_creates_pending_viewer_invite(self):
        contact_id = "507f1f77bcf86cd799439019"
        contacts = Mock()
        contacts.find.return_value = [{"_id": ObjectId(contact_id)}]
        linked_account = {
            "contact_id": contact_id,
            "user_id": "guest-user",
            "name": "Alex Guest",
            "email": "alex@example.com",
        }
        payload = {
            "title": "Planning",
            "dates": [{"start_at": "2026-11-07T10:00:00Z", "end_at": "2026-11-07T11:00:00Z"}],
            "guest_contact_ids": [contact_id],
        }
        with patch("app.services.events.get_collection", return_value=contacts), \
             patch("app.services.events.list_addable_members", return_value=[linked_account]):
            normalized = normalize_event(payload, "owner-user")
        self.assertEqual(normalized["members"], [{
            "user_id": "guest-user",
            "name": "Alex Guest",
            "email": "alex@example.com",
            "picture": "",
            "role": "viewer",
            "status": "pending",
        }])
        event = {
            "_id": ObjectId("507f1f77bcf86cd799439020"),
            "owner_id": "owner-user",
            "title": "Planning",
            "dates": payload["dates"],
            **normalized,
        }
        collection = Mock()
        collection.find.return_value = [event]
        with patch("app.services.events.get_collection", return_value=collection):
            guest_events = list_events("guest-user")
        self.assertEqual(len(guest_events), 1)
        self.assertEqual(guest_events[0]["viewer_status"], "pending")

    def test_registered_contact_is_removed_from_guests_and_added_as_member(self):
        contact_id = "507f1f77bcf86cd799439021"
        contacts = Mock()
        contacts.find.return_value = [{"_id": ObjectId(contact_id)}]
        with patch("app.services.events.get_collection", return_value=contacts), \
             patch("app.services.events.list_addable_members", return_value=[{
                 "contact_id": contact_id,
                 "user_id": "guest-user",
                 "name": "Alex Guest",
                 "email": "alex@example.com",
             }]):
            normalized = normalize_event({
                "title": "Planning",
                "dates": [{"start_at": "2026-11-07T10:00:00Z", "end_at": "2026-11-07T11:00:00Z"}],
                "guest_contact_ids": [contact_id],
            }, "owner-user")
        self.assertEqual(normalized["guest_contact_ids"], [])
        self.assertEqual(normalized["members"], [{
            "user_id": "guest-user",
            "name": "Alex Guest",
            "email": "alex@example.com",
            "picture": "",
            "role": "viewer",
            "status": "pending",
        }])

    def test_event_members_are_visible_to_accepted_guest(self):
        member_user = "guest-user"
        event = {
            "_id": ObjectId("507f1f77bcf86cd799439014"),
            "owner_id": "google-user",
            "title": "Planning",
            "status": "open",
            "dates": [{"start_at": "2026-11-05T10:00:00Z", "end_at": "2026-11-05T11:00:00Z"}],
            "members": [{"user_id": member_user, "role": "admin", "status": "accepted"}],
        }
        collection = Mock()
        collection.find.return_value = [event]
        with patch("app.services.events.get_collection", return_value=collection):
            result = list_events(member_user)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["members"][0]["user_id"], member_user)

        with patch("app.services.events.list_addable_members", return_value=[{
            "user_id": member_user, "name": "Guest", "email": "guest@example.com",
        }]):
            normalized = normalize_event({
                "title": "Planning",
                "dates": [{"start_at": "2026-11-05T10:00:00Z", "end_at": "2026-11-05T11:00:00Z"}],
                "members": [{"user_id": member_user, "role": "editor", "status": "accepted"}],
            }, "google-user")
        self.assertEqual(normalized["members"][0]["user_id"], member_user)
        self.assertEqual(normalized["members"][0]["role"], "editor")
        self.assertEqual(normalized["members"][0]["status"], "pending")

    def test_pending_event_invitation_is_listed_and_can_be_accepted(self):
        event_id = ObjectId("507f1f77bcf86cd799439015")
        event = {
            "_id": event_id,
            "owner_id": "owner-user",
            "title": "Planning",
            "dates": [{"start_at": "2026-11-07T10:00:00Z", "end_at": "2026-11-07T11:00:00Z"}],
            "members": [{
                "user_id": "guest-user", "name": "Alex", "email": "alex@example.com",
                "picture": "https://example.com/alex.png",
                "role": "editor", "status": "pending",
            }],
        }
        accepted_event = {**event, "members": [{**event["members"][0], "status": "accepted"}]}
        collection = Mock()
        collection.find.return_value = [event]
        collection.find_one.return_value = event
        collection.find_one_and_update.return_value = accepted_event
        with patch("app.services.events.get_collection", return_value=collection):
            listed = list_events("guest-user")
            fetched = get_event("guest-user", str(event_id))
            accepted = respond_to_invitation("guest-user", str(event_id), "accept")
        self.assertEqual(listed[0]["viewer_status"], "pending")
        self.assertEqual(listed[0]["members"][0]["email"], "alex@example.com")
        self.assertEqual(fetched["viewer_role"], "editor")
        self.assertEqual(accepted["viewer_status"], "accepted")
        self.assertTrue(can_manage_event(accepted_event, "guest-user"))
        self.assertIn("pending", str(collection.find.call_args.args[0]))
        self.assertEqual(collection.find_one_and_update.call_args.args[1]["$set"]["members.$.status"], "accepted")

    def test_viewer_role_cannot_manage_or_delete_event(self):
        viewer_event = {
            "owner_id": "owner-user",
            "members": [{"user_id": "viewer-user", "role": "viewer", "status": "accepted"}],
        }
        self.assertFalse(can_manage_event(viewer_event, "viewer-user"))
        collection = Mock()
        collection.find_one.return_value = viewer_event
        with patch("app.services.events.get_collection", return_value=collection):
            self.assertFalse(delete_event("viewer-user", "507f1f77bcf86cd799439015"))

    def test_editor_update_preserves_owner_managed_associations(self):
        event_id = "507f1f77bcf86cd799439016"
        previous = {
            "_id": ObjectId(event_id),
            "owner_id": "owner-user",
            "title": "Planning",
            "dates": [{"start_at": "2026-11-07T10:00:00Z", "end_at": "2026-11-07T11:00:00Z"}],
            "guest_contact_ids": ["owner-contact"],
            "conversation_ids": ["owner-conversation"],
            "members": [{"user_id": "editor-user", "name": "Editor", "email": "editor@example.com", "picture": "https://example.com/editor.png", "role": "editor", "status": "accepted"}],
            "map_points": [],
        }
        normalized = {
            "title": "Updated planning",
            "description": "",
            "dates": previous["dates"],
            "guest_contact_ids": ["attacker-contact"],
            "conversation_ids": ["attacker-conversation"],
            "members": [{"user_id": "other-user", "name": "Other", "email": "other@example.com", "picture": "https://example.com/other.png", "role": "editor", "status": "pending"}],
            "map_points": [],
        }
        collection = Mock()
        collection.find_one.return_value = previous
        collection.find_one_and_update.side_effect = lambda _query, update, **_kwargs: {**previous, **update["$set"]}
        with patch("app.services.events.get_collection", return_value=collection), \
             patch("app.services.events.normalize_event", return_value=normalized), \
             patch("app.services.events._notify_event_members") as notify:
            result = update_event("editor-user", event_id, {"title": "Updated planning"})
        self.assertEqual(result["guest_contact_ids"], ["owner-contact"])
        self.assertEqual(result["conversation_ids"], ["owner-conversation"])
        self.assertEqual(result["members"][0]["user_id"], "editor-user")
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1], "editor-user")
        self.assertEqual(notify.call_args.args[2], set())

    def test_owner_save_notifies_new_pending_event_member(self):
        event_id = "507f1f77bcf86cd799439018"
        previous = {
            "_id": ObjectId(event_id),
            "owner_id": "owner-user",
            "title": "Planning",
            "dates": [{"start_at": "2026-11-07T10:00:00Z", "end_at": "2026-11-07T11:00:00Z"}],
            "members": [],
            "map_points": [],
        }
        normalized = {
            "title": "Planning updated",
            "description": "",
            "dates": previous["dates"],
            "guest_contact_ids": [],
            "conversation_ids": [],
            "members": [{"user_id": "new-user", "name": "New", "email": "new@example.com", "picture": "https://example.com/new.png", "role": "editor", "status": "pending"}],
            "map_points": [],
        }
        collection = Mock()
        collection.find_one.return_value = previous
        collection.find_one_and_update.side_effect = lambda _query, update, **_kwargs: {**previous, **update["$set"]}
        with patch("app.services.events.get_collection", return_value=collection), \
             patch("app.services.events.normalize_event", return_value=normalized), \
             patch("app.services.events._notify_event_members") as notify:
            update_event("owner-user", event_id, {"title": "Planning updated"})
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1], "owner-user")
        self.assertEqual(notify.call_args.args[2], {"new-user"})

    def test_event_save_notifies_members_and_emails_guest_without_duplicate(self):
        guest_contact_id = "507f1f77bcf86cd799439017"
        event = {
            "id": "event-1",
            "owner_id": "owner-user",
            "title": "Planning",
            "guest_contact_ids": [guest_contact_id],
            "members": [
                {"user_id": "accepted-user", "name": "Accepted", "email": "shared@example.com", "picture": "https://example.com/accepted.png", "status": "accepted"},
                {"user_id": "pending-user", "name": "Pending", "email": "pending@example.com", "picture": "https://example.com/pending.png", "status": "pending"},
            ],
        }
        contacts = Mock()
        contacts.find.return_value = [{"name": "Guest", "email": "guest@example.com"}]
        users = Mock()
        users.find_one.return_value = {"email": "owner@example.com"}

        def collection_for(name):
            return contacts if name == "contacts" else users

        self.app.config["RESEND_API_KEY"] = "test-resend-key"
        self.app.config["VAPID_PUBLIC_KEY"] = "test-public-vapid-key"
        self.app.config["VAPID_PRIVATE_KEY"] = "test-private-vapid-key"
        self.app.config["VAPID_CONTACT"] = "mailto:test@example.com"
        with self.app.app_context(), \
             patch("app.services.events.get_collection", side_effect=collection_for), \
             patch("app.services.push_notifications.notify_users") as notify, \
             patch("app.services.events._send_event_email") as send_email:
            _notify_event_members(event, "owner-user", ["pending-user"])

        self.assertEqual(notify.call_count, 2)
        self.assertEqual(notify.call_args_list[0].args[1], ["pending-user"])
        self.assertEqual(notify.call_args_list[1].args[1], ["accepted-user"])
        self.assertEqual(notify.call_args_list[0].kwargs["exclude_ids"], {"owner-user"})
        self.assertEqual(notify.call_args_list[1].kwargs["exclude_ids"], {"owner-user"})
        self.assertEqual(send_email.call_count, 3)
        self.assertEqual(send_email.call_args_list[0].args[2], "shared@example.com")
        self.assertEqual(send_email.call_args_list[1].args[2], "pending@example.com")
        self.assertEqual(send_email.call_args_list[2].args[2], "guest@example.com")
        self.assertTrue(send_email.call_args_list[2].kwargs["guest"])

    def test_guest_email_uses_resend_and_does_not_link_to_private_calendar(self):
        self.app.config["RESEND_API_KEY"] = "test-resend-key"
        self.app.config["EMAIL_FROM"] = "Flutu <events@example.com>"
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with self.app.test_request_context("/calendar/"), patch("app.services.events.urllib_request.urlopen", return_value=response) as send:
            _send_event_email(
                self.app, {"title": "Planning <private>"}, "guest@example.com", "Guest",
                invitation=True, guest=True,
            )
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], ["guest@example.com"])
        self.assertEqual(payload["from"], "Flutu <events@example.com>")
        self.assertIn("Planning &lt;private&gt;", payload["html"])
        self.assertIn("contact the event organizer", payload["html"])
        self.assertNotIn("Open the calendar", payload["html"])

    def test_map_point_validates_coordinates_and_uploaded_pin(self):
        points = _normalize_points([{"label": "Hall", "latitude": 38.7, "longitude": -9.1}])
        self.assertEqual(points[0]["label"], "Hall")
        with self.assertRaises(ValueError):
            _normalize_points([{"latitude": 91, "longitude": 0}])
        with self.assertRaises(ValueError):
            _normalize_points([{"latitude": 0, "longitude": 0, "image": "data:image/svg+xml;base64,PHN2Zz4="}])
        oversize = base64.b64encode(b"x" * (24 * 1024 + 1)).decode("ascii")
        with self.assertRaises(ValueError):
            _normalize_points([{"latitude": 0, "longitude": 0, "image": f"data:image/webp;base64,{oversize}"}])


if __name__ == "__main__":
    unittest.main()