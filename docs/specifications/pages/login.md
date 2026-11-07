# Sign-in and authentication specification

## Routes and state

- `/` renders a public capabilities landing page without a session and redirects signed-in users to `/dashboard`. Its sign-in button remains disabled until the user accepts the site conditions on that page.
- `/language/<locale>` stores one of the supported locales in the signed session and redirects to a validated same-site path. The selected locale is available before sign-in and survives OAuth callback session replacement and logout.
- `/auth/login` shows the site conditions before sign-in: Flutu.eu is an alpha project that may be shut down at any time; the project is not responsible for decisions made by following the quantum selector's instructions; and the site is not responsible for damages the user may incur from using it. Without OAuth configuration, it displays a message and returns 503.
- `/auth/accept-conditions` accepts a required form confirmation and records it in the session. `/auth/google/login` refuses to start OAuth until conditions are accepted, then starts OAuth with session-bound state. `/auth/google/callback` and `/auth/callback` also require the accepted conditions; missing/mismatched state, a Google error, a missing code, or validation failure returns to sign-in without authenticating.
- Identity is validated using Google's userinfo endpoint. On success, the callback replaces the session, marks it permanent, and stores `sub`, normalized email, name, and photo. When MongoDB is configured, it also updates the user profile for location sharing.
- `/auth/logout` clears the session and returns to sign-in.

## Interface and access

- Sign-in is public and requires accepting the site conditions before Google OAuth. The sign-in buttons on both the landing and login pages are disabled until the conditions checkbox is selected; the server also requires acceptance. There is no password login or fixed local user.
- The public landing page introduces branching conversations, consent-based location sharing, contacts, and optional activity notifications. It provides the conditions, Google sign-in, and the project link. This overview is not displayed on the authenticated dashboard.
- The site conditions link to the public `/privacy` page; opening the policy does not require accepting conditions or signing in. The policy's controller identity and privacy contact details remain a publication prerequisite.
- The landing page renders a local, dependency-free canvas particle animation inspired by the anti-gravity points effect in `https://codepen.io/ykob/pen/avEpdd`; no third-party frame or runtime is required. Particles drift upward, subtly react to pointer movement, and pause when the page is hidden. The canvas has a localized accessible label, honors reduced-motion preferences, and scales responsively.
- The shared header offers English (UK) and Portuguese (Portugal). English (UK) is the default when no explicit selection or supported browser preference is available. The translated catalog currently covers the landing page, sign-in page, and dashboard; remaining private pages/messages are not yet fully translated.
- The visible site brand is `flutu.eu`; the existing logo and build-version display are retained.
- The GitHub link in the interface points to `https://github.com/mutualendemic/flutu`, opens in a new tab, and uses `rel="noopener noreferrer"`.
- The page shows the version as a short commit hash. In deployment, it uses `FLUTU_BUILD_COMMIT`, `VERCEL_GIT_COMMIT_SHA`, `GITHUB_SHA`, or `SOURCE_VERSION` (in that order); in development, it tries `git rev-parse`; if unavailable, it displays `unknown`.
- Private routes are protected on the server by the `login_required` decorator; see the cross-cutting [architecture specification](../architecture.md).

## Related files

`app/auth/routes.py`, `app/auth/decorators.py`, `app/services/google_oauth.py`, `app/templates/login.html`, `app/__init__.py`.
