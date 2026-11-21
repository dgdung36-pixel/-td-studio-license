# Trong Dung Studio — License Server & Web Admin (Build51)

This repository contains the **Build51 server/admin deployment source** (not the iOS IPA source).

## Contents
- `OnlineService/` — FastAPI License API, admin endpoints, access logs, PostgreSQL backend.
- `WebAdmin/` — static Admin dashboard with key creation, rotation, revocation, device management and logs.
- `render.yaml` — Render Blueprint for the Python backend.
- `.github/workflows/deploy-admin-pages.yml` — GitHub Pages deployment for the Admin site.
- `DEPLOY_ADMIN_ON_IPHONE.md` — setup instructions.

## Activate the website
1. Open [Settings → Pages](https://github.com/dgdung36-pixel/-td-studio-license/settings/pages) and choose **GitHub Actions** as the build/deploy source.
2. Visit [Actions](https://github.com/dgdung36-pixel/-td-studio-license/actions/workflows/deploy-admin-pages.yml) and run **TD Studio Build51 - Deploy Admin to GitHub Pages**, branch `main`.
3. Once deployment succeeds, open `https://dgdung36-pixel.github.io/-td-studio-license/admin/`.

## Make license keys work
1. Create a PostgreSQL database (for example, Supabase) and a Render web service from `render.yaml`.
2. Configure Render environment variables: `DATABASE_URL`, `LICENSE_ADMIN_TOKEN`, `ADMIN_ALLOWED_ORIGINS=https://dgdung36-pixel.github.io`. Keep sensitive values **on the server**, not in this repository.
3. Set the repository Actions variable `AOV_LICENSE_SERVER_URL` to your actual HTTPS Render service origin and redeploy the Admin site.
4. Configure the same server origin in your iOS app build, then test creating and revoking a temporary license.

**Status:** Source committed and static Admin checks passed in GitHub Actions. GitHub Pages is not live until enabled in repository Settings; no Render server or PostgreSQL database has been provisioned here.

**Privacy:** Inform app users about login-IP logging, limit retention, and restrict access to the Admin dashboard. Do not commit tokens, database passwords or user access logs to this public repository.
