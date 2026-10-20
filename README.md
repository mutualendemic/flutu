# Flutu

Flutu is a small Flask application with Google-only OAuth sign-in, a protected dashboard, a personal contacts list, and a quantum-random direction demo.

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

## SnapDeploy package

The repository includes a Dockerfile-based source package intended for container import services such as SnapDeploy. Build it locally with `python scripts/create_snapdeploy_zip.py`; the generated `dist/flutu-snapdeploy.zip` contains the Dockerfile, `.dockerignore`, `requirements.txt`, `run.py`, and the `app/` package at the ZIP root. It deliberately excludes `.env`, Git metadata, the local virtual environment, and tests. Configure Google OAuth credentials and a strong `FLASK_SECRET_KEY` in the deployment platform's environment settings; never put secrets in the ZIP.

When a GitHub Release is published, `.github/workflows/release-snapdeploy.yml` builds and attaches `flutu-snapdeploy-<tag>.zip` to that release. Download the attached ZIP and import it through SnapDeploy's container page. The image runs Gunicorn bound to `0.0.0.0` inside the container and honors the platform's `PORT`; the local development server remains bound to `127.0.0.1`.

### Google OAuth variables on SnapDeploy

In the SnapDeploy container's environment-variable settings, define:

| Variable | Value |
| --- | --- |
| `FLUTU_GOOGLE_CLIENT_ID` | Your Google OAuth client ID |
| `FLUTU_GOOGLE_CLIENT_SECRET` | Your Google OAuth client secret |
| `FLUTU_GOOGLE_REDIRECT_URI` | `https://<your-public-domain>/auth/google/callback` |
| `FLASK_SECRET_KEY` | A unique, long random secret |
| `FLASK_SESSION_COOKIE_SECURE` | `true` |

Replace `<your-public-domain>` with the HTTPS hostname assigned to your SnapDeploy container. Add that exact `FLUTU_GOOGLE_REDIRECT_URI` value to the OAuth client's authorized redirect URIs in Google Cloud Console. The callback route accepts both `/auth/google/callback` and `/auth/callback`; use the former consistently in the environment variable and Google Console. The application reads `FLUTU_GOOGLE_REDIRECT_URI` at startup and uses the same value for both the Google authorization request and token exchange. Do not store production values in the source ZIP or commit them.

The ZIP is a Docker build context, not a prebuilt image export. Confirm that SnapDeploy's importer accepts Dockerfile source ZIPs; the referenced example repository could not be fetched from this environment, so exact service-side ZIP constraints remain to be verified against SnapDeploy's current documentation. The expected context root is the five deployment inputs above, with `app/` as a directory; do not wrap them in an extra project folder inside the ZIP.

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
    quantum_random.py         ANU quantum-random integration
  templates/
    base.html                 Shared Jinja layout
    login.html                Google-only sign-in page
    dashboard.html            Authenticated root (level 1)
    contacts.html             Private contacts list with optional phone import (level 2)
    decision.html             Decision page (level 2)
    quantum_info.html          Decision information (level 3)
  static/
    logo.svg                  Shared static logo
tests/
  test_routes.py              Authentication, route, and session tests
  test_google_oauth.py         Google OAuth service tests
```

Routes are grouped by concern in Flask Blueprints and registered by `create_app()`. Templates extend `base.html`; integration and business logic live in dedicated modules, not in route handlers or templates. Google sign-in uses the OAuth 2.0 authorization-code flow with session-bound state validation and Google's userinfo endpoint.

## Authentication and page hierarchy

- Google OAuth login: `/auth/login`; callback: `/auth/callback` (the legacy `/auth/google/callback` remains supported); logout: `/auth/logout`.
- `/dashboard` is the authenticated root at level 1. Its child pages return to their immediate parent.
- `/contacts` is a level-2 page linked from the dashboard. Contacts are persisted in MongoDB and scoped to the signed-in Google account's stable `sub` identifier, making them available across devices. The server derives the owner from the authenticated session and never accepts an owner ID from the browser.
- **Import from phone** uses the browser Contact Picker API when available; support varies by mobile browser and it requires HTTPS. As a fallback, export contacts from the phone as a `.vcf`/vCard file and use **Import .vcf file**. The page also allows manual entry and search.
- `/decision` is level 2; `/decision/info` is level 3 and returns to `/decision`.
- The dashboard provides **Choose a path** and **My contacts** options.
- Unauthenticated page requests redirect to sign-in. Protected APIs return JSON `401` without performing the requested action.

## APIs

`GET /api/contacts`, `POST /api/contacts`, and `DELETE /api/contacts` manage the signed-in user's contacts. `DELETE /api/contacts/<id>` removes an individual contact. Every route requires authentication and scopes data to the Google account in the session.

`POST /api/decision` fetches a fresh permutation from the ANU Quantum Random Number Generator and returns the chosen direction:

```json
{"go_right": true}
```

## Tests

Run the route, session-protection, and OAuth-flow tests with `./.venv/bin/python -m unittest discover -s tests -v`.

## Copilot restart hook

The workspace hook in `.github/hooks/restart-app.json` runs `.github/hooks/restart-app.sh` after agent tool actions. It tracks the Flask application, templates, static files, configuration, dependencies, and startup script; when they change, it restarts the local server using `.env`. Logs are written to `/tmp/flutu-server.log`.
