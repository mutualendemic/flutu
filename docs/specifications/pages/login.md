# Sign-in and authentication specification

## Routes and state

- `/` renders a public capabilities landing page without a session and redirects signed-in users to `/dashboard`.
- `/language/<locale>` stores one of the supported locales in the signed session and redirects to a validated same-site path. The selected locale is available before sign-in and survives OAuth callback session replacement and logout.
- `/auth/login` shows the public Google sign-in page when credentials are configured; without configuration, it displays a message and returns 503.
- `/auth/google/login` starts OAuth with session-bound state. `/auth/google/callback` and `/auth/callback` process the response; missing/mismatched state, a Google error, a missing code, or validation failure returns to sign-in without authenticating.
- Identity is validated using Google's userinfo endpoint. On success, the callback replaces the session, marks it permanent, and stores `sub`, normalized email, name, and photo. When MongoDB is configured, it also updates the user profile for location sharing.
- `/auth/logout` clears the session and returns to sign-in.

## Interface and access

- Sign-in is public. There is no password login or fixed local user.
- The public landing page introduces branching conversations, consent-based location sharing, contacts, and optional activity notifications. It provides Google sign-in and the project link. This overview is not displayed on the authenticated dashboard.
- The shared header offers English (UK) and Portuguese (Portugal). English (UK) is the default when no explicit selection or supported browser preference is available. The translated catalog currently covers the landing page, sign-in page, and dashboard; remaining private pages/messages are not yet fully translated.
- The visible site brand is `ux9.eu`; the existing logo and build-version display are retained.
- The GitHub link in the interface points to `https://github.com/mutualendemic/flutu`, opens in a new tab, and uses `rel="noopener noreferrer"`.
- The page shows the version as a short commit hash. In deployment, it uses `FLUTU_BUILD_COMMIT`, `VERCEL_GIT_COMMIT_SHA`, `GITHUB_SHA`, or `SOURCE_VERSION` (in that order); in development, it tries `git rev-parse`; if unavailable, it displays `unknown`.
- Private routes are protected on the server by the `login_required` decorator; see the cross-cutting [architecture specification](../architecture.md).

## Related files

`app/auth/routes.py`, `app/auth/decorators.py`, `app/services/google_oauth.py`, `app/templates/login.html`, `app/__init__.py`.
