# Demo Deployment Without Card

This project can be demoed online by running it on your own Windows machine and exposing it with Cloudflare Tunnel.

## Why this works

- All current features continue to use the local project files:
  - `student.db`
  - `daily.db`
  - OCR
  - uploads
  - student/staff flows
- Good fit for a small demo with about 30 users.

## One-time setup

1. Install Python 3.10+ if needed.
2. Install Cloudflare Tunnel:
   - Download `cloudflared` for Windows from Cloudflare's official site.
3. Open a terminal in:
   - `C:\dev\laundry repo 3`

## Start the app

You can use the helper script:

```bat
start_demo.bat
```

This will:

- create `.venv` if needed
- install dependencies
- start the app with `waitress` on `127.0.0.1:8000`

## Expose it online

Open a second terminal in the same folder and run:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Cloudflare will print a public `https://...trycloudflare.com` URL.

Share that link for the demo.

## Important notes

- Keep this PC on while the demo is active.
- Keep both terminals open.
- SQLite is acceptable for a 30-user demo, but avoid heavy concurrent admin edits during OCR uploads.
- If you restart the app, the tunnel URL may change unless you later create a named tunnel.

## Staff demo login

- Username: `Test`
- Password: `1234`

## If the site does not load

1. Make sure the app terminal says it is serving on port `8000`.
2. Make sure `cloudflared` is still running.
3. Hard refresh the browser.
4. Check that Windows Firewall is not blocking Python or `cloudflared`.
