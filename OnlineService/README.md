# Trong Dung Studio · V50 License Server + Admin

This extends the Build49 FastAPI AI service with **server-authoritative license keys**, a private web Admin, device slots and **access IP logs**. It does **not** process or upload MOD archives. A signed IPA alone will not deploy the server.

## Architecture

```text
User's iPhone: key input → POST HTTPS /v1/license/activate → FastAPI → persistent PostgreSQL
               saved 30-day opaque session token → POST /v1/license/verify on every app launch / return from background
Owner's browser: /admin → Bearer LICENSE_ADMIN_TOKEN → create / rotate / revoke / delete licenses and inspect access logs
```

The server stores **SHA-256 hashes** of randomly generated, high-entropy keys and session tokens. Full keys are returned **once** at creation/rotation, not retrievable from the DB. The iPhone stores only its own opaque session and an app-specific random UUID in the **Keychain**, not an Admin credential, and does not store a device hardware identifier. Key revocation takes effect at the app's next online verification; it cannot undo functionality in a previously patched/compromised client. No offline bypass is enabled: when the service is unavailable, the app remains locked until it can verify.

## Deployment (Render + persistent Postgres)

1. Push the source directory to your GitHub repository. In Render, deploy the `OnlineService` directory as a Python web service, or create a Render Blueprint based on `OnlineService/render.yaml`. The repo root should remain the repository root; choose `OnlineService` as the service **Root Directory** if configuring manually. The provided `render.yaml` is located inside `OnlineService` and should be selected explicitly when creating the Blueprint.
2. Provision a persistent PostgreSQL database (Render Postgres or another managed Postgres). Put its **private** connection URI in `DATABASE_URL`. Both `postgres://` and `postgresql://` are supported; SQLAlchemy adapts the URI to psycopg. Keep credentials in Render environment settings, never in Git.
3. Set `APP_ENV=production`, `LICENSE_ADMIN_TOKEN` to a unique cryptographically random secret of at least **32 characters**, and `ACCESS_LOG_RETENTION_DAYS=30` (1–90 supported). The Blueprint can generate the Admin secret automatically. Store your Admin token in a trusted password manager; never include it in an IPA or share it with users.
4. The already-present AI advisor needs `OPENAI_API_KEY` and `AOV_CLIENT_TOKEN` only if AI is used. Licensing works without an AI API key. Verify `https://your-service.onrender.com/v1/license/status` returns `"ready": true` and `/health` returns OK.
5. Visit `https://your-service.onrender.com/admin` in your own browser, paste `LICENSE_ADMIN_TOKEN`, then create licenses. This Admin UI keeps your token in **page memory only**: closing the tab clears it. Treat the Admin URL and Admin token as private. Do not provide the token to license users.
6. Under GitHub repository **Settings → Secrets and variables → Actions → Variables**, set `AOV_LICENSE_SERVER_URL=https://your-service.onrender.com` (HTTPS origin, with no trailing path). Then run the iOS workflow. **Without this variable the build stops** rather than publishing a locked, misconfigured IPA. When using Xcode locally, pass the build setting `AOV_LICENSE_SERVER_URL` yourself. This is a public server URL, not a secret; do not put Admin token here.
7. Install and **sign** the IPA as required by your iOS distribution method. The GitHub workflow produces an **unsigned** IPA; it does not host the service or provision the database automatically.

If you manually start the backend from the root directory for local development:

```bash
cd OnlineService
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL='sqlite:///./license-dev.sqlite3'  # DEV ONLY, not production
export LICENSE_ADMIN_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(42))')"
uvicorn app:app --host 127.0.0.1 --port 8000
```

SQLite is for local development/test only. The server intentionally refuses SQLite when `APP_ENV=production` to prevent license loss on ephemeral web-service instances. An HTTPS reverse proxy, database backups, and appropriate access controls are essential before public launch.

## License endpoints and Admin behavior

- `GET /v1/license/status`: readiness, log retention configuration.
- `POST /v1/license/activate`: `{ "license_key":"TD-...", "device_id":"<random UUID>", "privacy_notice_accepted":true }` → opaque `session_token`, expiry and display label.
- `POST /v1/license/verify`: `{ "session_token":"...", "device_id":"<same UUID>" }` → valid state; 401 when revoked, expired, missing or mismatched.
- `POST /v1/license/logout`: revokes a session token.
- `GET /v1/admin/keys`: list key metadata (never plaintext).
- `POST /v1/admin/keys`: `{"label":"Tester 01","valid_days":30,"max_devices":1}`. Returns a plaintext `key_once` only this time.
- `POST /v1/admin/keys/{uuid}/rotate`: `{"reset_devices":true}` creates a new key and invalidates existing sessions; optionally frees old device slots.
- `POST /v1/admin/keys/{uuid}/revoke` / `restore`: withdraw or reinstate a key.
- `DELETE /v1/admin/keys/{uuid}`: permanently remove key and active sessions.
- `GET /v1/admin/keys/{uuid}/devices` and `DELETE .../devices/{device_uuid}`: inspect and unbind device slots.
- `GET /v1/admin/logs?limit=200`: login history, including IP and UTC timestamp; `DELETE /v1/admin/logs` clears it.

All Admin API requests require `Authorization: Bearer LICENSE_ADMIN_TOKEN`. Keys may be assigned to at most 20 devices; the default is 1. A license can last 1–3650 days; passing `valid_days: null` creates a nonexpiring license. A temporary session lasts 30 days; reenter key to renew. Replacing a key invalidates old session tokens immediately on server.

## IP logging, user notice, and retention

IP addresses are personal data in many contexts. The key activation view **discloses collection** and requires the user to acknowledge the notice. Only license activation and verification create an audit record: UTC time, public-facing IP as available to the server, event type, allow/deny and anonymized device hash prefix. No GPS, contact data, or file contents are transmitted. The database removes events after the configured retention period when license endpoints or log listing next run; use a scheduled database cleanup task if strict wall-clock deletion is needed. Admin may delete logs immediately.

**Proxy trust:** The backend uses the ASGI peer IP by default, and **never blindly trusts** caller-supplied `X-Forwarded-For` headers. To enable accurate IP resolution only behind an ingress you control, set `TRUSTED_PROXY_CIDRS` to comma-separated CIDR blocks of **verified** proxy hop ranges; the backend then walks the header chain from the right and rejects malformed chains. Leaving it empty is safe and may show an ingress IP. Behind Render/Cloudflare this may be the ingress proxy IP instead of the end user's IP. If exact original IP capture is required, configure and test your actual trusted reverse-proxy chain, with only verified ingress IPs trusted for forwarded headers. Do not enable `--forwarded-allow-ips='*'` on an unrestricted public origin. IP does not prove a person's identity or precise location.

Deploy only after setting an appropriate privacy notice and handling deletion requests. Use strong Admin secrets, least-privilege database credentials, HTTPS and backup/rotation procedures. The in-memory throttle is a basic guard, not a substitute for edge rate limiting/abuse protection.

## Test

```bash
python3 -m unittest discover -s OnlineService/tests -v  # run from repo root
swiftc -frontend -parse iOSApp/App/LicenseAccess50.swift
```

Unit tests validate API lifecycle, Admin protection, invalidation, IP audit presence and notice requirements. Native Swift/iOS build must run on a macOS Xcode runner; the Linux parser is not a compiler/type-checker for SwiftUI and there is **no on-device verification** from this source archive.

## Build51: Public GitHub Pages Admin + private FastAPI backend

This repository now includes `WebAdmin/` and `.github/workflows/deploy-admin-pages.yml`. The Pages site is a static authenticated **client**, never a database or license server. The new `ADMIN_ALLOWED_ORIGINS` environment variable contains one or more comma-separated HTTPS **origins** allowed to invoke Admin APIs cross-site, for example `https://USERNAME.github.io`. Omitting this setting disables cross-origin browser access but keeps same-origin `/admin` working. The Admin token is never emitted in Pages JavaScript or GitHub Actions; it remains private and is entered manually in browser memory.

A repository-root `render.yaml` is provided for a Free Render web-service experiment and requires a persistent Postgres `DATABASE_URL` supplied privately to the hosting service. Note: Render Free Postgres expires after 30 days and is not suitable for durable licenses. Follow `../DEPLOY_ADMIN_ON_IPHONE.md` for full setup instructions and Pages URL routing. This task does not create any live hosting deployment by itself.
