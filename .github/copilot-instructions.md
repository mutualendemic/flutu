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
- For user-facing copy, use gettext in Jinja/Python and `window.FlutuI18n` in browser scripts. Add every literal browser `t()` key to `app/i18n.py` and update `app/translations/pt/LC_MESSAGES/messages.po` plus its compiled catalog in the same change. Do not leave visible text, titles, placeholders, accessibility labels, or dynamic errors hard-coded in English. Keep API error contracts language-neutral, but map machine-readable error codes to localized user-facing messages; never display raw codes as UI copy.

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

## Credential safety and incident response

- Never print, quote, summarize, copy, or otherwise expose secret values in chat responses, code, diffs, logs, test output, screenshots, documentation, generated artifacts, or commit messages. This includes OAuth secrets, API tokens, cookies, private keys, database connection strings, and credentials from environment or local files.
- Do not inspect or read `.env`, `.env.*` (except `.env.example`), `credentials-local`, private key files, or deployment credential stores unless the user explicitly asks for a safe, specific operation that requires it. Never echo values from these files. If a user supplies secrets in context, treat them as compromised and do not repeat or incorporate them into changes.
- Do not request secrets in chat. For local setup, tell the user to enter secrets directly into an ignored local environment file or secret manager. Use only obviously fake placeholders in examples and tests.
- Keep secrets out of application logs and errors. Do not log request headers, cookies, authorization codes, tokens, full environment/configuration objects, or URLs containing credentials. Redact sensitive values before returning command output or diagnostic details.
- Ensure local secret files remain ignored, but remember `.gitignore` does not untrack files already committed. Before any commit, review changed and staged filenames and scan the diff for accidental secrets without printing their values. Never stage credential files or artifacts.
- If a secret appears in chat, source control, logs, tests, or an artifact, do not repeat it. Advise immediate revocation/rotation, update dependent deployment settings, and assess exposure locations. Removing a value or rewriting Git history does not make the credential safe; rotation is required. Do not perform destructive history rewriting unless explicitly requested.
