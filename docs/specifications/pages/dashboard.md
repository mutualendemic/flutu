# Dashboard specification

## Route, access, and position

- `/dashboard` is a private level-1 page and the root of the authenticated area. Without a valid session, the request returns to sign-in.
- Displays the session user's name/email and a sign-out action.
- Links to level-2 pages: **Choose a path** (`/decision`), **My contacts** (`/contacts`), **Location map** (`/map`), and **My profile** (`/profile`). Private-page links are not shown before authentication.

## Sharing indicator

- The dashboard presents an accessible indicator updated by the global `location-sharing.js` script.
- States: sharing active with recipient count, permissions exist but updates are paused, no active sharing, or status unavailable.
- The indicator reports consent/opt-in state; by itself it does not confirm that a recent GPS reading succeeded.

## Related files

`app/main/routes.py` (`dashboard`), `app/templates/dashboard.html`, `app/templates/base.html`, `app/static/location-sharing.js`.
