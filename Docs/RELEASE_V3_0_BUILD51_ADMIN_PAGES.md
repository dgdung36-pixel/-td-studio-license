# Build51 — GitHub Pages Admin / Render server

Based on Build50; no modification of the AOV mod-update engine, model assets, or iOS license gate.

## New

- `WebAdmin/`: mobile-friendly static Admin dashboard for Pages at `/admin/`, explicit server URL entry, no Admin secret stored on disk or Pages.
- `.github/workflows/deploy-admin-pages.yml`: GitHub Actions Pages deployment independent of the unsigned IPA workflow. Configured public API origin is injected by workflow from GitHub Actions **variable** `AOV_LICENSE_SERVER_URL`.
- `OnlineService/app.py`: allowlisted CORS via `ADMIN_ALLOWED_ORIGINS` for cross-site Admin calls; default is no cross-origin admin access.
- `render.yaml` (repository root): Render Blueprint with `rootDir=OnlineService`, no secrets embedded, persistent database URL required. Defaults to free web service; free service sleeping is expected.
- `OnlineService/admin.js`: one shared implementation for backend-hosted and GitHub Pages Admin, accepts HTTPS origin and keeps Admin token only in JS memory.

## Not yet done automatically

No hosted server, Pages website, database or IPA is created merely from source files. The GitHub connector used for this task did not show the previously referenced `aovmodup` repository, so no changes were pushed to any GitHub repository. Host deployment needs account permissions and configuration by the owner. Native iOS build requires an Xcode runner.

## Security / privacy

Admin token must remain on the server and be entered only on the Admin page over trusted HTTPS. The Pages site code is public; don't put any secrets in the `AOV_LICENSE_SERVER_URL` variable. Existing 30-day activation/verification IP log and privacy notice behavior remain unchanged. Accurate client IP under a proxy requires configuring verified ingress CIDRs and testing the actual deployment; do not blindly trust forwarded IP headers.
