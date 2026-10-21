# Copilot project instructions

## Authentication is required

- All new private pages and features must require the project's standard authentication.
- Enforce access on the server for every route; hiding links or protecting a page only in the frontend is not sufficient.
- If there is no valid session, redirect HTML pages to `/` (sign-in). APIs must return JSON `401` responses without performing the protected action.
- Links to private pages should only appear after sign-in, on the dashboard or on the page that is their parent.

## Page hierarchy and navigation

- The dashboard (`/dashboard`) is the root of the authenticated area and is level 1.
- Pages linked directly from the dashboard are level 2 and must provide navigation back to the dashboard.
- Pages linked from a level 2 page are level 3 and must return to the level 2 page that opened them. Continue this pattern at every level: each page returns to its immediate parent, never automatically to sign-in or the root, except when the current page is the dashboard.
- Add new pages to their parent's navigation and register their server routes so the hierarchy stays visible and predictable.
- When creating a page, identify its parent, add a “Back” link to that parent, and protect the server route with the standard session authentication.

## Keep documentation up to date

- Write all project documentation in English, including README files, implementation specifications, guides, comments intended as documentation, and other Markdown or text documentation. When updating existing documentation, translate any non-English content in the affected document so the file remains entirely in English.
- Update the relevant documentation whenever a meaningful code change changes user-visible behavior, routes, APIs, authentication, configuration, setup, or operating procedures.
- Keep `README.md` accurate for changes affecting how the project is installed, configured, run, or used. Update other relevant docs when a change is specific to a feature or API.
- Make documentation updates in the same change as the implementation, and verify examples, URLs, and instructions against the current code. Do not make unrelated documentation-only edits for changes that do not affect documented behavior.
- Maintain the implementation specifications under `docs/specifications/` as the authoritative record of current decisions. Every user-facing page must have its own up-to-date page specification in `docs/specifications/pages/`; cross-page decisions belong in `docs/specifications/architecture.md`. Update these specifications in the same change as any behavior or design decision, and describe the current implementation rather than an aspirational design.
- Keep `docs/specifications/README.md` as the index of all pages/routes and link every page specification from it. If a new page is added, add its spec and index entry together with its route, template, tests, and navigation.

## Application architecture (Flask)

- Use the Flask application factory in `app/__init__.py` to configure and create the app. Do not instantiate a global app in feature modules or import the app object directly; this avoids circular imports and keeps tests configurable.
- Keep the entry point in `run.py` and configuration in `app/config.py`. Add `app/extensions.py` only when the project uses shared Flask extension instances that need centralized initialization.
- Bind the local development server to `127.0.0.1` only. Do not expose it on `0.0.0.0` or another network interface unless explicitly requested.
- For container deployment, the production WSGI server must listen on `0.0.0.0` inside the container and honor the platform-provided `PORT`; do not change the local development server's loopback-only binding.
- Group routes by responsibility in Python packages and register each feature's Blueprint in the application factory. Authentication and OAuth belong in `app/auth/`; general pages and HTTP endpoints belong in `app/main/`.
- Put reusable business logic and external integrations in `app/services/`, separated by concern. Route functions should validate HTTP input, call a service, and return a response; do not put provider integration or business logic in `server.py` or templates.
- All HTML must be Jinja templates under `app/templates/`. Extend `base.html`, use `url_for()` for internal URLs and static assets, and do not add standalone root-level HTML pages.
- Put browser assets in `app/static/`. Keep secrets in environment variables or `.env`; never commit credentials.
- Google OAuth is the only supported sign-in method. Do not add local email/password login or hard-coded users. Preserve OAuth state validation and validate the user's identity with Google's trusted userinfo endpoint. Protect private HTML routes on the server and return JSON `401` responses from protected APIs when there is no valid session.
- Read the Google OAuth callback URL from the `FLUTU_GOOGLE_REDIRECT_URI` environment variable. Keep local defaults for development, document the exact production callback URL, and use the same value in both the authorization request and code exchange. Never hard-code a deployment hostname or commit OAuth credentials.
- New routes/pages must follow the existing parent/child navigation hierarchy above, be registered in a Blueprint, have tests, and update relevant documentation.
