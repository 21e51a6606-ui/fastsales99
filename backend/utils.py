"""Shared helpers: auth decorators, audit logging, formatting filters."""
from datetime import datetime
from functools import wraps

from flask import session, redirect, url_for, request, flash, g, jsonify, abort

from models import db, User, AuditLog, APIKey

ADMIN_ROLES = {"super_admin", "admin"}
MANAGEMENT_ROLES = {"super_admin", "admin", "manager", "team_lead"}


def current_user():
    if getattr(g, "_user", None) is not None:
        return g._user
    uid = session.get("user_id")
    g._user = db.session.get(User, uid) if uid else None
    return g._user


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify({"error": "authentication required"}), 401
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return fn(*a, **kw)
    return wrapper


def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                return redirect(url_for("auth.login", next=request.path))
            if u.role not in roles:
                if request.path.startswith("/api/") or request.is_json:
                    return jsonify({"error": "forbidden"}), 403
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def api_key_required(scope="read"):
    """Authenticate public REST calls with `Authorization: Bearer <key>` or `X-API-Key`."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            raw = request.headers.get("X-API-Key") or ""
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                raw = auth[7:].strip()
            if not raw:
                # fall back to a logged-in session for convenience
                if current_user():
                    return fn(*a, **kw)
                return jsonify({"error": "missing API key"}), 401
            key = APIKey.query.filter_by(prefix=raw[:12], is_active=True).first()
            if not key or not key.matches(raw):
                return jsonify({"error": "invalid API key"}), 401
            if key.expires_at and key.expires_at < datetime.utcnow():
                return jsonify({"error": "API key expired"}), 401
            scopes = set((key.scopes or "").split(","))
            if scope not in scopes and "admin" not in scopes:
                return jsonify({"error": f"key lacks '{scope}' scope"}), 403
            key.last_used = datetime.utcnow()
            key.usage_count = (key.usage_count or 0) + 1
            db.session.commit()
            g.api_key = key
            return fn(*a, **kw)
        return wrapper
    return deco


def audit(action, title, details=None, user=None):
    """Write an audit-log row. Caller is responsible for commit."""
    u = user or current_user()
    entry = AuditLog(user_id=u.id if u else None, action=action, title=title,
                     details=details, ip=request.remote_addr if request else None)
    db.session.add(entry)
    return entry


# ---------- template filters ----------
def inr(value, compact=False):
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "₹0"
    if compact:
        if abs(v) >= 1e7:
            return f"₹{v/1e7:.1f}Cr"
        if abs(v) >= 1e5:
            return f"₹{v/1e5:.1f}L"
        if abs(v) >= 1e3:
            return f"₹{v/1e3:.1f}K"
    return f"₹{v:,.0f}" if v == int(v) else f"₹{v:,.2f}"


def timeago(dt):
    if not dt:
        return "-"
    diff = datetime.utcnow() - dt
    s = int(diff.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def fmt_dt(dt, fmt="%m/%d/%Y, %I:%M:%S %p"):
    return dt.strftime(fmt) if dt else "-"


def register_filters(app):
    app.jinja_env.filters["inr"] = inr
    app.jinja_env.filters["timeago"] = timeago
    app.jinja_env.filters["dt"] = fmt_dt
