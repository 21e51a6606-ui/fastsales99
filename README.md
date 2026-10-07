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

Everything needed is in `deploy/`. Two options:

### Option A: Ubuntu VPS (Gunicorn + Nginx + systemd)

```bash
# on the server
sudo mkdir -p /opt/fastsales99 && sudo chown $USER /opt/fastsales99
# copy the project there (git clone, scp, rsync ...), then:
cd /opt/fastsales99
sudo bash deploy/install.sh          # installs deps, creates /etc/fastsales99.env
sudo nano /etc/fastsales99.env       # set SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD
sudo bash deploy/install.sh          # second run: starts the service and configures Nginx
```

The app is then served on port 80. Point a domain at the server, set `server_name` in
`/etc/nginx/sites-available/fastsales99`, and run `sudo certbot --nginx -d yourdomain.com` for HTTPS.

Useful commands: `sudo systemctl restart fastsales99`, `sudo journalctl -u fastsales99 -f`.
To update: pull the new code into `/opt/fastsales99` and restart the service.

### Option A2: Oracle Cloud Always Free VM (free forever)

1. Sign up at https://cloud.oracle.com (card needed for verification only). Pick a home region close to you.
2. Compute -> Instances -> Create instance. Image: **Ubuntu 22.04 or 24.04**. Shape: **VM.Standard.E2.1.Micro**
   (Always Free) or Ampere A1. Download the SSH private key it generates. Note the public IP.
3. Open the web ports in the cloud firewall: Networking -> Virtual Cloud Networks -> your VCN -> Subnet ->
   Default Security List -> Add Ingress Rule: Source `0.0.0.0/0`, protocol TCP, destination port `80`.
   Add another for port `443`.
4. SSH in: `ssh -i path	o\key.key ubuntu@PUBLIC_IP`
5. On the server:

```bash
sudo mkdir -p /opt/fastsales99 && sudo chown ubuntu /opt/fastsales99
git clone https://github.com/21e51a6606-ui/fastsales99.git /opt/fastsales99   # username + GitHub token when asked
cd /opt/fastsales99
sudo bash deploy/install.sh          # installs everything, creates /etc/fastsales99.env
sudo nano /etc/fastsales99.env       # set SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD; Ctrl+O, Enter, Ctrl+X
sudo bash deploy/install.sh          # second run starts the app
```

Open `http://PUBLIC_IP` in a browser and sign in as Super Admin. To update later:
`cd /opt/fastsales99 && git pull && sudo systemctl restart fastsales99`.

### Option B: Docker (any host, Render, Railway, Fly.io ...)

```bash
docker build -t fastsales99 .
docker run -d -p 8000:8000 -v fastsales_data:/app/backend/instance   -e SECRET_KEY=... -e ADMIN_EMAIL=... -e ADMIN_PASSWORD=... fastsales99
```

Mount a persistent volume on `/app/backend/instance` or set `DATABASE_URL` to Postgres, otherwise the
SQLite database is lost on redeploy.

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
