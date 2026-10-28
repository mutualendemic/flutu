import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from bson import ObjectId

from app import create_app
from app.chat.sockets import socketio
from app.services.chat import _quantum_option_index, _serialize_member, create_question, delete_conversation, graph_payload, validate_question


class ChatTests(unittest.TestCase):
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
            REDIS_URL = ""
            SOCKETIO_CORS_ORIGINS = ""
            CHAT_REALTIME_MODE = "polling"
            APP_ENV = "test"

        self.app = create_app(TestConfig)
        self.http = self.app.test_client()

    def sign_in(self):
        with self.http.session_transaction() as session:
            session["user"] = {
                "sub": "google-user", "email": "user@example.com", "name": "Test User"
            }

    def csrf_headers(self):
        with self.http.session_transaction() as session:
            session["_csrf_token"] = "test-csrf-token"
        return {"X-CSRF-Token": "test-csrf-token"}

    def test_question_validation_defaults_and_limits(self):
        self.assertEqual(validate_question(" Choose lunch? ", None), ("Choose lunch?", ["Yes", "No"]))
        self.assertEqual(validate_question("Choose?", ["  A ", "b"]), ("Choose?", ["A", "b"]))
        for text, options, expected in (
            ("", ["Yes", "No"], "invalid_text"),
            ("x" * 281, ["Yes", "No"], "invalid_text"),
            ("Question", ["Only one"], "invalid_option_count"),
            ("Question", [str(index) for index in range(11)], "invalid_option_count"),
            ("Question", ["Yes", " yes "], "invalid_option"),
            ("Question", ["", "No"], "invalid_option"),
            ("Question", ["x" * 61, "No"], "invalid_option"),
        ):
            with self.subTest(expected=expected, options=options):
                with self.assertRaisesRegex(ValueError, expected):
                    validate_question(text, options)

    def test_quantum_option_index_can_select_each_position_for_option_counts(self):
        for option_count in range(2, 11):
            bit_count = (option_count - 1).bit_length()
            for expected_index in range(option_count):
                bits = [bool(expected_index & (1 << shift)) for shift in range(bit_count - 1, -1, -1)]
                with self.subTest(option_count=option_count, expected_index=expected_index), patch(
                    "app.services.chat.choose_direction", side_effect=bits
                ) as choose:
                    self.assertEqual(_quantum_option_index(option_count), expected_index)
                    self.assertEqual(choose.call_count, bit_count)

    def test_quantum_option_index_rejects_out_of_range_bit_patterns_without_bias(self):
        # With three choices, bit pattern 11 is rejected; 10 then selects index 2.
        with patch("app.services.chat.choose_direction", side_effect=[True, True, True, False]) as choose:
            self.assertEqual(_quantum_option_index(3), 2)
        self.assertEqual(choose.call_count, 4)

    def test_only_creator_can_create_the_initial_question(self):
        conversation_id = ObjectId("65b0e7a3a6c6f166f1c3a021")
        conversation = {"_id": conversation_id, "created_by_user_id": "owner", "archived_at": None, "deleted_at": None}
        conversations = Mock()
        conversations.find_one.return_value = conversation
        questions = Mock()
        questions.find_one.return_value = None
        questions.insert_one.return_value.inserted_id = ObjectId("65b0e7a3a6c6f166f1c3a022")
        options = Mock()

        with patch("app.services.chat._collections", return_value=(conversations, Mock(), questions, options, Mock())):
            created = create_question(str(conversation_id), "owner", "Pick one", ["A", "B", "C"])

        self.assertEqual(created, "65b0e7a3a6c6f166f1c3a022")
        self.assertEqual([item["label"] for item in options.insert_many.call_args.args[0]], ["A", "B", "C"])
        with patch("app.services.chat._collections", return_value=(conversations, Mock(), questions, options, Mock())):
            with self.assertRaises(PermissionError):
                create_question(str(conversation_id), "participant", "Unauthorized root")

    def test_active_member_can_follow_up_only_on_quantum_selected_option(self):
        conversation_id = ObjectId("65b0e7a3a6c6f166f1c3a031")
        parent_question_id = ObjectId("65b0e7a3a6c6f166f1c3a032")
        selected_option_id = ObjectId("65b0e7a3a6c6f166f1c3a033")
        other_option_id = ObjectId("65b0e7a3a6c6f166f1c3a034")
        parent_question = {"_id": parent_question_id, "conversation_id": conversation_id}
        parent_option = {"_id": selected_option_id, "question_id": parent_question_id}
        conversation = {"_id": conversation_id, "created_by_user_id": "owner", "archived_at": None, "deleted_at": None}
        conversations = Mock()
        conversations.find_one.return_value = conversation
        questions = Mock()
        questions.find_one.return_value = parent_question
        questions.insert_one.return_value.inserted_id = ObjectId("65b0e7a3a6c6f166f1c3a035")
        options = Mock()
        options.find_one.side_effect = lambda query: parent_option if query.get("_id") == selected_option_id else None
        collections = (conversations, Mock(), questions, options, Mock())

        with patch("app.services.chat._collections", return_value=collections), patch(
            "app.services.chat._depth", return_value=1
        ), patch("app.services.chat._quantum_path_for_question", return_value=parent_option):
            created = create_question(str(conversation_id), "participant", "Follow up", parent_option_id=str(selected_option_id))
        self.assertEqual(created, "65b0e7a3a6c6f166f1c3a035")

        other_option = {"_id": other_option_id, "question_id": parent_question_id}
        options.find_one.side_effect = lambda query: other_option if query.get("_id") == other_option_id else None
        with patch("app.services.chat._collections", return_value=collections), patch(
            "app.services.chat._depth", return_value=1
        ), patch("app.services.chat._quantum_path_for_question", return_value=parent_option):
            with self.assertRaisesRegex(ValueError, "quantum_path_locked"):
                create_question(str(conversation_id), "participant", "Wrong branch", parent_option_id=str(other_option_id))

    def test_private_chat_pages_and_apis_require_session(self):
        for path in ("/chat/", "/chat/example"):
            with self.subTest(path=path):
                response = self.http.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/")
        response = self.http.get("/chat/api/conversations")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "Authentication required."})
        response = self.http.post("/chat/api/conversations", json={"title": "Private"})
        self.assertEqual(response.status_code, 401)

    def test_mutating_chat_api_requires_csrf(self):
        self.sign_in()
        response = self.http.post("/chat/api/conversations", json={"title": "No token"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "csrf_failed"})

    def test_conversation_delete_route_requires_authentication_and_csrf(self):
        response = self.http.delete("/chat/api/conversations/conversation-id")
        self.assertEqual(response.status_code, 401)
        self.sign_in()
        response = self.http.delete("/chat/api/conversations/conversation-id")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "csrf_failed"})

    def test_creator_can_delete_conversation_and_notify_all_members(self):
        self.sign_in()
        headers = self.csrf_headers()
        member_ids = ["google-user", "other-user"]
        with patch("app.chat.routes.service.delete_conversation", return_value=member_ids), patch(
            "app.chat.routes.emit_to_user"
        ) as emit:
            response = self.http.delete(
                "/chat/api/conversations/conversation-id", headers=headers
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"deleted": True})
        self.assertEqual(emit.call_count, 2)
        emit.assert_any_call("conversation_removed", {"id": "conversation-id"}, "other-user")

    def test_new_conversation_push_excludes_creator(self):
        self.sign_in()
        conversation = {"title": "Plan", "member_user_ids": ["google-user", "friend"]}
        with patch("app.chat.routes.service.create_conversation", return_value="conversation-id"), patch(
            "app.chat.routes.service.get_conversation", return_value=conversation
        ), patch("app.chat.routes.emit_to_user"), patch("app.chat.routes.notify_users") as notify:
            response = self.http.post(
                "/chat/api/conversations",
                json={"title": "Plan", "member_user_ids": ["friend"]},
                headers=self.csrf_headers(),
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(notify.call_args.args[1], ["google-user", "friend"])
        self.assertEqual(notify.call_args.kwargs["exclude_ids"], {"google-user"})

    def test_adding_members_pushes_only_ids_returned_as_new_members(self):
        self.sign_in()
        added = [{"user_id": "new-friend", "name": "New Friend"}]
        with patch("app.chat.routes.service.add_members", return_value=added), patch(
            "app.chat.routes.service.get_conversation", return_value={"title": "Plan"}
        ), patch("app.chat.routes.emit_to_user"), patch("app.chat.routes.emit_to_active_members"), patch(
            "app.chat.routes.notify_users"
        ) as notify:
            response = self.http.post(
                "/chat/api/conversations/conversation-id/members",
                json={"user_ids": ["new-friend"]},
                headers=self.csrf_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(notify.call_args.args[1], ["new-friend"])

    def test_socket_created_question_pushes_to_other_members(self):
        self.sign_in()
        client = socketio.test_client(self.app, namespace="/chat", flask_test_client=self.http)
        with patch("app.chat.sockets.service.is_active_member", return_value=True), patch(
            "app.chat.sockets.service.create_question", return_value="question-id"
        ), patch("app.chat.sockets.service.question_event_payload", return_value={}), patch(
            "app.chat.sockets.service.get_active_members", return_value=[{"user_id": "google-user"}, {"user_id": "friend"}]
        ), patch("app.chat.sockets.emit_to_active_members"), patch("app.chat.sockets.notify_users") as notify:
            result = client.emit(
                "create_question",
                {"conversation_id": "conversation-id", "text": "A question?", "options": ["A", "B"]},
                namespace="/chat",
                callback=True,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(notify.call_args.args[1], ["google-user", "friend"])
        self.assertEqual(notify.call_args.kwargs["exclude_ids"], {"google-user"})
        client.disconnect(namespace="/chat")

    def test_non_creator_cannot_delete_conversation(self):
        self.sign_in()
        with patch("app.services.chat._collections") as collections_factory:
            conversations = Mock()
            conversations.find_one.return_value = {
                "_id": ObjectId("65b0e7a3a6c6f166f1c3a001"),
                "created_by_user_id": "creator-user",
            }
            collections_factory.return_value = (conversations, Mock(), Mock(), Mock(), Mock())
            with self.assertRaises(PermissionError):
                delete_conversation("65b0e7a3a6c6f166f1c3a001", "google-user")
        conversations.find_one_and_update.assert_not_called()

    def test_polling_conversation_page_exposes_its_transport(self):
        self.sign_in()
        with patch("app.chat.routes.service.is_active_member", return_value=True):
            response = self.http.get("/chat/conversation-id")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-realtime-mode="polling"', response.data)

    def test_conversation_members_control_is_an_accessible_toggle(self):
        self.sign_in()
        with patch("app.chat.routes.service.is_active_member", return_value=True):
            response = self.http.get("/chat/conversation-id")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'role="switch" aria-checked="false" aria-expanded="false" aria-controls="members-panel"', response.data)
        self.assertIn(b'id="question-text"', response.data)
        self.assertIn(b'id="option-editors"', response.data)
        self.assertIn(b'id="send-question"', response.data)
        self.assertIn(b'id="graph-fit"', response.data)
        self.assertIn(b'id="graph-zoom-in"', response.data)
        self.assertIn(b'id="graph-empty-state"', response.data)
        self.assertIn(b'id="graph-empty-state"', response.data)
        self.assertIn(b'src="/static/logo.svg"', response.data)
        script = self.http.get("/static/chat-conversation.js")
        self.assertIn(b'node[type="option"][?quantum_selected]', script.data)
        self.assertIn(b'edge[kind="branch"][?quantum_selected]', script.data)
        self.assertIn(b"input.value = ''; input.placeholder = t(value)", script.data)
        self.assertIn(b"input.reportValidity()", script.data)
        script.close()

    def test_chat_list_uses_member_profile_photos_with_initials_fallback(self):
        self.sign_in()
        response = self.http.get("/chat/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"member-photo", response.data)
        script = self.http.get("/static/chat-list.js")
        self.assertIn(b"member.picture", script.data)
        self.assertIn(b"image.replaceWith(dot)", script.data)
        script.close()

    def test_member_snapshot_preserves_profile_photo_for_author_avatar(self):
        member = _serialize_member({
            "user_id": "google-user",
            "name": "Test User",
            "picture": "https://example.com/avatar.png",
            "left_at": None,
        })
        self.assertEqual(member["picture"], "https://example.com/avatar.png")
        self.assertTrue(member["active"])

    def test_graph_question_node_includes_author_photo_and_name(self):
        conversation_id = ObjectId()
        question_id = ObjectId()
        option_id = ObjectId()
        created_at = datetime.now(timezone.utc)
        conversation = {"_id": conversation_id, "title": "Planning"}
        question = {
            "_id": question_id,
            "conversation_id": conversation_id,
            "author_user_id": "google-user",
            "text": "Where should we meet?",
            "status": "open",
            "parent_option_id": None,
            "winning_option_id": None,
            "created_at": created_at,
        }
        option = {
            "_id": option_id,
            "question_id": question_id,
            "conversation_id": conversation_id,
            "label": "Park",
            "position": 0,
        }
        members = Mock()
        members.find.return_value = [{
            "user_id": "google-user",
            "name": "Test User",
            "picture": "https://example.com/avatar.png",
            "left_at": None,
        }]
        questions = Mock()
        questions.find.return_value.sort.return_value = [question]
        options = Mock()
        options.find.return_value.sort.return_value = [option]
        answers = Mock()
        answers.find.return_value = []

        with patch("app.services.chat.get_conversation", return_value=conversation), patch(
            "app.services.chat._collections", return_value=(Mock(), members, questions, options, answers)
        ):
            graph = graph_payload(str(conversation_id), "google-user")

        question_node = next(node for node in graph["nodes"] if node["type"] == "question")
        self.assertEqual(question_node["author_name"], "Test User")
        self.assertEqual(question_node["author_picture"], "https://example.com/avatar.png")

    def test_chat_list_displays_private_channel_authorization_check(self):
        self.sign_in()
        response = self.http.get("/chat/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="realtime-status"', response.data)
        self.assertIn(b"Checking Supabase private-channel authorization", response.data)
        script = self.http.get("/static/chat-list.js")
        self.assertIn(b"conversation-delete", script.data)
        script.close()

    def test_realtime_token_requires_authentication_and_supabase_config(self):
        response = self.http.get("/chat/api/realtime-token")
        self.assertEqual(response.status_code, 401)

        self.sign_in()
        response = self.http.get("/chat/api/realtime-token")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"error": "realtime_not_configured"})

    def test_production_supabase_mode_does_not_require_redis(self):
        class VercelProductionConfig:
            SECRET_KEY = "test-secret"
            TESTING = True
            APP_ENV = "production"
            CHAT_REALTIME_MODE = "supabase"
            REDIS_URL = ""
            SOCKETIO_REQUIRE_REDIS = True
            SOCKETIO_CORS_ORIGINS = ""

        app = create_app(VercelProductionConfig)
        self.assertEqual(app.extensions["socketio"].server.eio.async_mode, "threading")

    def test_supabase_token_endpoint_scopes_topics_to_active_membership(self):
        self.sign_in()
        self.app.config.update(
            SUPABASE_URL="https://project.supabase.co",
            SUPABASE_ANON_KEY="public-anon-key",
            SUPABASE_SERVICE_ROLE_KEY="server-only-key",
            SUPABASE_JWT_SECRET="jwt-secret",
        )
        with patch("app.chat.routes.service.is_active_member", return_value=True):
            response = self.http.get("/chat/api/realtime-token?conversation_id=65b0e7a3a6c6f166f1c3a001")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["url"], "https://project.supabase.co")
        self.assertEqual(body["anon_key"], "public-anon-key")
        self.assertNotIn("server-only-key", response.get_data(as_text=True))
        self.assertEqual(
            body["conversation_topics"],
            {"65b0e7a3a6c6f166f1c3a001": "chat-conversation:65b0e7a3a6c6f166f1c3a001"},
        )

        with patch("app.chat.routes.service.is_active_member", return_value=False):
            denied = self.http.get("/chat/api/realtime-token?conversation_id=65b0e7a3a6c6f166f1c3a001")
        self.assertEqual(denied.status_code, 403)

    def test_rest_question_creation_is_authenticated_and_csrf_protected(self):
        self.sign_in()
        headers = self.csrf_headers()
        with patch("app.chat.routes.service.is_active_member", return_value=True), patch(
            "app.chat.routes.service.create_question", return_value="q1"
        ) as create, patch("app.chat.routes.service.question_event_payload", return_value={"question": {}, "options": [], "edges": []}), patch(
            "app.chat.routes.emit_to_active_members"
        ), patch("app.chat.routes.service.get_active_members", return_value=[{"user_id": "google-user"}, {"user_id": "friend"}]), patch(
            "app.chat.routes.notify_users"
        ) as notify:
            response = self.http.post(
                "/chat/api/conversations/conversation-id/questions",
                json={"text": "A question?", "options": ["One", "Two", "Three"]}, headers=headers,
            )
        self.assertEqual(response.status_code, 201)
        create.assert_called_once_with("conversation-id", "google-user", "A question?", ["One", "Two", "Three"], None, True)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1], ["google-user", "friend"])
        self.assertEqual(notify.call_args.kwargs["exclude_ids"], {"google-user"})

    def test_non_creator_cannot_create_initial_question(self):
        self.sign_in()
        headers = self.csrf_headers()
        with patch("app.chat.routes.service.is_active_member", return_value=True), patch(
            "app.chat.routes.service.create_question", side_effect=PermissionError("forbidden")
        ):
            response = self.http.post(
                "/chat/api/conversations/conversation-id/questions",
                json={"text": "What next?"},
                headers=headers,
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "forbidden"})

    def test_graph_payload_marks_quantum_random_branch_selection(self):
        conversation_id = ObjectId("65b0e7a3a6c6f166f1c3a001")
        question_id = ObjectId("65b0e7a3a6c6f166f1c3a002")
        option_id_a = ObjectId("65b0e7a3a6c6f166f1c3a003")
        option_id_b = ObjectId("65b0e7a3a6c6f166f1c3a004")
        conversation = {"_id": conversation_id, "title": "Quantum decision", "created_by_user_id": "google-user"}
        question = {
            "_id": question_id,
            "conversation_id": conversation_id,
            "author_user_id": "google-user",
            "text": "Choose a door",
            "status": "open",
            "parent_option_id": None,
            "winning_option_id": None,
            "created_at": datetime.now(timezone.utc),
        }
        options = [
            {"_id": option_id_a, "question_id": question_id, "conversation_id": conversation_id, "label": "Left", "position": 0},
            {"_id": option_id_b, "question_id": question_id, "conversation_id": conversation_id, "label": "Right", "position": 1},
        ]
        members = [{"user_id": "google-user", "name": "Test User", "picture": "https://example.com/a.png", "left_at": None}]

        members_collection = Mock()
        members_collection.find.return_value = members
        questions_collection = Mock()
        questions_collection.find.return_value.sort.return_value = [question]
        questions_collection.find_one.return_value = question
        questions_collection.update_one.side_effect = lambda _query, update: question.update(update.get("$set", {}))
        options_collection = Mock()
        options_collection.find.return_value.sort.return_value = options
        answers_collection = Mock()
        answers_collection.find.return_value = []

        with patch("app.services.chat.get_conversation", return_value=conversation), patch(
            "app.services.chat._collections",
            return_value=(Mock(), members_collection, questions_collection, options_collection, answers_collection),
        ), patch("app.services.chat.choose_direction", return_value=True):
            graph = graph_payload(str(conversation_id), "google-user")

        self.assertEqual(graph["branch_mode"], "quantum_random")
        self.assertFalse(graph["can_create_initial_question"])
        self.assertTrue(graph["can_manage_members"])
        question_node = next(node for node in graph["nodes"] if node["type"] == "question")
        self.assertEqual(question_node["lane"], 0)
        option_nodes = [node for node in graph["nodes"] if node["type"] == "option"]
        self.assertEqual({node["lane"] for node in option_nodes}, {1})
        self.assertEqual(len({node["row"] for node in option_nodes}), 2)
        self.assertEqual([node["option_id"] for node in option_nodes], [str(option_id_a), str(option_id_b)])
        self.assertLess(option_nodes[0]["row"], option_nodes[1]["row"])
        self.assertTrue(all("count" not in node and "voter_names" not in node for node in option_nodes))
        selected = next(node for node in option_nodes if node["option_id"] == str(option_id_b))
        self.assertTrue(selected["quantum_selected"])
        selected_edge = next(edge for edge in graph["edges"] if edge["to"] == selected["id"])
        self.assertTrue(selected_edge["quantum_selected"])

    def test_graph_does_not_mark_first_option_when_no_quantum_selection_exists(self):
        conversation_id = ObjectId("65b0e7a3a6c6f166f1c3a051")
        question_id = ObjectId("65b0e7a3a6c6f166f1c3a052")
        option_ids = [ObjectId("65b0e7a3a6c6f166f1c3a053"), ObjectId("65b0e7a3a6c6f166f1c3a054")]
        conversation = {"_id": conversation_id, "title": "Selection unavailable", "created_by_user_id": "owner"}
        question = {
            "_id": question_id, "conversation_id": conversation_id, "author_user_id": "owner",
            "text": "Choose", "status": "open", "parent_option_id": None,
            "winning_option_id": None, "created_at": datetime.now(timezone.utc),
        }
        option_docs = [
            {"_id": option_id, "question_id": question_id, "conversation_id": conversation_id, "label": str(index), "position": index}
            for index, option_id in enumerate(option_ids)
        ]
        members = Mock()
        members.find.return_value = []
        questions = Mock()
        questions.find.return_value.sort.return_value = [question]
        options = Mock()
        options.find.return_value.sort.return_value = option_docs
        options.find_one.return_value = None

        with patch("app.services.chat.get_conversation", return_value=conversation), patch(
            "app.services.chat._collections", return_value=(Mock(), members, questions, options, Mock())
        ), patch("app.services.chat._depth", return_value=0), patch(
            "app.services.chat._quantum_path_for_question", return_value=None
        ):
            graph = graph_payload(str(conversation_id), "owner")

        question_node = next(node for node in graph["nodes"] if node["type"] == "question")
        option_nodes = [node for node in graph["nodes"] if node["type"] == "option"]
        self.assertIsNone(question_node["quantum_selected_option_id"])
        self.assertEqual([node["quantum_selected"] for node in option_nodes], [False, False])

    def test_graph_payload_keeps_quantum_branch_selection_stable(self):
        conversation_id = ObjectId("65b0e7a3a6c6f166f1c3a011")
        question_id = ObjectId("65b0e7a3a6c6f166f1c3a012")
        option_ids = [ObjectId("65b0e7a3a6c6f166f1c3a013"), ObjectId("65b0e7a3a6c6f166f1c3a014")]
        conversation = {"_id": conversation_id, "title": "Quantum decision"}
        question = {
            "_id": question_id,
            "conversation_id": conversation_id,
            "author_user_id": "google-user",
            "text": "Choose a direction",
            "status": "open",
            "parent_option_id": None,
            "winning_option_id": None,
            "created_at": datetime.now(timezone.utc),
        }
        options = [
            {"_id": option_id, "question_id": question_id, "conversation_id": conversation_id, "label": label, "position": index}
            for index, (option_id, label) in enumerate(zip(option_ids, ("Left", "Right")))
        ]
        members = Mock()
        members.find.return_value = []
        questions = Mock()
        questions.find.return_value.sort.return_value = [question]
        questions.find_one.return_value = question
        questions.update_one.side_effect = lambda _query, update: question.update(update.get("$set", {}))
        option_collection = Mock()
        option_collection.find.return_value.sort.return_value = options
        answers = Mock()
        answers.find.return_value = []

        with patch("app.services.chat.get_conversation", return_value=conversation), patch(
            "app.services.chat._collections",
            return_value=(Mock(), members, questions, option_collection, answers),
        ), patch("app.services.chat.choose_direction", side_effect=[True, False]) as choose:
            first = graph_payload(str(conversation_id), "google-user")
            second = graph_payload(str(conversation_id), "google-user")

        first_selected = next(node["option_id"] for node in first["nodes"] if node["type"] == "option" and node["quantum_selected"])
        second_selected = next(node["option_id"] for node in second["nodes"] if node["type"] == "option" and node["quantum_selected"])
        self.assertEqual(first_selected, str(option_ids[1]))
        self.assertEqual(second_selected, first_selected)
        choose.assert_called_once()

    def test_graph_places_followup_question_after_selected_option_column(self):
        conversation_id = ObjectId("65b0e7a3a6c6f166f1c3a041")
        root_id = ObjectId("65b0e7a3a6c6f166f1c3a042")
        child_id = ObjectId("65b0e7a3a6c6f166f1c3a043")
        selected_id = ObjectId("65b0e7a3a6c6f166f1c3a044")
        other_id = ObjectId("65b0e7a3a6c6f166f1c3a045")
        child_option_id = ObjectId("65b0e7a3a6c6f166f1c3a046")
        child_other_id = ObjectId("65b0e7a3a6c6f166f1c3a047")
        root = {
            "_id": root_id, "conversation_id": conversation_id, "author_user_id": "owner",
            "text": "First question", "status": "open", "parent_option_id": None,
            "created_at": datetime.now(timezone.utc),
        }
        child = {
            "_id": child_id, "conversation_id": conversation_id, "author_user_id": "participant",
            "text": "Follow-up question", "status": "open", "parent_option_id": selected_id,
            "created_at": datetime.now(timezone.utc),
        }
        options = [
            {"_id": selected_id, "question_id": root_id, "conversation_id": conversation_id, "label": "Chosen", "position": 0},
            {"_id": other_id, "question_id": root_id, "conversation_id": conversation_id, "label": "Other", "position": 1},
            {"_id": child_option_id, "question_id": child_id, "conversation_id": conversation_id, "label": "Next A", "position": 0},
            {"_id": child_other_id, "question_id": child_id, "conversation_id": conversation_id, "label": "Next B", "position": 1},
        ]
        members = Mock()
        members.find.return_value = [
            {"user_id": "owner", "name": "Owner", "left_at": None},
            {"user_id": "participant", "name": "Participant", "left_at": None},
        ]
        questions = Mock()
        questions.find.return_value.sort.return_value = [root, child]
        option_collection = Mock()
        option_collection.find.return_value.sort.return_value = options
        option_collection.find_one.return_value = options[0]
        with patch("app.services.chat.get_conversation", return_value={"_id": conversation_id, "title": "Flow", "created_by_user_id": "owner"}), patch(
            "app.services.chat._collections", return_value=(Mock(), members, questions, option_collection, Mock())
        ), patch("app.services.chat._depth", side_effect=lambda question, *_args: 0 if question["_id"] == root_id else 1), patch(
            "app.services.chat._quantum_path_for_question", side_effect=lambda qid: options[0] if qid == root_id else options[2]
        ):
            graph = graph_payload(str(conversation_id), "participant")

        root_node = next(node for node in graph["nodes"] if node["id"] == f"q{root_id}")
        child_node = next(node for node in graph["nodes"] if node["id"] == f"q{child_id}")
        option_node = next(node for node in graph["nodes"] if node["id"] == f"o{selected_id}")
        self.assertEqual((root_node["lane"], option_node["lane"], child_node["lane"]), (0, 1, 2))
        self.assertTrue(any(edge["from"] == option_node["id"] and edge["to"] == child_node["id"] and edge["kind"] == "follow_up" for edge in graph["edges"]))

    def test_rest_answer_and_close_actions_are_disabled_in_quantum_mode(self):
        self.sign_in()
        headers = self.csrf_headers()
        question = {"conversation_id": "conversation-id"}
        with patch("app.chat.routes.service.question_by_id", return_value=question), patch(
            "app.chat.routes.service.is_active_member", return_value=True
        ), patch("app.chat.routes.service.submit_answer") as submit:
            response = self.http.post(
                "/chat/api/questions/question-id/answers",
                json={"option_id": "option-id"}, headers=headers,
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "branch_mode_locked"})
        submit.assert_not_called()

        with patch("app.chat.routes.service.question_by_id", return_value=question), patch(
            "app.chat.routes.service.is_active_member", return_value=True
        ), patch("app.chat.routes.service.close_question") as close:
            response = self.http.post(
                "/chat/api/questions/question-id/close", json={}, headers=headers,
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "branch_mode_locked"})
        close.assert_not_called()

    def test_socket_rejects_unauthenticated_connection(self):
        client = socketio.test_client(self.app, namespace="/chat", flask_test_client=self.http)
        self.assertFalse(client.is_connected("/chat"))

    def test_socket_requires_active_membership_and_returns_ack(self):
        self.sign_in()
        client = socketio.test_client(self.app, namespace="/chat", flask_test_client=self.http)
        self.assertTrue(client.is_connected("/chat"))
        with patch("app.chat.sockets.service.is_active_member", return_value=False):
            denied = client.emit("join", {"conversation_id": "conversation-id"}, namespace="/chat", callback=True)
        self.assertEqual(denied, {"ok": False, "error": "forbidden"})
        with patch("app.chat.sockets.service.is_active_member", return_value=True), patch(
            "app.chat.sockets.service.graph_payload", return_value={"conversation_id": "conversation-id", "nodes": [], "edges": []}
        ):
            allowed = client.emit("join", {"conversation_id": "conversation-id"}, namespace="/chat", callback=True)
        self.assertEqual(allowed["ok"], True)
        self.assertEqual(allowed["graph"]["conversation_id"], "conversation-id")
        client.disconnect(namespace="/chat")

    def test_socket_question_creation_broadcasts_after_service_write(self):
        self.sign_in()
        client = socketio.test_client(self.app, namespace="/chat", flask_test_client=self.http)
        with patch("app.chat.sockets.service.is_active_member", return_value=True), patch(
            "app.chat.sockets.service.create_question", return_value="q1"
        ) as create, patch("app.chat.sockets.service.question_event_payload", return_value={"question": {}, "options": [], "edges": []}), patch(
            "app.chat.sockets.emit_to_active_members"
        ) as emit, patch("app.chat.sockets.service.get_active_members", return_value=[{"user_id": "google-user"}]), patch(
            "app.chat.sockets.notify_users"
        ):
            result = client.emit(
                "create_question",
                {"conversation_id": "conversation-id", "text": "A question?", "options": ["Yes", "No"]},
                namespace="/chat",
                callback=True,
            )
        self.assertEqual(result, {"ok": True, "question_id": "q1"})
        create.assert_called_once()
        emit.assert_called_once()
        client.disconnect(namespace="/chat")

    def test_socket_limits_events_to_twenty_per_ten_seconds(self):
        self.sign_in()
        client = socketio.test_client(self.app, namespace="/chat", flask_test_client=self.http)
        with patch("app.chat.sockets.service.is_active_member", return_value=True), patch(
            "app.chat.sockets.service.graph_payload", return_value={"nodes": [], "edges": []}
        ):
            results = [
                client.emit("join", {"conversation_id": "conversation-id"}, namespace="/chat", callback=True)
                for _ in range(21)
            ]
        self.assertTrue(all(result["ok"] for result in results[:19]))
        self.assertEqual(results[20], {"ok": False, "error": "rate_limited"})
        client.disconnect(namespace="/chat")


if __name__ == "__main__":
    unittest.main()
