# Web Admin Build51 (GitHub Pages)

- Deploy with `.github/workflows/deploy-admin-pages.yml`; published project path is `/admin/`.
- Backend URL is public and can be set via GitHub Actions variable `AOV_LICENSE_SERVER_URL`.
- If no URL is configured, manually paste an HTTPS origin in the Admin page.
- Admin token is **never** committed, embedded in the IPA, copied to GitHub Pages or written to browser storage.
- Only send the token to a trusted HTTPS license backend you control. Use `ADMIN_ALLOWED_ORIGINS=https://YOURNAME.github.io` on the backend to enable CORS for this Admin site.
- GitHub Pages hosts **static files only**. The FastAPI API must remain online on another host.
