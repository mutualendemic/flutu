# Spec: Branching group chat with live question graph

Target: existing Python / Flask app that already has Contacts.
Audience: code agent. Read the whole file before writing code, and inspect the existing codebase first (see section 2).

## 1. Goal

Add a chat feature where a user can create multiple conversations, add other participants from their Contacts, and run the conversation as a series of questions. Every question opens a visible branch in a live graph. Participants answer by selecting exactly one option. The graph updates in real time for everyone as people interact.

### Core behavior

- A user creates a conversation and adds participants (picked from Contacts).
- Any member can create a question. The question has free text and a list of options.
- The default options are `Yes` and `No`. The creator can edit the list, add more options, or remove options (minimum 2, maximum 10).
- Every other member picks exactly one option. Picking again changes the vote while the question is open.
- Each question opens a branch in the graph. Options sit on the branch, with a vote count and colored voter dots. When the question is closed, the branch merges back and the winning option is highlighted.
- A member can create a follow-up question attached to an option. This opens a nested sub-branch.
- Everything updates live in all connected clients without a page reload.

### Out of scope for v1

- Free-text chat messages (keep the model extensible; see open questions).
- File or image attachments.
- Inviting people who have no user account.
- Push notifications and email.

## 2. First step: inspect the existing app

Before coding, find and report (in a short note at the top of your PR) the following. Do not assume.

1. How users and authentication work (Flask-Login? sessions? JWT?). Reuse it. Do not add a second auth system.
2. The existing `Contact` model and how a contact maps to a user account (if at all).
3. The database in use, ORM (Flask-SQLAlchemy?), migration tool (Flask-Migrate / Alembic?), and the app factory / blueprint layout.
4. How the front end is built (Jinja templates, htmx, a JS framework). Match it. Section 7 assumes Jinja templates plus vanilla JS; adapt if different.
5. How the app is deployed today (gunicorn? uwsgi? Docker?) because WebSockets change the server requirements (section 8).

## 3. Technology choices

| Concern | Choice | Why |
|---|---|---|
| Real-time transport | Flask-SocketIO (Socket.IO) | Bidirectional events, rooms (one per conversation), acknowledgements, namespaces, Flask-Login integration, Redis queue for scaling. SSE is server-to-client only, so every client action would need a separate HTTP call. |
| Persistence | Flask-SQLAlchemy + Flask-Migrate | Standard stack. Reuse if already present. |
| Auth in sockets | Flask-Login (reuse) | Flask-SocketIO can read the Flask-Login session on connect. Authenticate before the socket connects. |
| Async worker (production) | gevent (with gevent-websocket) | Flask-SocketIO supports eventlet and gevent. gevent is the safer choice because eventlet is no longer actively maintained. |
| Multi-process scaling | Redis message queue | Required to share broadcasts and rooms across workers or instances. |
| Graph rendering (browser) | Cytoscape.js 3.x, pinned, vendored under `static/vendor/` | Built for graph-centric views, with pan, zoom, tap events, and incremental add or update of nodes. We use the `preset` layout and compute positions ourselves (section 6), so no layout plugin is needed. |
| Front-end realtime client | Official `socket.io` JS client, version matched to the installed python-socketio / Flask-SocketIO compatibility table | Version mismatches break the handshake. |

Considered and rejected:

- React Flow: a good fit for editable node-based editors, but it assumes a React front end. Only adopt it if the app is already React.
- dagre or elkjs auto-layout: made for general trees and DAGs. Our git-style lane layout is deterministic and simple, so we compute it directly and keep the graph stable between updates.
- Server-Sent Events: one-way only.

## 4. Data model

Use the app's existing conventions for ids, timestamps, and naming. Names below are logical.

```
Conversation
  id, title, created_by_user_id, created_at, archived_at (nullable)

ConversationMember
  id, conversation_id, user_id, role ('owner' | 'member'),
  color (hex, assigned at join from a fixed palette, unique per conversation),
  joined_at, left_at (nullable)
  unique (conversation_id, user_id)

Question
  id, conversation_id, author_user_id, text (max 280),
  parent_option_id (nullable FK -> Option; null = main thread),
  status ('open' | 'closed'), allow_vote_change (bool, default true),
  winning_option_id (nullable), created_at, closed_at (nullable)

Option
  id, question_id, label (max 60), position (int), created_at
  unique (question_id, label)

Answer
  id, question_id, option_id, user_id, answered_at, updated_at
  unique (question_id, user_id)        # enforces exactly one choice per member
```

Rules enforced on the server (never trust the client):

- Creating a question without options creates `Yes` and `No`.
- 2 to 10 options. Labels trimmed, non-empty, unique within the question (case-insensitive).
- Only active members (not left) can create questions, answer, or read the conversation.
- An answer's option must belong to the answered question.
- Answering a closed question is rejected. Changing a vote is rejected if `allow_vote_change` is false.
- A question closes when the owner or the question author closes it, or automatically when every active member has answered.
- Winning option: the one with the most answers. On a tie, `winning_option_id` stays null and the graph shows the tied options highlighted equally. The author can pick the winner when closing (optional `winning_option_id` in the close call, which must be one of the tied options).
- A follow-up question (`parent_option_id` set) must reference an option in the same conversation. Maximum nesting depth: 3.
- The author may edit or delete a question only while it has zero answers.

## 5. Contacts integration

- A conversation member is always a `User`. The member picker lists the current user's Contacts.
- If a contact is linked to a user account, it can be added. If not, show it disabled with the label "Not on the app" (invites are out of scope for v1).
- Owner can add and remove members. A member can leave. Removing or leaving keeps their past answers and shows them as a gray "former member" dot.
- The creator is the first member with role `owner`.
- Adding a member emits a live event so their conversation list and any open graph update immediately.

## 6. Graph model and layout

The server sends the graph as data. The client lays it out with this deterministic algorithm so the picture is stable and identical for everyone.

### Node and edge payload

```json
{
  "conversation_id": 12,
  "members": [{"user_id": 3, "name": "Ana", "color": "#7F77DD", "active": true}],
  "nodes": [
    {"id": "q5", "type": "question", "label": "Lunch today?", "status": "open",
     "author_user_id": 3, "lane": 0, "row": 0, "winning_option_id": null},
    {"id": "o9", "type": "option", "label": "Yes", "question_id": 5,
     "lane": 1, "row": 1, "count": 2, "voter_user_ids": [3, 4], "is_winner": false}
  ],
  "edges": [
    {"from": "q5", "to": "o9", "kind": "branch"},
    {"from": "o9", "to": "q7", "kind": "follow_up"},
    {"from": "q5", "to": "q8", "kind": "merge"}
  ]
}
```

### Layout algorithm (implemented on the client; port to Python only for tests)

1. Order all questions by `created_at`. Each question gets the next free `row`. Its options take the following rows, one per option, stacked vertically.
2. `lane` of a main-thread question is 0. The options of a question are drawn on `lane = question.lane + 1` (the branch).
3. A follow-up question hangs from its parent option and takes that option's lane, so its own options go one lane further right.
4. When a question is closed, add a merge edge from its last option node back to the next question on the parent lane (or to a small end marker if there is none).
5. Positions: `x = laneX0 + lane * 130`, `y = rowY0 + row * 56`. Mobile width is about 380 px, so depth 3 is the maximum.
6. Render with Cytoscape `layout: { name: 'preset' }`. Style tokens:
   - Main thread: gray 2 px line.
   - Branch edges: amber 2 px, elbow-shaped (`curve-style: taxi`).
   - Question nodes: ring in amber while open, solid when closed.
   - Option nodes: label plus count badge; winner gets a green outline.
   - Voter dots: one small circle per voter in the member's color, with initials or name in the tooltip. Do not rely on color alone: every option shows its voter names in the details panel (accessibility).
7. On each live event, update the changed elements in place (add or update node data) and animate position changes for about 250 ms. Never re-create the whole graph.
8. Pan and zoom enabled. Tapping an option opens the answer sheet. Tapping a question shows author, time, status, and a "Follow up" action.

## 7. Backend API

All routes require an authenticated user. Mutating REST routes need CSRF protection (reuse the app's existing mechanism, e.g. Flask-WTF). Put everything in a new blueprint `chat`.

REST (for loading and management):

| Method | Path | Purpose |
|---|---|---|
| GET | `/chat/api/conversations` | List the current user's conversations (title, last activity, unanswered question count). |
| POST | `/chat/api/conversations` | Create. Body: `title`, `member_user_ids` (optional). |
| GET | `/chat/api/conversations/<id>` | Full graph payload (section 6). Must be a member. |
| POST | `/chat/api/conversations/<id>/members` | Add members (owner only). Body: `user_ids`. |
| DELETE | `/chat/api/conversations/<id>/members/<user_id>` | Remove member (owner) or leave (self). |
| GET | `/chat/api/contacts/addable?conversation_id=` | Contacts that can be added (linked users not already members). |
| GET | `/chat/` and `/chat/<id>` | HTML pages (list and conversation view). |

Socket.IO (namespace `/chat`; one room per conversation named `conv:<id>`):

Client to server (each must use an acknowledgement callback returning `{ok: true, ...}` or `{ok: false, error: "code"}`):

| Event | Payload |
|---|---|
| `join` | `{conversation_id}` (verify membership, then `join_room`, reply with the graph snapshot) |
| `leave` | `{conversation_id}` |
| `create_question` | `{conversation_id, text, options?: string[], parent_option_id?: int, allow_vote_change?: bool}` |
| `submit_answer` | `{question_id, option_id}` |
| `close_question` | `{question_id, winning_option_id?}` |

Server to client (broadcast to the room):

| Event | Payload |
|---|---|
| `question_created` | question node, its option nodes, new edges |
| `answer_recorded` | `{question_id, option_id, previous_option_id, user_id, counts: {option_id: n}}` |
| `question_closed` | `{question_id, winning_option_id, merge_edges}` |
| `member_added` / `member_removed` | member object |

Per-user events (room `user:<id>`, joined on connect): `conversation_added`, `conversation_removed`.

Requirements:

- Reject the connection if the user is not authenticated.
- Check membership on every event, not only on `join`. Flask `before_request` hooks do not run for Socket.IO handlers, so put authorization in a decorator used by every handler.
- Validate payloads: types, lengths (question 280, option 60), option count, and ownership of ids.
- Rate limit: at most 20 events per 10 seconds per connection; reject extra events with `error: "rate_limited"`.
- Restrict `cors_allowed_origins` to the app's own origins.
- Write to the database first, then emit. Emit only after commit succeeds.
- Make `submit_answer` idempotent: the same user choosing the same option again returns ok without a broadcast.
- Escape all user text on render (use `textContent`, never `innerHTML`).

## 8. Deployment changes

- Dev: `socketio.run(app)`. Do not use plain `flask run` for the realtime path because the Werkzeug server lacks WebSocket support.
- Production: Gunicorn with the gevent worker, one worker per process: `gunicorn -k gevent -w 1 -b 0.0.0.0:8000 "yourapp:app"`. Install `gevent` and `gevent-websocket`.
- If gevent or eventlet is used, monkey patch at the very top of the entry module, before other imports.
- Redis: configure `SocketIO(app, message_queue=REDIS_URL, async_mode="gevent")` so rooms and broadcasts work across processes. Scale out by running more single-worker processes behind a load balancer with sticky sessions.
- If the app currently runs behind Nginx or another proxy, add WebSocket upgrade headers for `/socket.io/`.
- Add `REDIS_URL` and `SOCKETIO_CORS_ORIGINS` to config and to the deployment docs. Fail fast with a clear message if Redis is not reachable in production mode.

## 9. Front end

- Conversation list page: cards with title, member avatars, unanswered count, a "New conversation" button.
- New conversation: title field plus a Contacts picker with search.
- Conversation page: the graph fills the main area. Below it, a composer to create a question: text field, options list that starts with Yes and No, "Add option" button, remove buttons, and a Send button.
- Answer sheet: tapping an option on an open question shows a bottom sheet with the question text, the radio options (exactly one), and a Submit button. Show the current vote if the user already answered.
- A members drawer to add or remove people.
- The page must work on a phone-width screen first (about 380 px). The graph supports pan and pinch zoom.
- Connection status indicator and automatic resync: on reconnect, emit `join` again and replace local state with the returned snapshot.
- Use the app's existing styles and components. Sentence case for all labels.

## 10. Implementation order

1. Inspect the app (section 2) and write the findings note.
2. Models and migration (section 4). Unit tests for the validation rules.
3. REST API and the conversation list, create, and member management UI.
4. Socket.IO setup with auth, rooms, and the event handlers, using `SocketIOTestClient` for tests.
5. Graph payload builder and the layout function, with tests on fixed fixtures.
6. Front-end graph rendering with Cytoscape, then live updates, then the answer sheet and composer.
7. Production config, Redis, proxy notes, docs.

## 11. Acceptance criteria

1. A user can create a conversation and add at least two contacts who have accounts. Contacts without accounts are shown disabled.
2. Any member can create a question. With no options given, it shows `Yes` and `No`. Adding and removing options works within the 2 to 10 limit.
3. A second logged-in browser sees the new question and branch appear without reloading.
4. Each member can select exactly one option. Selecting another option moves their vote. The database never holds two answers from the same user on one question (the unique constraint holds under concurrent requests).
5. Vote counts and voter dots update live for all members.
6. Closing a question (manually or when everyone has answered) merges the branch and highlights the winner; ties are shown as tied.
7. A follow-up on an option creates a nested branch, up to depth 3. Deeper attempts return a clear error.
8. A non-member cannot read a conversation, join its room, or send events to it, via REST or Socket.IO.
9. Removed or left members stop receiving events immediately and appear as former members in history.
10. Reloading the page restores the identical graph from the snapshot.
11. The layout is identical across clients for the same data.
12. Works on a 380 px wide screen. Option and voter information is also available as text, not only color.
13. Two app processes behind Redis deliver events across processes (integration test or documented manual check).

## 12. Tests required

- Model and validation tests (defaults, option limits, uniqueness, depth limit, closed-question rules).
- Authorization tests for every REST route and every socket event (member, non-member, former member).
- Socket tests with two test clients verifying broadcast, ack format, idempotent answers, and rate limiting.
- Layout unit tests with fixtures: single question, three options, a follow-up chain at depth 3, a closed question with a tie.
- A smoke test that the page loads and the graph renders (headless browser if the project already uses one).

## 13. Assumptions and open questions for the product owner

If an answer is not available, implement the assumption and leave a clearly marked TODO.

1. Assumption: any member can create questions. (Alternative: owner only.)
2. Assumption: the vote is not anonymous; everyone sees who picked what.
3. Assumption: v1 has no free-text messages. The model should allow adding a `Comment` node later without schema changes to the questions.
4. Assumption: contacts without accounts cannot be added. An invite flow is a later feature.
5. Assumption: a closed question cannot be reopened.
6. Question: should answering also be possible for the question's author? Assumed yes.
7. Question: retention and deletion rules for conversations.

## Sources used for the technology choices

- Flask-SocketIO deployment guide: https://flask-socketio.readthedocs.io/en/latest/deployment.html
- Flask-SocketIO implementation notes (authentication, context globals): https://flask-socketio.readthedocs.io/en/stable/_sources/implementation_notes.rst.txt
- Flask-SocketIO getting started (rooms, namespaces, acknowledgements): https://github.com/miguelgrinberg/Flask-SocketIO/blob/732d223b053ac66b1be7a41abf9824c7e1e895ff/docs/getting_started.rst
- React Flow layouting guide (dagre, elkjs, force): https://reactflow.dev/learn/layouting/layouting
- React Flow vs Cytoscape comparison: https://radar.firstaimovers.com/react-flow-vs-cytoscape-graph-engine-choice
- Scaling Flask-SocketIO with Redis: https://oneuptime.com/blog/post/2026-03-31-redis-flask-websocket-server-with-redis-pubsub/markdown
