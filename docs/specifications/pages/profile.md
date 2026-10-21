# Profile specification

## Route, access, and navigation

- `/profile` is a private level-2 page and appears as **My profile** on the dashboard. It returns to the dashboard.
- The page displays the name and email from the authenticated Google session.

## Profile photo on the map

- There is no marker selection option. The photo from the authenticated Google profile represents the user on the map; when unavailable or unable to load, the user's initials are displayed.
- The page continues to show the name and email associated with the session and explains how the photo is used on the map.
- The photo is included in location data only for relationships with accepted consent; it is not shared with unauthorized users.

## Related files

`app/main/routes.py`, `app/services/location_sharing.py`, `app/templates/profile.html`, `app/templates/dashboard.html`, `app/templates/location_map.html`.
