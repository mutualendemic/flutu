# Contacts specification

## Route and access

- `/contacts` is a private level-2 page linked from the dashboard and includes a link back to the dashboard.
- Related APIs: `GET /api/contacts`, `POST /api/contacts`, `DELETE /api/contacts`, `DELETE /api/contacts/<contact_id>`. All require a session and use `session.user.sub` as the owner.

## Current behavior

- The persisted list is specific to the Google account and is available across sessions/devices when MongoDB is configured.
- Users can add contacts manually, search, delete an individual contact, and clear all contacts.
- Contacts can be imported with Contact Picker when supported by the browser and secure context. Alternatively, a `.vcf` file up to 5 MiB can be read and parsed locally, with each server request limited to 100 records.
- For a saved contact with an email address, users can open their email app with a prefilled invitation. For a contact with a phone number, they can open their messaging app with the invitation text prepared. Users review and send the message themselves; Flutu does not send or persist invitations.
- Invitation messages link to `/auth/login`, where a friend can continue with the supported Google sign-in flow. The contacts page remains session-protected; no invitation-specific API or signup bypass is introduced.
- Accepted fields: required name (up to 120 characters), optional phone (up to 80), and optional email (up to 254); at least a phone or email must be provided. The API returns 400 for invalid payloads and 503 when MongoDB is unavailable.
- Import deduplication compares lowercase email and phone without spaces against contacts already loaded on the page. Persistence does not enforce global contact uniqueness.

## Related files

`app/main/routes.py`, `app/services/contacts.py`, `app/templates/contacts.html`.
