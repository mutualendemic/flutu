# Privacy policy

## Route and access

- `/privacy` is a public, localized page and does not require a session or acceptance of the site conditions.
- The public landing page links to the policy alongside the conditions shown before Google sign-in.
- The policy describes data categories, purposes and intended legal bases, recipients, international processing, retention, user rights, cookies, and security based on the current implementation.

## Disclosed processing

- Google OAuth supplies the stable account identifier, email, name, and optional profile photo. MongoDB Atlas stores user profiles and feature records, including contacts, sharing relationships, live locations, events, branching-chat content, and push subscriptions.
- Vercel hosts the application and Vercel Blob stores private event images. Supabase Realtime receives short-lived authorization tokens and channel identifiers for chat invalidation, not chat content. Resend sends configured invitations and event emails. IBM Quantum receives random-circuit jobs without account or chat content.
- OpenStreetMap tile services, unpkg browser assets, and browser push services receive requests from clients and may process technical data. People selected by users can receive invitations, event/chat information, or authorized live-location sharing.
- Live location sharing requires user action and browser permission. Location points are not a history and expire shortly after updates stop. The current application does not provide self-service account deletion; requests need controller handling.

## Publication prerequisite

The operator confirmed Flutu as its legal name and supplied `xntp006@gmail.com` as the privacy contact, and indicated generally that providers are configured in Europe. The postal address, exact country/region for each provider, and transfer documentation remain unverified. These limits are explicitly identified on the page; do not represent the policy as complete or GDPR-compliant until the controller verifies them, maps each processing purpose to an appropriate legal basis, and confirms provider agreements and safeguards.

## Related files

`app/main/routes.py`, `app/templates/privacy_policy.html`, `app/templates/landing.html`, and `tests/test_routes.py`.