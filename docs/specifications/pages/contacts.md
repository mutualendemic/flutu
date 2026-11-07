# Contacts specification

## Route and access

- `/contacts` is a private level-2 page linked from the dashboard and includes a link back to the dashboard.
- Related APIs: `GET /api/contacts`, `POST /api/contacts`, `DELETE /api/contacts`, `DELETE /api/contacts/<contact_id>`, `GET /api/contact-invitations/contexts`, and `POST /api/contact-invitations`. All require a session and use `session.user.sub` as the owner; invitation sends also require a Contacts-page CSRF token and same-origin request.

## Current behavior

- The persisted list is specific to the Google account and is available across sessions/devices when MongoDB is configured.
- The contact list uses the shared contact renderer and shows a profile photo or initials, name, email when available, and whether the email matches a registered Flutu.eu account. Contacts are sorted alphabetically by name using the page locale. The same renderer and ordering are used by contact selectors throughout the application.
- Users can add contacts manually, search, delete an individual contact, and clear all contacts. Removing a contact and clearing the list require explicit confirmation.
- Contacts can be imported with Contact Picker when supported by the browser and secure context. Alternatively, a `.vcf` file up to 5 MiB can be read and parsed locally, with each server request limited to 100 records.
- For a saved contact with an email address, users can open their email app with a prefilled invitation. For a contact with a phone number, they can open their messaging app with the invitation text prepared. A separate message action lets users customize text, choose email or Push for registered accounts, and optionally attach an owned event or branching chat. Contacts without a Flutu account can receive the customized message only by email.
- Contextual invitations grant access only through existing server-side rules: event invitations are pending viewer memberships, chat additions use the conversation owner's existing membership flow, and external contacts remain email-only guests without account access. A message without context does not modify memberships. See [Contact invitation flow](../contact-invitations.md).
- All external invitation links lead to `/auth/login`, which continues to enforce Google sign-in. No invitation-specific signup bypass is introduced.
- Accepted fields: required name (up to 120 characters), optional phone (up to 80), and optional email (up to 254); at least a phone or email must be provided. The API returns 400 for invalid payloads and 503 when MongoDB is unavailable.
- Import deduplication compares lowercase email and phone without spaces against contacts already loaded on the page. Persistence does not enforce global contact uniqueness.

## Related files

`app/main/routes.py`, `app/services/contacts.py`, `app/templates/contacts.html`.
