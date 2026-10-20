# Flutu

Flutu is a small Flask application with Google-only OAuth sign-in, a protected dashboard, a personal contacts list, private OpenStreetMap-based location sharing, and a quantum-random direction demo.

## Links

- **Demo:** [https://ux9.eu](https://ux9.eu)
- **GitHub repository:** [mutualendemic/flutu](https://github.com/mutualendemic/flutu)

## Requirements

- Python 3.10 or later
- Google OAuth 2.0 credentials (Web application)

## Setup and run

1. Create the project's virtual environment and install dependencies:

  ```bash
  python3 -m venv .venv
  ./.venv/bin/python -m pip install -r requirements.txt
  ```

2. Copy `.env.example` to `.env` and fill in the Google OAuth client ID, client secret, a unique `FLASK_SECRET_KEY`, `FLUTU_GOOGLE_REDIRECT_URI`, and the MongoDB Atlas values `MONGODB_URI` and `MONGODB_DATABASE`. Keep the URI quoted in `.env`, and never commit credentials. If the local runtime has no `/etc/resolv.conf`, `MONGODB_DNS_NAMESERVERS` supplies DNS servers for resolving Atlas `mongodb+srv` addresses; it is ignored whenever system DNS configuration exists.
   The app also accepts the standard Vercel/Google names (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `SECRET_KEY`) as fallbacks when those are configured instead.
3. Add the exact redirect URI to the authorized redirect URIs in Google Cloud Console. For local development it is `http://127.0.0.1:8000/auth/google/callback`.
4. Start the app with `bash start_server.sh`.
5. Open http://127.0.0.1:8000. The development server binds exclusively to `127.0.0.1` and is not exposed to the local network.

Google OAuth is the only sign-in method; there is no local email/password login. For local development, `FLASK_SESSION_COOKIE_SECURE=false` allows cookies over HTTP. Set it to `true` when serving over HTTPS. Never use the development fallback session key in a deployed environment.

The sign-in page displays the running version as a short Git commit hash. Deployments should provide `FLUTU_BUILD_COMMIT` (or the platform's `VERCEL_GIT_COMMIT_SHA`, `GITHUB_SHA`, or `SOURCE_VERSION`); local development reads the current Git commit when available.

## Vercel deployment

The repository includes a Vercel-compatible Flask export at `api/index.py`. Vercel looks for a callable WSGI app object at the `api` entrypoint, and this project exports the existing Flask application factory there without changing the local development behavior.

1. Add the project to Vercel and keep the repository root as the project root.
2. In the Vercel project environment settings, define the same Google OAuth variables used in local development:

   - `FLUTU_GOOGLE_CLIENT_ID`
   - `FLUTU_GOOGLE_CLIENT_SECRET`
   - `FLUTU_GOOGLE_REDIRECT_URI`
   - `FLASK_SECRET_KEY`
   - `FLASK_SESSION_COOKIE_SECURE=true`
  - `MONGODB_URI` (Atlas connection string; server-side only)
  - `MONGODB_DATABASE` (for example, `flutu`)

3. Set `FLUTU_GOOGLE_REDIRECT_URI` to the exact HTTPS callback URL Vercel assigns to the app, such as `https://<your-project>.vercel.app/auth/google/callback`.
4. Add that exact callback URL to the Google OAuth client authorized redirect URIs.
5. Deploy; Vercel uses `vercel.json` to route all requests to `api/index.py`.

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
  services/
    google_oauth.py           Google authorization-code and userinfo integration
    contacts.py               MongoDB contacts, scoped by Google account
    location_sharing.py       Consent requests and private location updates
    mongodb.py                Shared MongoDB collection access
    quantum_random.py         ANU quantum-random integration
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
- The map reports whether an unavailable distance is due to your device position being stale or the other person not sharing their current position with you. Map markers use the Google profile photo, falling back to initials if unavailable.
- The Google profile directory used to match sharing requests is refreshed on sign-in and stored in MongoDB. A contact must have signed in to Flutu at least once to receive a request. Requests are in-app and appear when the recipient next opens the map page; there are no push notifications.
- Sharing requires recipient consent and a separate explicit start action by the location owner, in addition to browser geolocation permission. Once enabled on the map page, the app updates location about every 30 seconds on any authenticated app route while the app is visible. The opt-in is stored in the user's MongoDB profile and remains active across route changes; it can be paused from the map page. MongoDB upserts one latest GeoJSON location document per user instead of creating a record for every update. The location is returned only to accepted requesters, hidden when it has not been updated for two minutes, and automatically expires from MongoDB after three minutes without an update; pausing sharing or revoking the final active grant deletes it immediately. Browser geolocation requires HTTPS outside localhost. OpenStreetMap map tiles come from its public tile service and are subject to the OpenStreetMap tile usage policy.
- **Import from phone** uses the browser Contact Picker API when available; support varies by mobile browser and it requires HTTPS. As a fallback, export contacts from the phone as a `.vcf`/vCard file and use **Import .vcf file**. The page also allows manual entry and search.
- `/decision` is level 2; `/decision/info` is level 3 and returns to `/decision`.
- The dashboard provides **Choose a path**, **My contacts**, **Location map**, and **My profile** options.
- Unauthenticated page requests redirect to sign-in. Protected APIs return JSON `401` without performing the requested action.

## APIs

`GET /api/contacts`, `POST /api/contacts`, and `DELETE /api/contacts` manage the signed-in user's contacts. `DELETE /api/contacts/<id>` removes an individual contact. Every route requires authentication and scopes data to the Google account in the session.

Location sharing APIs also require a session and derive identities from it: `GET /api/location/status` returns the caller's opt-in, active-recipient count, and profile photo; `POST /api/location/sharing` enables or pauses updates; `GET /api/location/overview` returns pending requests, active grants, and locations shared with the caller; `POST /api/location/requests` requests a saved contact's location; `POST /api/location/requests/<id>/respond` accepts, declines, or cancels a pending request; `POST /api/location/updates` upserts the signed-in user's latest coordinates only if the owner opted in and an active grant exists; `DELETE /api/location/shares/<id>` revokes one grant; and `DELETE /api/location/shares` revokes all grants. Coordinates are validated server-side, and a location is disclosed only when an accepted request connects its owner and the viewer. Map markers use the Google profile photo (or initials if unavailable); there is no marker-selection API.

`POST /api/decision` fetches a fresh permutation from the ANU Quantum Random Number Generator and returns the chosen direction:

```json
{"go_right": true}
```

## Tests

Run the route, session-protection, and OAuth-flow tests with `./.venv/bin/python -m unittest discover -s tests -v`.

## Copilot restart hook

The workspace hook in `.github/hooks/restart-app.json` runs `.github/hooks/restart-app.sh` after agent tool actions. It tracks the Flask application, templates, static files, configuration, dependencies, and startup script; when they change, it restarts the local server using `.env`. Logs are written to `/tmp/flutu-server.log`.
