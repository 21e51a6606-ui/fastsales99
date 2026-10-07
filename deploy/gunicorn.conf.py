"""Gunicorn settings. Used by the systemd unit and the Dockerfile."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = 4
timeout = 60
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "*"   # trust X-Forwarded-* from the reverse proxy
