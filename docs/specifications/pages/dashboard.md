# Dashboard specification

## Route, access, and position

- `/dashboard` is a private level-1 page and the root of the authenticated area. Without a valid session, the request returns to sign-in.
- Displays the session user's name/email and a sign-out action.
- Links to level-2 pages: **Quantum path selector** (`/decision`), **My contacts** (`/contacts`), **Location map** (`/map`), and **My profile** (`/profile`). Private-page links are not shown before authentication.

## Sharing indicator

- The dashboard presents an accessible indicator updated by the global `location-sharing.js` script.
- States: sharing active with recipient count, permissions exist but updates are paused, no active sharing, or status unavailable.
- The indicator reports consent/opt-in state; by itself it does not confirm that a recent GPS reading succeeded.

## Web Push opt-in

- The dashboard provides an accessible device-level control to enable or disable Web Push. The browser permission prompt is requested only after the user activates the control; page load may inspect an existing permission/subscription but never prompts.
- Subscriptions are associated server-side with the authenticated Google `sub`. Push targets and eligible actions follow the shared policy in [architecture.md](../architecture.md); the dashboard UI receives only the VAPID public key, never the private key.
- The interface reports unsupported browsers, blocked permission, active subscription, and failures. Disabling removes this device's server-side subscription and browser subscription.

## Related files

`app/main/routes.py` (`dashboard` and push APIs), `app/templates/dashboard.html`, `app/templates/base.html`, `app/static/location-sharing.js`, `app/static/push-notifications.js`, and `app/static/sw.js`.
