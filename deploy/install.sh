#!/usr/bin/env bash
# One-shot setup on a fresh Ubuntu 22.04/24.04 server. Run as root (sudo bash deploy/install.sh)
# from the project root after copying the project to /opt/fastsales99.
set -euo pipefail
APP_DIR=/opt/fastsales99

apt-get update
apt-get install -y python3 python3-venv nginx git

# Oracle Cloud Ubuntu images ship with iptables rules that drop web traffic. Open 80/443.
if command -v iptables >/dev/null && iptables -C INPUT -j REJECT --reject-with icmp-host-prohibited 2>/dev/null; then
  iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
  iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
  DEBIAN_FRONTEND=noninteractive apt-get install -y netfilter-persistent iptables-persistent
  netfilter-persistent save
fi

id -u fastsales >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin fastsales

cd "$APP_DIR/backend"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
mkdir -p instance
chown -R fastsales:fastsales "$APP_DIR"

if [ ! -f /etc/fastsales99.env ]; then
  cp "$APP_DIR/deploy/.env.example" /etc/fastsales99.env
  chmod 600 /etc/fastsales99.env
  echo ">> Edit /etc/fastsales99.env now (SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD), then re-run this script."
  exit 0
fi

cp "$APP_DIR/deploy/fastsales99.service" /etc/systemd/system/fastsales99.service
systemctl daemon-reload
systemctl enable --now fastsales99
systemctl restart fastsales99

cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/fastsales99
ln -sf /etc/nginx/sites-available/fastsales99 /etc/nginx/sites-enabled/fastsales99
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ">> Done. App is on port 80. Set server_name in /etc/nginx/sites-available/fastsales99 and run certbot for HTTPS."
systemctl --no-pager status fastsales99 | head -5
