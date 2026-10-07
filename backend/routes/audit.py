import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, Response, jsonify

from models import db, AuditLog, User
from utils import login_required, role_required

bp = Blueprint("audit", __name__, url_prefix="/audit")


def _query():
    q = (request.args.get("q") or "").strip()
    action = request.args.get("action")
    uid = request.args.get("user", type=int)
    period = request.args.get("period")
    base = AuditLog.query
    if q:
        like = f"%{q}%"
        base = base.join(User, isouter=True).filter(
            (AuditLog.title.ilike(like)) | (AuditLog.details.ilike(like)) | (User.name.ilike(like)) | (User.email.ilike(like)))
    if action:
        base = base.filter(AuditLog.action == action)
    if uid:
        base = base.filter(AuditLog.user_id == uid)
    if period and period.isdigit():
        base = base.filter(AuditLog.created_at >= datetime.utcnow() - timedelta(days=int(period)))
    return base.order_by(AuditLog.created_at.desc())


@bp.route("/")
@login_required
@role_required("super_admin", "admin", "manager")
def index():
    page = request.args.get("page", 1, type=int)
    pagination = _query().paginate(page=page, per_page=25, error_out=False)
    actions = [r[0] for r in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action)]
    users = User.query.order_by(User.name).all()
    return render_template("audit.html", pagination=pagination, rows=pagination.items, actions=actions,
                           users=users, args=request.args)


@bp.route("/export.csv")
@login_required
@role_required("super_admin", "admin")
def export():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "timestamp", "action", "title", "details", "user", "email", "role", "ip"])
    for r in _query().limit(5000).all():
        w.writerow([r.public_id, r.created_at.isoformat(), r.action, r.title, r.details or "",
                    r.user.name if r.user else "", r.user.email if r.user else "",
                    r.user.role if r.user else "", r.ip or ""])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=audit_logs.csv"})


@bp.route("/data")
@login_required
@role_required("super_admin", "admin", "manager")
def data():
    rows = _query().limit(200).all()
    return jsonify([{"id": r.public_id, "action": r.action, "title": r.title, "details": r.details,
                     "user": r.user.name if r.user else None, "ip": r.ip, "at": r.created_at.isoformat()} for r in rows])
