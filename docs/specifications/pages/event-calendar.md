# Event calendar specification

## Route and access

- `/calendar` is a private level-2 page linked from `/dashboard`; its Back link returns to the dashboard.
- All calendar APIs require the standard authenticated Google session. Mutations also require the calendar session CSRF token and same-origin validation. The server derives `owner_id` from the session and scopes all event reads and writes to that owner.
- The owner and event members can access an event. Pending members can view the invitation and respond; accepted viewers can read event details; accepted editors can update the event. Declined members and linked conversation members cannot access it. Only the owner can delete an event or see its pins in the location-map layer. Selecting a contact linked to a Flutu account as a guest also creates a pending viewer membership, which appears in the invitee's acceptance panel. Unlinked guests remain email-only contacts without event access; when they have an email address, they receive best-effort email notices on event creation and changed saves if Resend is configured.

## Event model and calendar view

- An event has a title (required, up to 160 characters) and optional description (up to 5,000 characters). Status is derived from all date entries and is not editable or authoritative in storage: it is `open` if any occurrence is in progress or in the future, and `closed` only when every occurrence has ended. A recurring date keeps the event open while another occurrence remains. Legacy stored values are ignored. The status continues to appear in the calendar and event details.
- Each event has 1–50 date entries. Each entry has a timezone-aware start and end; end must follow start and a single occurrence cannot exceed 31 days.
- A date entry can optionally repeat daily, weekly, monthly, or yearly. Weekly rules can select one or more weekdays; when omitted, the start weekday is used. The interval is 1–30, the end date is required, the horizon is at most ten years, and each rule may produce at most 500 occurrences.
- The month view requests a bounded range of up to 62 days. Recurrences are expanded by `python-dateutil` on the server. The stored timestamps are UTC; display and edit inputs use the browser's local timezone.
- The month view uses FullCalendar 7.1.4's native toolbar and automatic height, with the official Monarch theme and blue palette mapped to the site's shared light/dark surface, text, border, and accent tokens. Its locale follows the language selected on the site. The calendar spans the page width, with a second FullCalendar `timeGridDay` view below it for the selected date. Selecting a date in the month view changes the day view; selecting an occurrence opens its event details. The event detail header uses three columns: a cover image on the left, a colored title that expands into the available space, and the status aligned to the right. The title and status fill the image height and grow with it when the title wraps. Events without a cover use a solid event-color placeholder. The detail view also has a dedicated Dates and times section with start and end values for each date entry, separated information sections, and an embedded Leaflet map of the event's map points. The day view scrolls to 10:00 for other dates and to the current local time when showing today. Each event receives a stable blue shade derived from its ID, shared across both calendar views and all recurrence instances; closed events use a muted blue variant. The title and status text use a foreground color chosen for contrast. All occurrences are displayed in their day cells.
- Calendar links containing an owned event ID and occurrence date select that month and date, open the event details, and scroll them into view. This is used by private event pins on the location map.
- Users can create, edit, and delete their own events. Editing preserves previously stored custom pin images unless the point is removed or replaced.
- The owner can invite account-linked contacts as `viewer` or `editor`; selecting an account-linked contact as a guest automatically adds a `viewer` invitation unless the owner explicitly assigns another role in the member selector. Contact and member lists are sorted alphabetically by name using the page locale. The UI displays each person's name and email and the member's role/invitation state. New invitations are `pending`; the server ignores client-supplied acceptance status. Pending invitations appear in the invitee's calendar with accept/decline actions. An accepted editor can update event content and map points but cannot delete the event or manage its members, guests, or conversations; viewers have no mutation controls. Creation and changed saves notify other accepted members by opted-in Web Push and optional best-effort email. New invitations notify the new member; unchanged saves and pending invitations are not resent.

## Contacts, conversations, and map points

- Guests are selected from the current user's saved Contacts. The API validates each contact ID against the authenticated owner's contact records.
- Conversations are selected from the existing branching-chat list. The API validates active membership through `app.services.chat.is_active_member`; inaccessible or deleted conversations cannot be attached. Calendar detail links open the existing conversation page.
- An event may contain up to 20 map points. Each point has a label, latitude, longitude, and optional custom pin image. When editing an event, existing pins are restored on the editor map and the map fits them into view. The editor supports map selection, place/address search through Nominatim, and editing or removing existing pins.
- Source images must be PNG/JPEG/WebP under 10 MiB. Pin images are resized to at most 256×256 px and compressed to no larger than 24 KiB. Optional event cover images are resized and compressed to no larger than 64 KiB and displayed in the event detail. The server enforces both limits. With 20 pins and a cover, custom image storage is capped at 544 KiB per event. Images are uploaded to a **private** Vercel Blob store. The browser receives only same-origin authenticated image URLs. Image routes check event ownership and return `Cache-Control: private, no-cache` plus `X-Content-Type-Options: nosniff`.
- The `/map` page has an opt-in “Show open events” toggle, off by default. When enabled it displays the owner's event pins whose date-derived status is `open` from `GET /calendar/api/map-points?status=open` in a dedicated layer, separate from consent-based location-sharing markers. Event pins in this layer remain private to their owner and do not depend on GPS sharing permission. Accepted event members can view event locations only within the authenticated event detail. Popups link back to the calendar.

## API

- `GET /calendar/api/events` lists events owned by the current user and events for which the current user has a pending or accepted membership.
- `GET /calendar/api/event-members` lists account-linked contacts available to invite, including name and email.
- `POST /calendar/api/events` creates an event.
- `PATCH /calendar/api/events/<event_id>` updates an event owned by the current user or an event for which the current user is an accepted editor. Editors cannot change membership, contact guests, or conversation associations.
- `POST /calendar/api/events/<event_id>/invitation` accepts or declines a pending invitation for the authenticated account.
- `DELETE /calendar/api/events/<event_id>` deletes an event and best-effort removes its private pin and cover images.
- `GET /calendar/api/occurrences?from=<ISO>&to=<ISO>` returns expanded occurrences within a maximum 62-day range.
- `GET /calendar/api/map-points` lists the owner's event locations; `status=open` filters to open events for the map toggle.
- `GET /calendar/api/location-search?q=<query>` returns up to five normalized place results and is rate-limited to one request per second per process.
- `GET /calendar/api/events/<event_id>/images/<image_id>` serves an image only after session and event-access checks.
- `GET /calendar/api/events/<event_id>/cover-image` serves the private event cover only after session and event-access checks.
- Validation errors use language-neutral codes; the browser maps them to localized messages. MongoDB or Blob unavailability returns HTTP 503 without exposing provider credentials or private paths.

## Storage and operations

- Event metadata and private Blob pathnames for pins and covers are stored in MongoDB collection `calendar_events`; image bytes are not embedded in MongoDB.
- Deployment requires a private Vercel Blob store connected to the Vercel project. Configure the store's Vercel read/write token as `BLOB_READ_WRITE_TOKEN` for local uploads in ignored `.env`. Calendar events without custom images do not require Blob credentials.
- The SDK dependency is `vercel-blob>=0.5.0,<1`; the recurrence dependency is `python-dateutil>=2.9,<3`.

## Related files

`app/calendar/`, `app/services/events.py`, `app/services/blob_storage.py`, `app/templates/calendar.html`, `app/static/calendar.js`, `app/templates/location_map.html`, and `tests/test_events.py`.