# FastSales99 / Genailakes Admin Portal (Python clone)

A Flask + SQLite re-implementation of the Genailakes sales-management admin portal: role-based login,
dashboard, deals pipeline (kanban + table), employee hierarchy, lead assignment, products, AI agents,
API keys, payments/invoices/wallet, analytics, audit logs, campaigns, WhatsApp operations, settings and help.

## Project layout

```
backend/                 Python (Flask) application
  app.py                 app factory, blueprints, error pages, create-admin CLI command
  models.py              SQLAlchemy models (users, leads, deals, calls, agents, keys, payments, ...)
  utils.py               auth decorators, API-key auth, audit helper, Jinja filters
  requirements.txt
  routes/                one blueprint per module (auth, main, deals, leads, employees, ...)
  instance/              SQLite database lives here (created on first run)
frontend/                Jinja templates + static assets served by the backend
  templates/             one page per screen; base.html holds the top bar + nav
  static/css/style.css   design system (light/dark)
  static/js/app.js       shared helpers (fetch, modals, toasts, theme)
```

## Run

```bash
cd backend
pip install -r requirements.txt
flask --app app create-admin      # one-time: creates your Super Admin login (prompts for name/email/password)
python app.py                     # http://127.0.0.1:5000
```

The SQLite database is created empty in `backend/instance/fastsales.db` on first start. There is no demo
data; sign in as the Super Admin and add employees, products, leads and the rest from the UI or the REST API.

For a server deploy you can create the admin non-interactively instead: set `ADMIN_EMAIL`, `ADMIN_PASSWORD`
(and optionally `ADMIN_NAME`) in the environment on the first start and the account is created automatically.
Set `SECRET_KEY` to a long random value in production.

## Deploy to a server

### Free option: Render (app) + Neon (Postgres database). Only a GitHub login is needed.

1. **Database:** sign in at https://neon.tech with GitHub, create a project (any name, region Singapore or
   closest to you). On the project dashboard click **Connect**, copy the connection string
   (`postgresql://...neon.tech/neondb?sslmode=require`).
2. **App:** sign in at https://render.com with GitHub. Click **New -> Blueprint**, pick the `fastsales99`
   repo. Render reads `render.yaml` and asks for three values:
   - `DATABASE_URL`: paste the Neon connection string
   - `ADMIN_EMAIL` / `ADMIN_PASSWORD`: your Super Admin login
3. Click **Apply**. The first build takes 3-5 minutes. Open the `https://fastsales99-xxxx.onrender.com` URL,
   choose Super Admin on the wheel and sign in.
4. After the first login, open the service's **Environment** tab and delete `ADMIN_PASSWORD`.

Free-tier behaviour: the app sleeps after 15 minutes without visitors and the next request takes
30-60 s to wake it. Data lives in Neon, so nothing is lost. Every `git push` redeploys automatically.

### Paid / self-hosted options

- **Any Docker host** (Railway, Fly.io, Render paid): `docker build -t fastsales99 .` and run with the same
  environment variables. Without `DATABASE_URL` the app uses SQLite in `/app/backend/instance`; mount a
  volume there to persist it.
- **Ubuntu VPS** (Oracle Always Free, Hetzner, DigitalOcean ...): clone the repo to `/opt/fastsales99` and run
  `sudo bash deploy/install.sh` twice (first run creates `/etc/fastsales99.env` for you to fill in, second run
  starts Gunicorn behind Nginx as a systemd service). Oracle: also open ports 80/443 in the VCN security list.

### Environment variables

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Required. Session signing key; use a long random string. |
| `DATABASE_URL` | SQLAlchemy URL. Defaults to SQLite in `backend/instance/`. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME` | Create the first Super Admin on first start if no users exist. |
| `PORT`, `WEB_CONCURRENCY` | Gunicorn port (8000) and worker count (2). |
| `FLASK_DEBUG` | Only affects `python app.py`; set `0` outside development. |

## Public REST API

Generate a key under **API Keys**, then:

```bash
curl http://127.0.0.1:5000/api/v1/leads -H "Authorization: Bearer fs_live_..."
curl -X POST http://127.0.0.1:5000/api/v1/leads -H "X-API-Key: fs_live_..." \
     -H "Content-Type: application/json" -d '{"name":"Jane","phone":"+919999999999"}'
```

Endpoints: `/api/v1/ping`, `/leads`, `/leads/{id}`, `/deals`, `/calls`, `/products`, `/agents`, `/users`, `/stats`.
Inbound WhatsApp webhook: `POST /dashboard/whatsapp/webhook`.
