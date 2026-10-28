# ux9.eu

ux9.eu is a small Flask application with Google-only OAuth sign-in, a protected dashboard, a personal contacts list, private OpenStreetMap-based location sharing, and a quantum-random direction demo. The existing logo is retained; Flutu remains the internal repository and configuration name.

The interface automatically follows the device's light or dark appearance preference, including system browser controls and the map's interface elements. Authenticated users can also create live branching conversations with contacts who have Flutu accounts and opt in to Web Push notifications for friend requests and collaborative chat activity.

## Links

- **Demo:** [https://ux9.eu](https://ux9.eu)
- **GitHub repository:** [mutualendemic/flutu](https://github.com/mutualendemic/flutu)

## Requirements

- Python 3.10 or later
- Google OAuth 2.0 credentials (Web application)
- MongoDB for persistent data
- Redis for production Socket.IO broadcasts

## Setup and run

1. Create the project's virtual environment and install dependencies:

  ```bash
  python3 -m venv .venv
  ./.venv/bin/python -m pip install -r requirements.txt
  ```

2. Copy `.env.example` to `.env` and fill in the Google OAuth client ID, client secret, a unique `FLASK_SECRET_KEY`, `FLUTU_GOOGLE_REDIRECT_URI`, and the MongoDB Atlas values `MONGODB_URI` and `MONGODB_DATABASE`. Set `IBM_QUANTUM_API_KEY` to a key from the IBM Quantum Platform dashboard: it is required for both `/api/decision` and quantum-selected chat branches. `IBM_QUANTUM_INSTANCE` is optional and selects an instance by CRN. Keep credentials private and never commit them. If the local runtime has no `/etc/resolv.conf`, `MONGODB_DNS_NAMESERVERS` supplies DNS servers for resolving Atlas `mongodb+srv` addresses; it is ignored whenever system DNS configuration exists.
   The app also accepts the standard Vercel/Google names (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `SECRET_KEY`) as fallbacks when those are configured instead.
3. Add the exact redirect URI to the authorized redirect URIs in Google Cloud Console. For local development it is `http://127.0.0.1:8000/auth/google/callback`.
4. Start the app with `bash start_server.sh`.
5. Open http://127.0.0.1:8000. The development server binds exclusively to `127.0.0.1` and is not exposed to the local network.

The public home page explains the main capabilities before sign-in. The interface supports English (UK, `en_GB`) and Portuguese (Portugal, `pt_PT`), selected from the language control or the browser's `Accept-Language` preference. The explicit choice is retained through sign-in and logout. Flask-Babel reads gettext catalogs from `app/translations/`; after changing a `.po` file, compile it with `python -m babel.messages.frontend compile -d app/translations`. The landing page, sign-in page, and dashboard currently have translated copy; the remaining authenticated pages and client-side messages are being localized incrementally. See the localization design in `docs/specifications/architecture.md`.

Chat uses Supabase Realtime Broadcast by default when Supabase is configured; MongoDB remains the source of truth. Without Supabase, local development can use Flask-SocketIO/gevent (start with `bash start_server.sh`, not `flask run`). Redis is only needed for multi-instance Socket.IO deployment. `CHAT_REALTIME_MODE` supports `supabase`, `socketio`, and `polling`.

Google OAuth is the only sign-in method; there is no local email/password login. For local development, `FLASK_SESSION_COOKIE_SECURE=false` allows cookies over HTTP. Set it to `true` when serving over HTTPS. Never use the development fallback session key in a deployed environment.

### Web Push setup

Web Push uses the existing MongoDB database for subscriptions and does not require a separate Postgres service. Install the project requirements, then generate a VAPID key pair once in a trusted local Python environment. Keep the same keys across deploys: rotating them invalidates existing browser subscriptions. Do not commit the private key or paste it into frontend code.

```python
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

private_key = ec.generate_private_key(ec.SECP256R1())
private_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")
public_bytes = private_key.public_key().public_bytes(
  serialization.Encoding.X962,
  serialization.PublicFormat.UncompressedPoint,
)
encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
print("VAPID_PUBLIC_KEY=" + encode(public_bytes))
print("VAPID_PRIVATE_KEY=" + encode(private_bytes))
```

Copy the output securely into local `.env` and the Vercel environment settings for every environment that should send pushes:

- `VAPID_PUBLIC_KEY` — public application-server key returned to the dashboard browser.
- `VAPID_PRIVATE_KEY` — server-only secret; never expose or commit it.
- `VAPID_CONTACT` — valid VAPID contact URI, for example `mailto:ops@example.com`.

Set the same values in Vercel Project Settings → Environment Variables, redeploy, and keep `FLASK_SESSION_COOKIE_SECURE=true`. The application serves the root-scoped worker at `/sw.js`; no `public/` directory, filesystem persistence, or extra database URL is needed. Push permission is requested only when the signed-in user presses **Enable notifications** on the dashboard. The user can disable a device there. Notifications are best-effort and only reach browsers that opted in. Android Chrome supports Web Push; on iOS, the site must be added to the Home Screen and installed as a web app. No generic public broadcast/send endpoint is provided.

The sign-in page displays the running version as a short Git commit hash. Deployments should provide `FLUTU_BUILD_COMMIT` (or the platform's `VERCEL_GIT_COMMIT_SHA`, `GITHUB_SHA`, or `SOURCE_VERSION`); local development reads the current Git commit when available.

For new Web Push event integrations, follow the shared eligibility and delivery contract in `docs/specifications/architecture.md`: send only for meaningful new friend requests/invitations or actions requesting friend/group input, resolve recipients from server-side persisted relationships, exclude the actor, and never push on polling/heartbeats/repeated no-op updates. Update the architecture and relevant page specification and add eligibility/recipient/failure tests with every new trigger.

## Vercel deployment

The repository includes a Vercel-compatible Flask export at `api/index.py`. Vercel serves HTTP requests and the browser connects directly to Supabase Realtime for private, low-latency chat invalidations. MongoDB remains authoritative; every notification makes the browser reload data through Flask’s authorized API. If Supabase is missing or unavailable, the client falls back to polling. The app selects Supabase mode automatically on Vercel; set `CHAT_REALTIME_MODE` explicitly to override it.

1. Add the project to Vercel and keep the repository root as the project root.
2. In the Vercel project environment settings, define the same Google OAuth variables used in local development:

   - `FLUTU_GOOGLE_CLIENT_ID`
   - `FLUTU_GOOGLE_CLIENT_SECRET`
   - `FLUTU_GOOGLE_REDIRECT_URI`
   - `FLASK_SECRET_KEY`
   - `FLASK_SESSION_COOKIE_SECURE=true`
   - `MONGODB_URI` (Atlas connection string; server-side only)
   - `MONGODB_DATABASE` (for example, `flutu`)
  - `VAPID_PUBLIC_KEY` (public key used by browser subscription)
  - `VAPID_PRIVATE_KEY` (server-only secret; never expose to the browser)
  - `VAPID_CONTACT` (for example, `mailto:ops@example.com`)
    - `IBM_QUANTUM_API_KEY` (server-side key required for decisions and quantum chat branches)
    - `IBM_QUANTUM_INSTANCE` (optional IBM Quantum instance CRN)
   - `SUPABASE_URL` and `SUPABASE_ANON_KEY` (the anon/publishable key is intended for browser use)
   - `SUPABASE_SERVICE_ROLE_KEY` (server-only secret; never expose it to the browser)
    - `SUPABASE_JWT_SECRET` (the same project's legacy HS256 JWT signing secret; server-only, not the anon key, service-role key, or database password)
   - `CHAT_REALTIME_MODE=supabase`

3. In Supabase Dashboard, open **SQL Editor → New query** and run this setup to enable RLS and add the topic allow-list policy:

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

  When the chat page loads, it first checks that its authorized private topic is accepted, then tries a random topic not allowed by its token. That probe must be rejected; if Supabase accepts it, the page warns that RLS is disabled or too broad and falls back to polling. This verifies the effective authorization path, but does not replace inspecting the SQL policies.

  Run this read-only query to validate the RLS setting, find the expected policy, and inspect every SELECT policy:

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

  Expected: both `rls_enabled` and `expected_topic_policy_exists` are `true`. Review all returned policies: permissive SELECT policies are combined with OR, so remove any unintended broad policy. The Flask API issues short-lived topic-scoped tokens after checking the existing session and membership. Broadcasts contain only an event kind; details are fetched from Flask. Never expose the service-role key or JWT signing secret in browser code.

4. Set `FLUTU_GOOGLE_REDIRECT_URI` to the exact HTTPS callback URL Vercel assigns to the app, such as `https://<your-project>.vercel.app/auth/google/callback`.
5. Add that exact callback URL to the Google OAuth client authorized redirect URIs.
6. Deploy; Vercel uses `vercel.json` to route all requests to `api/index.py`.

The local development server stays bound to `127.0.0.1`, while the Vercel export keeps the same app factory and routes as the local app.

## Architecture

```text
run.py                      Flask development entry point
app/
  __init__.py                Application factory and Blueprint registration
  config.py                  Environment-backed application configuration
  auth/
    decorators.py             Server-side login protection
    routes.py                 Google login, OAuth callback, logout
  main/
    routes.py                 Dashboard, decision and API routes
    chat/
      routes.py                 Protected chat pages and REST endpoints
      sockets.py                Authenticated Socket.IO event handlers
  services/
    google_oauth.py           Google authorization-code and userinfo integration
    contacts.py               MongoDB contacts, scoped by Google account
    location_sharing.py       Consent requests and private location updates
    chat.py                   MongoDB chat documents, validation and graph snapshots
    mongodb.py                Shared MongoDB collection access
    quantum_random.py         IBM Quantum hardware random measurement
  templates/
    base.html                 Shared Jinja layout
    login.html                Google-only sign-in page
    dashboard.html            Authenticated root (level 1)
    contacts.html             Private contacts list with optional phone import (level 2)
    location_map.html         Private OpenStreetMap and sharing controls (level 2)
    profile.html              Private account and map-marker preferences (level 2)
    decision.html             Decision page (level 2)
    quantum_info.html          Decision information (level 3)
  static/
    logo.svg                  Shared static logo
    location-sharing.js       Authenticated cross-route location updates
    chat-list.js               Conversation list and contact picker
    chat-conversation.js       Fixed-position branching graph, quantum paths and live updates
tests/
  test_routes.py              Authentication, route, and session tests
  test_google_oauth.py         Google OAuth service tests
```

Routes are grouped by concern in Flask Blueprints and registered by `create_app()`. Templates extend `base.html`; integration and business logic live in dedicated modules, not in route handlers or templates. Google sign-in uses the OAuth 2.0 authorization-code flow with session-bound state validation and Google's userinfo endpoint.

The implementation decisions for cross-page architecture and each user-facing page are maintained in [docs/specifications/README.md](docs/specifications/README.md). Update the relevant specification whenever implementation decisions or page behavior change.

## Authentication and page hierarchy

- Google OAuth login: `/auth/login`; callback: `/auth/callback` (the legacy `/auth/google/callback` remains supported); logout: `/auth/logout`.
- `/dashboard` is the authenticated root at level 1. Its child pages return to their immediate parent.
- `/contacts` is a level-2 page linked from the dashboard. Contacts are persisted in MongoDB and scoped to the signed-in Google account's stable `sub` identifier, making them available across devices. The server derives the owner from the authenticated session and never accepts an owner ID from the browser.
- `/map` is a level-2 page linked from the dashboard. It lets a user request location sharing from a saved contact with an email address. The recipient sees the request on their map page and can accept or decline it; accepting also adds the requester to the recipient's contacts. A recipient can revoke one grant or all grants at any time. Opening the map tracks the current device locally every 30 seconds and shows the user's Google profile photo as a marker (or initials if no photo is available); private map readings are not sent to the server. To share with contacts, the owner must accept at least one incoming request and explicitly enable sharing; that action invokes the browser's native location-permission prompt (there is no separate Flutu authorization page). Shared positions are shown to authorized requesters.
- `/profile` is a level-2 page linked from the dashboard. It shows the signed-in Google account and explains that the profile photo is used as the user's map marker, with initials as a fallback. The profile page remains available; it no longer contains marker selection controls.
- On the map, distance to a person you share your location with is calculated locally only when you have a recent own position and that person has separately shared their location with you. Otherwise the distance is unavailable; Flutu does not infer or request their location without their consent.
- The map reports whether an unavailable distance is due to your device position being stale or the other person not sharing their current position with you. Distance is also included in remote marker popups. Map markers use the Google profile photo, falling back to initials if unavailable.
- The Google profile directory used to match sharing requests is refreshed on sign-in and stored in MongoDB. A contact must have signed in to Flutu at least once to receive a request. A newly created location-sharing request sends an opted-in recipient a generic Web Push linking to the map; acceptance or refusal notifies the requester. Duplicate requests and requester-initiated cancellation do not send pushes.
- Sharing requires recipient consent and a separate explicit start action by the location owner, in addition to browser geolocation permission. Once enabled on the map page, the app updates location about every 30 seconds on any authenticated app route while the app is visible. The opt-in is stored in the user's MongoDB profile and remains active across route changes; it can be paused from the map page. MongoDB upserts one latest GeoJSON location document per user instead of creating a record for every update. The location is returned only to accepted requesters, hidden when it has not been updated for two minutes, and automatically expires from MongoDB after three minutes without an update; pausing sharing or revoking the final active grant deletes it immediately. Browser geolocation requires HTTPS outside localhost. OpenStreetMap map tiles come from its public tile service and are subject to the OpenStreetMap tile usage policy.
- **Import from phone** uses the browser Contact Picker API when available; support varies by mobile browser and it requires HTTPS. As a fallback, export contacts from the phone as a `.vcf`/vCard file and use **Import .vcf file**. The page also allows manual entry and search.
- `/decision` is level 2; `/decision/info` is level 3 and returns to `/decision`.
- The dashboard provides **Quantum path selector**, **My contacts**, **Location map**, and **My profile** options.
- `/chat/` is a level-2 page linked from the dashboard. It lists conversations, creates conversations using account-linked Contacts, and links to each member-only graph at `/chat/<conversation_id>`. A conversation returns to its list. REST mutations require a session CSRF token. Socket handlers reuse the Google-authenticated Flask session, verify active membership for every event, and broadcast only to active per-user rooms. Newly added conversation members receive an opted-in generic push. The creator writes one initial question with 2–10 options; IBM Quantum selects and persists a single option. Every active participant can then add a follow-up question with its own options to that selected option; other active members receive an opted-in generic push for a new question/follow-up, excluding its author. The graph alternates question/author and vertically stacked option columns; it marks the selected path and follow-up connections, keeps nodes fixed, and provides fit/zoom/pan controls.
- Unauthenticated page requests redirect to sign-in. Protected APIs return JSON `401` without performing the requested action.

## APIs

`GET /api/contacts`, `POST /api/contacts`, and `DELETE /api/contacts` manage the signed-in user's contacts. `DELETE /api/contacts/<id>` removes an individual contact. Every route requires authentication and scopes data to the Google account in the session.

Location sharing APIs also require a session and derive identities from it: `GET /api/location/status` returns the caller's opt-in, active-recipient count, and profile photo; `POST /api/location/sharing` enables or pauses updates; `GET /api/location/overview` returns pending requests, active grants, and locations shared with the caller; `POST /api/location/requests` requests a saved contact's location; `POST /api/location/requests/<id>/respond` accepts, declines, or cancels a pending request; `POST /api/location/updates` upserts the signed-in user's latest coordinates only if the owner opted in and an active grant exists; `DELETE /api/location/shares/<id>` revokes one grant; and `DELETE /api/location/shares` revokes all grants. Coordinates are validated server-side, and a location is disclosed only when an accepted request connects its owner and the viewer. Map markers use the Google profile photo (or initials if unavailable); there is no marker-selection API.

Web Push APIs: `GET /api/push/vapid-public-key` returns only the public key; authenticated `POST /api/push/subscribe` and `/api/push/unsubscribe` register or remove the current browser endpoint for the signed-in Google account. Mutations require the dashboard's session CSRF token and same-origin requests. Subscription endpoints are limited to HTTPS push-service hosts. Delivery is event-driven and best-effort; see the architecture specification for eligible triggers, recipient rules, exclusions, and security behavior.

Chat APIs are under `/chat/api/`: list/create/delete conversations, graph snapshots, member add/remove, addable contacts, and quantum-path question creation. Voting and manual question closing are disabled. Question editing/deletion endpoints are locked in quantum branch mode. Only a conversation's creator can permanently delete it; deletion removes its members, questions, options, and answer records. Supabase Realtime Broadcast sends private invalidation events; Socket.IO remains available for self-hosted deployments. The app also supports REST polling as a fallback. For Socket.IO, use gevent Gunicorn, one worker per process, Redis shared among instances, sticky sessions, and WebSocket proxy upgrade support. Set the container's `PORT`; the Docker image binds to `0.0.0.0` while local development remains on `127.0.0.1`. Supabase JS 2.49.1, Socket.IO client 4.8.1, and Cytoscape 3.30.4 are pinned on jsDelivr. See [docs/specifications/pages/branching-chat.md](docs/specifications/pages/branching-chat.md).

`POST /api/decision` consumes one bit from a MongoDB cache populated by 128-shot one-qubit Hadamard-and-measure jobs on operational IBM Quantum hardware. Quantum-selected chat branches use the same provider and cache. A new hardware job is submitted only when no cached bits remain, so the first decision or branch selection of a batch can wait for the hardware queue while later choices use cached bits. Batches expire after 24 hours. `IBM_QUANTUM_API_KEY` is required for both features; `IBM_QUANTUM_INSTANCE` is optional and selects a specific instance. For `/api/decision`, a hardware result of `1` means right, and `0` means left:

```json
{"go_right": true}
```

## Tests

Run the route, session-protection, and OAuth-flow tests with `./.venv/bin/python -m unittest discover -s tests -v`.

## Copilot restart hook

The workspace hook in `.github/hooks/restart-app.json` runs `.github/hooks/restart-app.sh` after agent tool actions. It tracks the Flask application, templates, static files, configuration, dependencies, and startup script; when they change, it restarts the local server using `.env`. Logs are written to `/tmp/flutu-server.log`.
