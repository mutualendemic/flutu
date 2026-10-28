# Branching chat

## Findings before implementation

- Authentication is the existing Google OAuth flow. The signed Flask session identifies users by Google's stable `sub`; no second auth system was added.
- Contacts are MongoDB documents owned by the session user's `sub`. A contact is linked to a Flutu account by normalized email against the `users` collection; unlinked contacts are displayed disabled.
- The application uses MongoDB and PyMongo, not SQLAlchemy or a migration framework. Chat data is stored in dedicated MongoDB collections with unique indexes for members, option labels/positions, and one answer per question and user.
- The project uses a Flask factory, Blueprints, Jinja templates, and vanilla JavaScript.
- Chat persistence remains in MongoDB/PyMongo. Realtime invalidation is delivered through Supabase Broadcast on Vercel and can use Flask-SocketIO on a self-hosted deployment. MongoDB is authoritative; clients fetch all conversation data through authenticated Flask APIs.

## Pages and access

- `/chat/` is a level-2 authenticated page linked from the dashboard; it returns to `/dashboard`.
- `/chat/<conversation_id>` is a child of the conversation list and returns to `/chat/`. It is only rendered for active members.
- `/chat/api/*` is protected on the server. Unauthenticated requests return JSON 401; mutating REST requests require the session CSRF token in `X-CSRF-Token` and a same-origin request.
- REST APIs support listing and creating conversations, graph snapshots, member add/remove, conversation deletion, addable contacts, question creation, and closing. The conversation creator can add/remove members and create the single root question; any active member can create follow-up questions under the quantum-selected option, up to three nested follow-up levels. Edit/delete question endpoints are disabled. All mutating routes require CSRF validation. `DELETE /chat/api/conversations/<conversation_id>` is restricted to the conversation creator and permanently deletes the conversation, member records, questions, options, and answers. It requires an explicit browser confirmation and notifies all active members so their lists update and open conversation pages return to the list. `GET /chat/api/realtime-token` returns a short-lived Supabase JWT, project URL, public anon key, and only the user topic plus an optionally requested conversation topic. It rejects requests for conversations where the caller is not an active member.
- Newly added members receive an opted-in generic Web Push to the conversation; the creator and existing members are excluded. Creating a root question or follow-up sends an opted-in generic push to other active members, excluding the author. These are attention notifications, not votes or read receipts; realtime invalidation remains the in-app update mechanism. Delivery follows the centralized policy in [architecture.md](../architecture.md).

## Persistence and rules

Chat documents use `chat_conversations`, `chat_members`, `chat_questions`, `chat_options`, and `chat_answers`. Google `sub` values are user IDs. Former members remain in `chat_members` and their answers remain visible in graph history. Active member IDs are also maintained on conversation documents for listing.

Question text is limited to 280 characters. Option labels are trimmed, case-insensitively unique, and limited to 2–10 options of at most 60 characters. Missing options default to Yes and No. Follow-up depth is limited to three nested levels. Each question's IBM Quantum-selected option is persisted and determines the only option to which participants can add a follow-up. The initial question is restricted to the conversation creator; all active members can add follow-ups under the selected option. Question editing and deletion are unavailable in this mode.

MongoDB writes use unique indexes and atomic upserts for answers. There is no cross-document transaction requirement or SQL migration. Operations are written before events are emitted.

Each question stores its selected branch in `quantum_selected_option_id`. The first graph snapshot without a valid stored selection consumes IBM Quantum random bits and saves the choice; later snapshots use the stored option. For questions with multiple options, the random bits form an index and rejection sampling avoids bias when the number of options is not a power of two. A single-option question selects its only option without consuming a bit. Members do not vote: the quantum-selected option is the sole path available for follow-up. The creator authors the initial root question; all active participants, including the creator, can add follow-up questions to the selected option.

Conversation deletion is creator-only and permanent. The service marks the conversation deleted before removing its answers, options, questions, memberships, and conversation document. This prevents access while the cascade runs and lets a repeated request retry cleanup after a partial database failure. Deleted content cannot be restored.

## Live graph and client

- Supabase Realtime uses private Broadcast topics `chat-user:<base64url-user-id>` and `chat-conversation:<conversation-id>`. The backend publishes only invalidation events, never question text, member names, or option contents. After a broadcast, clients fetch fresh data from Flask, which rechecks session authentication and active membership.
- Flask signs short-lived (five-minute) HS256 JWTs using `SUPABASE_JWT_SECRET`. Each token has role `authenticated` and a `chat_topics` allow-list. Supabase's `realtime.messages` SELECT RLS policy checks that the current topic is in this claim. Conversation tokens are issued only after a server-side active-membership check. The browser receives only `SUPABASE_ANON_KEY`; the service-role key and JWT signing secret remain server-side.
- Conversation list pages subscribe only to their private user topic. A conversation page subscribes to that user's topic and the single conversation topic. Clients refresh their token/channels when membership or conversation-list events arrive.
- The browser receives a full snapshot on initial load and updates Cytoscape elements in place after a broadcast. Before the first question, a centered Flutu logo and ready message appear over the graph; this empty-state overlay fades away once a question is present. The graph uses fixed, deterministic columns alternating between question cards (including author name) and vertically stacked options, followed by the next question column. The selected quantum option is highlighted with a green node and edge; follow-up questions connect from their exact parent option with labeled purple edges. Nodes are locked against dragging. The initial graph is fit to view, and explicit fit/zoom controls plus panning let users inspect larger flows; minimum zoom is low enough to fit long graphs. Conversation summaries show the question count rather than unanswered/vote counts.
- The Members control is a visible switch with `role="switch"`, `aria-checked`, and panel disclosure attributes. Member records include the profile photo captured when they join; every question graph card displays its author's profile image (or initials fallback), and selecting a question also shows the author's avatar, name, and status in the details panel.
- Async action buttons use a shared pending state: they are disabled and marked busy until the request finishes, preventing duplicate submissions. Immediate local controls such as adding an option or toggling the Members panel remain responsive.
- Socket.IO remains an optional self-hosted transport under namespace `/chat`; authenticated connections join per-user rooms, every event rechecks membership, and events are rate-limited to 20 per connection in 10 seconds. Supabase mode does not require Redis or persistent Flask WebSockets.
- If Supabase is not configured or its client/channel cannot connect, the browser falls back to authenticated REST polling. This fallback is slower than Broadcast.
- User text is assigned through DOM text nodes and Cytoscape labels; the client does not use `innerHTML`.
- Cytoscape.js 3.30.4, Supabase JS 2.49.1, and Socket.IO client 4.8.1 are pinned CDN assets. They are not vendored in this release; deployments need network access to jsDelivr.

## Deployment

Supabase mode requires `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_JWT_SECRET`. `SUPABASE_JWT_SECRET` must be the project's legacy HS256 JWT secret used for signing tokens, not the anon key, service-role key, database password, or a publishable key. Keep the URL, anon key, service-role key, and JWT secret from the same Supabase project. In Supabase Dashboard, open **SQL Editor → New query** and execute this setup. It enables RLS and replaces the named policy if it already exists:

```sql
alter table realtime.messages enable row level security;

drop policy if exists "Chat members receive authorized broadcasts"
on realtime.messages;

create policy "Chat members receive authorized broadcasts"
on realtime.messages
for select
to authenticated
using ((select auth.jwt() -> 'chat_topics') ? realtime.topic());
```

At page load the client first subscribes to its allowed private topic, then tries to subscribe to a random private topic absent from its signed token. The allowed subscription must succeed and the probe must be rejected; an accepted probe is treated as an RLS failure and the UI falls back to polling with a warning. This checks the effective authorization path, including unexpectedly broad policies. It does not replace reviewing database policy configuration.

Use this read-only audit query to check that RLS is enabled, the expected allow-list policy exists, and see every SELECT policy that could also grant access:

```sql
with target as (
	select c.relrowsecurity as rls_enabled
	from pg_class c
	join pg_namespace n on n.oid = c.relnamespace
	where n.nspname = 'realtime' and c.relname = 'messages'
), policies as (
	select
		count(*) filter (
			where policyname = 'Chat members receive authorized broadcasts'
				and cmd = 'SELECT'
				and 'authenticated' = any(roles)
				and coalesce(qual, '') ilike '%chat_topics%'
				and coalesce(qual, '') ilike '%realtime.topic%'
		) as expected_policy_count,
		coalesce(jsonb_agg(jsonb_build_object(
			'name', policyname,
			'roles', roles,
			'using', qual
		)), '[]'::jsonb) as select_policies
	from pg_policies
	where schemaname = 'realtime'
		and tablename = 'messages'
		and cmd = 'SELECT'
)
select
	coalesce(target.rls_enabled, false) as rls_enabled,
	policies.expected_policy_count > 0 as expected_topic_policy_exists,
	policies.select_policies
from policies
left join target on true;
```

Expected: `rls_enabled = true` and `expected_topic_policy_exists = true`. Review every item in `select_policies`: PostgreSQL combines permissive policies with OR, so a broader SELECT policy could weaken the topic restriction even when the expected policy is present. Remove any unintended broad policy. The page's unauthorized-topic probe should be denied; acceptance means RLS is disabled or a policy is broader than intended.

Set `CHAT_REALTIME_MODE=supabase`; Vercel selects it automatically. Supabase Broadcast is client WebSocket-to-Supabase, not a persistent connection to the Vercel Flask function. Redis is not required in this mode. If Supabase is absent, the client falls back to REST polling. For a self-hosted Socket.IO deployment, set `CHAT_REALTIME_MODE=socketio`, `APP_ENV=production`, `REDIS_URL`, and the gevent Gunicorn worker. Set `SOCKETIO_CORS_ORIGINS` only to comma-separated origins that serve this app; unset means same-origin only. Each Gunicorn process must use one worker; scale with multiple single-worker instances behind a WebSocket-capable proxy/load balancer, sticky sessions, and shared Redis. The Docker image listens on `0.0.0.0:$PORT`; local development remains loopback-only.

## Product assumptions and current scope

The selector chooses one option per question and active members can continue only that path by adding follow-up questions; voting and manual closing are not part of quantum branch mode. Only the creator can author the initial question and manage members; any active member can add follow-ups. Question edits/deletions are disabled. Contacts without accounts cannot join or receive Web Push. The creator can permanently delete a conversation and all its chat content. Free-text messages, attachments, and external invitations are out of scope.
