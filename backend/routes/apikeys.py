from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from models import db, APIKey
from utils import login_required, role_required, current_user, audit

bp = Blueprint("apikeys", __name__, url_prefix="/api-keys")

SCOPES = ["read", "write", "calls", "webhooks", "admin"]


@bp.route("/")
@login_required
@role_required("super_admin", "admin")
def index():
    keys = APIKey.query.order_by(APIKey.created_at.desc()).all()
    new_key = request.args.get("new")
    return render_template("api_keys.html", keys=keys, scopes=SCOPES, new_key=new_key,
                           base_url=request.host_url.rstrip("/"))


@bp.route("/create", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def create():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Key name is required.", "danger")
        return redirect(url_for("apikeys.index"))
    scopes = [s for s in request.form.getlist("scopes") if s in SCOPES] or ["read"]
    raw = APIKey.generate()
    k = APIKey(name=name, scopes=",".join(scopes), owner_id=current_user().id)
    k.set_key(raw)
    days = request.form.get("expires_days", type=int)
    if days:
        k.expires_at = datetime.utcnow() + timedelta(days=days)
    db.session.add(k)
    db.session.flush()
    audit("CREATE", f"API key created: {name}", ",".join(scopes))
    db.session.commit()
    # show the raw key once via session flash-like query param
    return redirect(url_for("apikeys.index", new=raw))


@bp.route("/<int:kid>/revoke", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def revoke(kid):
    k = db.session.get(APIKey, kid)
    if k:
        k.is_active = not k.is_active
        audit("UPDATE", f"API key {'re-enabled' if k.is_active else 'revoked'}: {k.name}")
        db.session.commit()
    if request.is_json:
        return jsonify({"ok": True, "is_active": k.is_active if k else None})
    return redirect(url_for("apikeys.index"))


@bp.route("/<int:kid>/delete", methods=["POST"])
@login_required
@role_required("super_admin")
def delete(kid):
    k = db.session.get(APIKey, kid)
    if k:
        audit("DELETE", f"API key deleted: {k.name}")
        db.session.delete(k)
        db.session.commit()
        flash("API key deleted.", "info")
    return redirect(url_for("apikeys.index"))
