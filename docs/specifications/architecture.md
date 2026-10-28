# Architecture — current decisions

This specification describes decisions shared across pages and APIs, as reflected in the current implementation.

## Application and organization

- Flask uses the `create_app()` factory in `app/__init__.py`. The development entry point is `run.py`; environment-based configuration is in `app/config.py`.
- Authentication/OAuth is in the `auth` Blueprint; general pages and APIs are in the `main` Blueprint. Jinja templates are in `app/templates/`, CSS/JavaScript/images in `app/static/`, and integrations/business logic in `app/services/`.
- The local server uses `127.0.0.1:8000`. The production container uses Gunicorn on `0.0.0.0` and the port defined by `PORT`; do not expose local behavior to the network unless explicitly required.
- Vercel publishes the application through the `api/index.py` adapter and `vercel.json`.
- The version shown on sign-in uses the build SHA injected through the environment (`FLUTU_BUILD_COMMIT`, `VERCEL_GIT_COMMIT_SHA`, `GITHUB_SHA`, `SOURCE_VERSION`), truncated to 12 characters. Without a build SHA, configuration tries to obtain the local Git commit and uses `unknown` if it cannot.
- All pages automatically follow the device's `prefers-color-scheme` setting. Shared design tokens in `base.html` provide light and dark palettes, and the browser chrome theme color and Leaflet controls follow the same preference; there is no separate theme toggle or stored override.

## Session and identity

- Google OAuth is the only sign-in method. OAuth uses a random `state` stored in the session and validates identity through Google's trusted userinfo endpoint. There is no local password registration.
- The Flask session cookie is signed with `SECRET_KEY`/`FLASK_SECRET_KEY`, marked HttpOnly and SameSite=Lax, and has a seven-day permanent lifetime; use `FLASK_SESSION_COOKIE_SECURE=true` with HTTPS.
- The session contains user data, including Google's stable `sub`, lowercase email, name, and photo. Persistent operations use `sub` for scope/identity; never trust an owner ID supplied by the browser.
- Anonymous visits are not recorded. When MongoDB is configured, a profile in the `users` collection is updated after authentication; indexing failures are logged and do not prevent sign-in.
- `login_required` enforces access on the server: HTML page requests without a session redirect to `/` (which forwards to sign-in); `/api/*` returns JSON 401. UI controls do not replace route protection.

## Configuration and integrations

- Main variables: `FLUTU_GOOGLE_CLIENT_ID`, `FLUTU_GOOGLE_CLIENT_SECRET`, `FLUTU_GOOGLE_REDIRECT_URI`, `FLASK_SECRET_KEY`, `FLASK_SESSION_COOKIE_SECURE`, `MONGODB_URI`, `MONGODB_DATABASE`, `IBM_QUANTUM_API_KEY`, optional `IBM_QUANTUM_INSTANCE`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, and `VAPID_CONTACT`; in environments without system DNS configuration, `MONGODB_DNS_NAMESERVERS` can supply DNS resolvers. Standard Google/Vercel aliases are supported for OAuth credentials, redirect URI, and secret.
- Development callback: `http://127.0.0.1:8000/auth/google/callback`. The public callback must use HTTPS and exactly match the URL authorized in Google; the same configuration is used for authorization and OAuth code exchange.
- MongoDB is accessed on demand through `app/services/mongodb.py`; missing configuration causes functions requiring the database to report unavailability explicitly. Current collections: `contacts`, `users`, `location_shares`, `locations`, `quantum_random_batches`.
- Branching chat persists to `chat_conversations`, `chat_members`, `chat_questions`, `chat_options`, and `chat_answers`, with unique MongoDB indexes enforcing membership, option, and answer uniqueness. The creator authors the initial root question and manages members; any active member can add a follow-up under the IBM Quantum-selected option. A question's `quantum_selected_option_id` persists that selection across snapshots. It uses Flask-SocketIO with authenticated session identity, gevent, and Redis in production. The details and current limitations are in [branching-chat.md](pages/branching-chat.md).
- The decision service and quantum-selected chat branches use `IBM_QUANTUM_API_KEY` and optional `IBM_QUANTUM_INSTANCE`. They share the MongoDB `quantum_random_batches` cache, populated with 128-shot one-qubit Hadamard-and-measure jobs when no unused bits remain. A bit is reserved atomically and its stored measurement is unset immediately after consumption; batches also expire after 24 hours. Both quantum features require IBM Quantum credentials; other application features do not.
- Maps use Leaflet loaded from the unpkg CDN and tiles from the public OpenStreetMap service. The page includes copyright attribution; comply with the tile usage policy. Browser geolocation requires a secure context (HTTPS, except localhost).

## Web Push architecture and event policy

Web Push is a shared delivery capability, not a feature-specific integration. Components must use `app.services.push_notifications.notify_users()` only after their domain operation has committed successfully. A component must not call `pywebpush` directly, send from browser code, or make push delivery a condition for success of its business action. Delivery is best-effort; a push failure is logged without endpoint/key data and does not roll back location, membership, or chat writes.

### Which actions may send push

Send a push only when all of the following hold: the operation creates a meaningful new invitation/request or an action whose purpose is to get a friend/group member's attention or input; the persisted result confirms a new state transition (not a duplicate/no-op); the server resolves the recipients from authenticated identity and persisted relationships; and the recipient has a registered browser subscription. Exclude the actor from recipient IDs. Current eligible events are:

- A newly created location-sharing request (`created=true`) notifies its recipient. An accepted or declined request notifies the original requester. A duplicate request, sender cancellation, or failed transition sends nothing.
- Creating a conversation notifies only the selected account-linked members other than its creator. Adding members to an existing conversation notifies only the newly added members returned by the service. Membership is immediate; it is not an acceptance workflow.
- Creating the initial chat question or a follow-up notifies other active conversation members, excluding the author, because the question asks for their attention/input. This notification does not represent a vote or a delivery/read receipt.

Do not notify for saving contacts, unlinked contacts, a repeated or unchanged request/membership, removing members, revoking location access, location sharing toggles, GPS coordinate updates, polling, realtime invalidation, graph refresh, or unrelated quantum decisions. Do not send a push to the person who performed the action. Current event inventory and page behavior are specified in the dashboard, location-map, and branching-chat page specifications. Any future component that adds a push trigger must update this architecture section and its own page specification, and add tests for event eligibility, recipient calculation/exclusion, deduplication, and push-failure isolation in the same change.

### Event contract, recipients, and privacy

Call `notify_users(app, recipient_ids, title=..., body=..., url=..., exclude_ids=...)` after the successful write. `recipient_ids` must be Google `sub` values obtained from server-side business data, never IDs asserted by request JSON. Use short generic titles/bodies that do not disclose location coordinates, contact email, or question text on a lock screen. `url` is a same-origin path such as `/map` or `/chat/<conversation_id>`; arbitrary external destinations are rejected. The service deduplicates IDs, applies recipient/payload limits, sends only to opted-in endpoints, removes subscriptions only when the push service returns 404/410, and retains registrations after transient failures. It does not create an inbox or guarantee that a notification was displayed or read.

Subscriptions are stored in MongoDB collection `push_subscriptions`, uniquely indexed by endpoint and associated with the currently authenticated Google `sub`. Registering the same browser endpoint under another signed-in account transfers its ownership to that account; explicit unsubscribe removes only the current owner's record. Browser permission is requested only after the user activates the dashboard control. The subscription remains usable while the website is closed and is not automatically removed at logout. `POST /api/push/subscribe` and `/api/push/unsubscribe` require an authenticated session, same-origin request and session CSRF token. `GET /api/push/vapid-public-key` returns only the public key. `/sw.js` is served at the site root by Flask so its default service-worker scope covers the application; notification click targets are restricted to the same origin. Subscription endpoints are untrusted outbound URLs; the service accepts HTTPS endpoints only on known push-service hosts to mitigate SSRF.

### Setup and operations

Install project dependencies from `requirements.txt`; Web Push uses `pywebpush`, and subscription persistence reuses `MONGODB_URI`/`MONGODB_DATABASE` without a second database. Generate one P-256 VAPID key pair in a trusted local environment and keep it stable: replacing the pair invalidates all existing browser subscriptions. Configure `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` (server-only secret), and `VAPID_CONTACT` (a valid `mailto:` contact) in local `.env` and in every Vercel environment used for deployment/preview. `.env.example` contains placeholders only. Never commit generated keys. Missing MongoDB or VAPID configuration disables subscription/send APIs with an explicit unavailable response; it never falls back to local-file storage. HTTPS is required outside localhost. Android Chrome supports web push; iOS requires the website to be added to the Home Screen and installed as a web app. See README for the key-generation and deployment walkthrough.

## Personal data and location

- Contacts have `owner_id` equal to the Google `sub`, name, phone, email, and creation date. Endpoints always scope operations to the authenticated owner.
- On sign-in, the `users` directory is updated by `sub` and contains normalized email and name for resolving sharing requests. Account lookup uses email, but identity/persistence uses Google's `sub`.
- Each sharing relationship in `location_shares` connects a requester to a recipient with states `pending`, `accepted`, `declined`, `cancelled`, or `revoked`. Only the recipient can accept/decline, and only the sender can cancel pending requests. Accepting adds the requester to the recipient's contacts if not already present.
- Profiles have no marker selection setting. Markers use the Google profile photo, with initials as a fallback; `users.picture` is updated at sign-in only when Google provides a photo, preserving a saved value when the field is absent. The overview provides other people's photos only for IDs linked to accepted shares. `GET /api/location/status` returns the current user's photo for the private marker.
- The recipient gives consent for each request. The location owner must also explicitly enable updates and allow browser geolocation. Opt-in is stored in `users.location_sharing_enabled` and can be paused on the map page.
- A location is a GeoJSON point, accuracy, and optional Google photo in one document per user, upserted by unique `owner_id`. Updates occur about every 30 seconds while any authenticated page is visible. A hidden tab pauses sending; returning to the foreground requests a location immediately. MongoDB timestamps are serialized in UTC with a `Z` suffix so freshness calculations are correct in any device timezone.
- Only on `/map`, the browser also reads the position about every 30 seconds to draw a local device marker, starting when the page opens. Without opt-in, these coordinates exist only in the browser page memory: they are not sent to the API or persisted. With opt-in active, the marker uses the recent point returned by the server.
- Approximate distance to people in the sharing list and remote-marker popups is calculated client-side using Haversine, with a recent own location (up to 120 seconds) and only points the other person has shared with the user under an accepted grant. The UI distinguishes a stale own coordinate from the absence of reciprocal sharing. Without both points, distance is unavailable; no additional unilateral tracking or distance storage occurs.
- When sharing is enabled on the map, geolocation is requested directly from the user's click before saving opt-in, allowing the browser to show its permission prompt. Errors for denied permission, unavailable/timed-out GPS, and lack of HTTPS are shown in the UI. The global indicator reports recent location acquisition/sending failures.
- Only requesters with an `accepted` share can see a point. The authenticated owner can also see their own recent point while opt-in is enabled. Locations not updated for at least 120 seconds are excluded from the API; a TTL index removes documents after 180 seconds of inactivity. Pausing opt-in or revoking the last grant removes the document immediately. Revoking one of multiple shares keeps the location available to the other authorized recipients.
- Locations are not a history/track. Browser behavior is best-effort; geolocation can be denied/unavailable and closed pages do not send updates.

## Navigation, errors, and documentation

- `/dashboard` is level 1. Pages linked from it are level 2 and return to the dashboard. The information page is level 3 and returns to the decision page that opened it.
- Protected APIs return appropriate HTTP status codes and JSON messages; MongoDB unavailability is reported as 503. Location APIs validate coordinates on the server and do not accept user identity from the client.
- Chat mutation APIs additionally require the session CSRF token and same-origin request validation. Socket handlers authorize active membership on every event and broadcast to active per-user rooms.
- Each page has a specification in `docs/specifications/pages/`; this specification contains cross-cutting decisions only. The README describes configuration and operation; update both alongside relevant changes. All project documentation must be written in English.
