# Contact invitation flow

This specification describes customized communications sent from the Contacts page. It is cross-cutting because it can grant access to events and branching chats.

## Entry points and access

- The Contacts page offers a message action beside the existing email and SMS invitation actions for each saved contact with an email address.
- `GET /api/contact-invitations/contexts` requires a signed-in session and returns only events the caller owns and chats the caller owns.
- `POST /api/contact-invitations` requires a signed-in session, same-origin validation, and the Contacts-page CSRF token. The contact, account, event, chat, and sender identity are resolved on the server; request data cannot assert ownership or recipients.
- The message is required and limited to 1,000 characters for email and 180 characters for Web Push. Context is optional and is selected as either an owned event or an owned branching chat.

## Delivery channels

- A saved contact with an email address matching a Flutu account can receive either Web Push or email. Push requires an active registered subscription; email requires Resend configuration.
- A contact without a Flutu account can only receive email. The email contains the sender's custom message and links to the Google sign-in flow. The application does not create an account or bypass authentication.
- The recipient's email address is the address stored on the sender-owned contact. Email bodies escape user-supplied names and messages; delivery credentials remain server-side.
- Web Push uses the shared `notify_users()` service, a same-origin path, the registered account ID, and the user's custom message. Push delivery is best-effort; the response reports when delivery did not occur.
- If no event or chat is selected, sending a message does not modify memberships or guest lists.

## Context and membership

- Selecting an event for a registered contact creates a pending viewer invitation if the person is not already a pending or accepted member. Selecting an event for an external contact adds the sender-owned contact as an event guest. Only the event owner may select that event.
- Selecting a branching chat for a registered contact adds them using the existing owner-only `add_members()` rule. Existing membership is not duplicated. Only a conversation owner may select that chat.
- Selecting a chat for an external contact sends the custom email with a sign-in link but does not add a chat member or grant access. The sender must add the person after they have a Flutu account.
- A selected event or chat is included in the notification/email destination only after the server verifies the sender's ownership and applies the membership/guest rule above.
- Email delivery failure does not roll back membership already applied. Retrying is idempotent for event memberships, event guest contacts, and chat membership.

## Removal confirmations

- Deleting a saved contact, removing a chat member, revoking an individual location-sharing grant, clearing all contacts, deleting an event, deleting a conversation, revoking all location grants, and disabling a device's Push subscription require a localized confirmation before the persisted change.
- Removing dates, map points, or images from an unsaved editor draft does not require an additional confirmation; the user commits those edits through the form's Save action.
- Confirmation is a UI safeguard only. Every API still enforces authentication, ownership, CSRF where required, and authorization on the server.