# Direction choice specification

## Route and access

- `/decision` is a private level-2 page linked from the dashboard and returns to the dashboard.
- `POST /api/decision` requires a session. The route invokes the ANU service; external failures or invalid formats return JSON 502.

## Behavior

- The interface provides a “Choose for me” button. Each click makes a new request; the control is disabled while the request is pending and then displays the result or an error.
- The server queries ANU's random permutation generator and interprets the final value in the permutation of 1 and 2 to indicate left/right. The permutation is neither displayed nor persisted.
- The page includes an external link to the ANU source and a child link to `/decision/info`.

## Related files

`app/main/routes.py`, `app/services/quantum_random.py`, `app/templates/decision.html`.
