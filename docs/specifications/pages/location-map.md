# Map and location-sharing specification

## Route and interface

- `/map` is a private level-2 page linked from the dashboard and provides a link back to the dashboard.
- Markers use the owner's Google profile photo. The current user's marker uses the session photo or the photo from authenticated status; other people's photos are included only in locations returned through an accepted sharing relationship. Missing or non-loading HTTPS URLs fall back to initials. If the latest Google userinfo response has no photo, a previously saved photo is not deleted.
- In “People you share with” and remote-marker popups, the page shows approximate distance when both the user's and the other person's coordinates are recent (up to 120 seconds). Haversine distance is calculated in the browser and requires that the other person has also shared their location with the user. Messages distinguish a missing recent own position from the other person not sharing their location with the viewer; the page does not obtain or infer a location without consent.
- The controls to enable/pause updates and stop all sharing are disabled and visually dimmed when there are no accepted sharing permissions.
- The map uses Leaflet and OpenStreetMap tiles and displays the latest points shared with the current user. Each time a participant's location changes, the map recenters and adjusts its bounds to include all visible participant markers, including the current user's marker. When the map opens, it requests the device's own location and updates a local blue marker every 30 seconds, even without accepted shares. A button allows retry after an error/permission denial. In private mode, the own point is not sent to or saved on the server. If the user enables sharing, their marker reflects the latest point updated on the server, which is delivered only to authorized recipients.
- The page lists incoming requests, outgoing pending requests, and people who authorized sharing with the user. It allows requesting a location from a contact with an email address, accepting/declining/canceling requests, revoking one permission, or revoking all permissions.

## Flow and consent

1. The sender selects a saved contact. The server confirms that the contact belongs to the authenticated account and resolves its account using the normalized email in the Flutu directory.
2. If that account has signed in with Google, the server creates a `pending` request identified by Google account IDs (`sub`). Requests are in-app; no email or push notification is sent.
3. The recipient decides whether to accept or decline. Accepting adds the requester to the recipient's contact list if that email is not already present.
4. The location owner separately decides whether to enable updates. Without at least one accepted incoming request, the button is disabled; the interface explains that a contact must request the location first. On enable, the page requests the position immediately in the direct context of the user action to trigger the browser's native permission prompt (there is no separate Flutu authorization page); only after obtaining a position does it save opt-in and send the first point. If the browser already has a saved decision, it does not show another prompt and follows that decision. Opt-in is persisted in the profile and can be paused on the page. Messages distinguish a non-HTTPS context, denied permission, unavailable GPS, and timeout.
5. On the map, the device's own location is obtained immediately and then about every 30 seconds to display only the own marker; a hidden-page event suspends reads, and returning to the foreground requests a new read. These private reads are not saved on the server. If sharing is enabled and there is at least one accepted recipient, `location-sharing.js` also sends updates (about every 30 seconds) from any visible authenticated route. A closed page sends no updates.

## Storage and access

- Each update upserts the GeoJSON point, accuracy, Google photo, and timestamp in one document with a unique `owner_id`. No history is kept. Timestamps are returned with an explicit UTC timezone to validate freshness regardless of the device timezone.
- The overview API returns a location only to the requester in an `accepted` relationship; data at least 120 seconds old is omitted. MongoDB TTL removes points after 180 seconds of inactivity. Pausing opt-in or revoking the last grant deletes the point immediately.
- Revoking an individual grant leaves other accepted grants active. Removing the last grant disables opt-in and removes the point.
- Private API routes: `GET /api/location/overview`, `GET /api/location/status`, `POST /api/location/sharing`, `POST /api/location/requests`, `POST /api/location/requests/<id>/respond`, `POST /api/location/updates`, `DELETE /api/location/shares`, `DELETE /api/location/shares/<id>`. Validation, scope, and rules are in the [architecture specification](../architecture.md).
- Location is sensitive. Use depends on explicit consent, browser GPS permission, and an HTTPS context outside localhost. GPS errors from the global updater appear on the map page and in the dashboard sharing indicator. Do not use these data as a track/history.

## Related files

`app/main/routes.py`, `app/services/location_sharing.py`, `app/static/location-sharing.js`, `app/templates/location_map.html`, `app/templates/base.html`.
