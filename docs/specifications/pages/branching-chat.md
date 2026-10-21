# Branching chat

## Findings before implementation

- Authentication is the existing Google OAuth flow. The signed Flask session identifies users by Google's stable `sub`; no second auth system was added.
- Contacts are MongoDB documents owned by the session user's `sub`. A contact is linked to a Flutu account by normalized email against the `users` collection; unlinked contacts are displayed disabled.
- The application uses MongoDB and PyMongo, not SQLAlchemy or a migration framework. Chat data is stored in dedicated MongoDB collections with unique indexes for members, option labels/positions, and one answer per question and user.
- The project uses a Flask factory, Blueprints, Jinja templates, and vanilla JavaScript.
- Development runs through Flask-SocketIO/gevent. The Docker production entry uses Gunicorn's gevent worker and requires Redis for push-based chat delivery. Vercel's serverless WSGI adapter does not provide persistent Socket.IO connections; Vercel deployments instead use authenticated REST actions and periodic graph polling.

## Pages and access

- `/chat/` is a level-2 authenticated page linked from the dashboard; it returns to `/dashboard`.
- `/chat/<conversation_id>` is a child of the conversation list and returns to `/chat/`. It is only rendered for active members.
- `/chat/api/*` is protected on the server. Unauthenticated requests return JSON 401; mutating REST requests require the session CSRF token in `X-CSRF-Token` and a same-origin request.
- REST APIs support listing and creating conversations, graph snapshots, member add/remove, addable contacts, question creation, voting, closing, and editing/deleting unanswered questions. All mutating routes require CSRF validation.

## Persistence and rules

Chat documents use `chat_conversations`, `chat_members`, `chat_questions`, `chat_options`, and `chat_answers`. Google `sub` values are user IDs. Former members remain in `chat_members` and their answers remain visible in graph history. Active member IDs are also maintained on conversation documents for listing.

Question text is limited to 280 characters. Option labels are trimmed, case-insensitively unique, and limited to 2–10 options of at most 60 characters. Missing options default to Yes and No. Follow-up depth is limited to three nested levels. Answers use a unique `(question_id, user_id)` index and are idempotent when the same choice is repeated. Closed questions reject answers; a question closes when an owner/author closes it or every active member has answered. A tie has no winner unless the closer selects one of the tied options. Authors can edit/delete only questions with no answers.

MongoDB writes use unique indexes and atomic upserts for answers. There is no cross-document transaction requirement or SQL migration. Operations are written before events are emitted.

## Live graph and client

- Socket.IO uses namespace `/chat`; authenticated connections join a per-user room. Every event rechecks current conversation membership. Events are rate-limited to 20 per connection in 10 seconds.
- Events are fanned out to the active members' per-user rooms, so removed members stop receiving events immediately even if a stale conversation room membership remains.
- The browser receives full snapshots on initial load/reconnect and updates Cytoscape elements in place for live changes. The graph uses deterministic lane/row positions and a preset layout; questions, options, voter names, counts, outcomes, and former members are also exposed as accessible text.
- Vercel mode uses REST for question creation, votes, and closing, and polls the graph every 3 seconds and the conversation list every 5 seconds. This provides near-real-time updates without a persistent connection; push delivery requires a Socket.IO-capable host.
- User text is assigned through DOM text nodes and Cytoscape labels; the client does not use `innerHTML`.
- Cytoscape.js 3.30.4 and Socket.IO client 4.8.1 are pinned CDN assets. They are not vendored in this release; deployments need network access to jsDelivr.

## Deployment

Socket.IO production requires `APP_ENV=production`, `REDIS_URL`, and the gevent Gunicorn worker. Set `SOCKETIO_CORS_ORIGINS` only to comma-separated origins that serve this app; unset means same-origin only. Each Gunicorn process must use one worker; scale with multiple single-worker instances behind a WebSocket-capable proxy/load balancer, sticky sessions, and shared Redis. The Docker image listens on `0.0.0.0:$PORT`; local development remains loopback-only. Vercel automatically selects REST polling mode; `CHAT_REALTIME_MODE=polling` can force this transport elsewhere, and `CHAT_REALTIME_MODE=socketio` selects Socket.IO on a compatible host.

## Product assumptions and current scope

Any active member can ask questions; votes are visible; authors may answer; closed questions cannot reopen; contacts without accounts cannot join. Free-text messages, attachments, invitations, notifications, and conversation retention/deletion controls are out of scope. TODO: establish product retention and conversation deletion rules before adding those operations.
