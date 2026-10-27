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

- Main variables: `FLUTU_GOOGLE_CLIENT_ID`, `FLUTU_GOOGLE_CLIENT_SECRET`, `FLUTU_GOOGLE_REDIRECT_URI`, `FLASK_SECRET_KEY`, `FLASK_SESSION_COOKIE_SECURE`, `MONGODB_URI`, `MONGODB_DATABASE` and, in environments without system DNS configuration, `MONGODB_DNS_NAMESERVERS`. Standard Google/Vercel aliases are supported for credentials/URI/secret.
- Development callback: `http://127.0.0.1:8000/auth/google/callback`. The public callback must use HTTPS and exactly match the URL authorized in Google; the same configuration is used for authorization and OAuth code exchange.
- MongoDB is accessed on demand through `app/services/mongodb.py`; missing configuration causes functions requiring the database to report unavailability explicitly. Current collections: `contacts`, `users`, `location_shares`, `locations`, `quantum_random_batches`.
- Branching chat persists to `chat_conversations`, `chat_members`, `chat_questions`, `chat_options`, and `chat_answers`, with unique MongoDB indexes enforcing membership, option, and answer uniqueness. A question's `quantum_selected_option_id` persists its IBM Quantum-selected branch across graph snapshots and votes. It uses Flask-SocketIO with authenticated session identity, gevent, and Redis in production. The details and current limitations are in [branching-chat.md](pages/branching-chat.md).
- The decision service uses `IBM_QUANTUM_API_KEY` and optional `IBM_QUANTUM_INSTANCE`. It submits a 128-shot one-qubit Hadamard-and-measure circuit when its MongoDB `quantum_random_batches` collection has no unused bits. Bits are consumed with atomic MongoDB updates and batches expire after 24 hours, so a hardware job is needed only when refilling a batch.
- Maps use Leaflet loaded from the unpkg CDN and tiles from the public OpenStreetMap service. The page includes copyright attribution; comply with the tile usage policy. Browser geolocation requires a secure context (HTTPS, except localhost).

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
