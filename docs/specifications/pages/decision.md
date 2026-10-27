# Direction choice specification

## Route and access

- `/decision` is a private level-2 page linked from the dashboard and returns to the dashboard.
- `POST /api/decision` requires a session. The route invokes IBM Quantum hardware; missing credentials, hardware/job errors, or invalid results return JSON 502.

## Behavior

- The interface provides a “Choose for me” button. Each click makes a new request; the control is disabled while the request is pending and then displays the result or an error.
- The server submits a one-qubit Hadamard-and-measure circuit to the least-busy operational IBM Quantum backend using the Sampler primitive. The measured bit indicates left/right; the result is neither displayed as a bit nor persisted.
- IBM Quantum credentials are supplied through `IBM_QUANTUM_API_KEY`; `IBM_QUANTUM_INSTANCE` may optionally select an instance. The page links to IBM's hardware guide and to `/decision/info`.

## Related files

`app/main/routes.py`, `app/services/quantum_random.py`, `app/templates/decision.html`.
