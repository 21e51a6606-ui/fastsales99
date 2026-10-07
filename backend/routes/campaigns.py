from datetime import date, datetime
import random

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from models import db, Campaign, Product, Lead, WAMessage, WATemplate, CallLog, User
from utils import login_required, role_required, current_user, audit

bp = Blueprint("campaigns", __name__, url_prefix="/campaigns")

CHANNELS = ["WhatsApp", "AI Call", "Email", "SMS"]


@bp.route("/")
@login_required
def index():
    tab = request.args.get("tab", "active")
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status")
    base = Campaign.query
    if q:
        base = base.filter(Campaign.name.ilike(f"%{q}%"))
    if status:
        base = base.filter(Campaign.status == status)
    all_rows = base.order_by(Campaign.created_at.desc()).all()
    active = [c for c in all_rows if c.status in ("Active", "Paused", "Draft")]
    history = [c for c in all_rows if c.status == "Completed"]
    totals = {
        "total": Campaign.query.count(),
        "active": Campaign.query.filter_by(status="Active").count(),
        "audience": sum(c.audience_size for c in Campaign.query.all()),
        "sent": sum(c.sent for c in Campaign.query.all()),
        "engaged": sum(c.engaged for c in Campaign.query.all()),
        "outcomes": sum(c.outcomes for c in Campaign.query.all()),
    }
    totals["engagement"] = round(100 * totals["engaged"] / totals["sent"], 1) if totals["sent"] else 0.0
    products = Product.query.order_by(Product.name).all()
    templates = WATemplate.query.filter_by(status="Approved").all()
    return render_template("campaigns.html", tab=tab, active=active, history=history, totals=totals,
                           products=products, channels=CHANNELS, templates=templates, q=q, status=status)


@bp.route("/add", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def add():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Campaign name is required.", "danger")
        return redirect(url_for("campaigns.index"))
    pid = request.form.get("product_id", type=int) or None
    audience_q = Lead.query
    if pid:
        audience_q = audience_q.filter(Lead.product_id == pid)
    seg = request.form.get("segment", "all")
    if seg == "uncontacted":
        audience_q = audience_q.filter(Lead.contacted == False)
    elif seg == "interested":
        audience_q = audience_q.filter(Lead.status.in_(["Interested", "Follow Up"]))
    elif seg == "high":
        audience_q = audience_q.filter(Lead.priority == "High")
    c = Campaign(name=name, channel=request.form.get("channel") or "WhatsApp", strategy=request.form.get("strategy"),
                 status="Draft", audience_size=audience_q.count(), product_id=pid)
    for f in ("start_date", "end_date"):
        v = request.form.get(f)
        if v:
            setattr(c, f, date.fromisoformat(v))
    db.session.add(c)
    db.session.flush()
    audit("CREATE", f"Campaign created: {name}", f"audience={c.audience_size}")
    db.session.commit()
    flash(f"Campaign created with an audience of {c.audience_size} leads.", "success")
    return redirect(url_for("campaigns.index"))


@bp.route("/<int:cid>/status", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def set_status(cid):
    c = db.session.get(Campaign, cid)
    if not c:
        return jsonify({"error": "not found"}), 404
    status = (request.get_json(silent=True) or request.form).get("status")
    if status not in ("Draft", "Active", "Paused", "Completed"):
        return jsonify({"error": "bad status"}), 400
    c.status = status
    audit("UPDATE", f"Campaign {status.lower()}: {c.name}")
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True, "status": status})
    return redirect(url_for("campaigns.index"))


@bp.route("/<int:cid>/run", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def run_batch(cid):
    """Dispatch a batch of the campaign: creates WhatsApp messages / AI calls for the next N audience members."""
    c = db.session.get(Campaign, cid)
    if not c:
        return jsonify({"error": "not found"}), 404
    if c.status != "Active":
        return jsonify({"error": "campaign must be Active to run"}), 400
    n = int((request.get_json(silent=True) or {}).get("batch") or 25)
    q = Lead.query
    if c.product_id:
        q = q.filter(Lead.product_id == c.product_id)
    batch = q.order_by(Lead.id).offset(c.sent).limit(min(n, max(0, c.audience_size - c.sent))).all()
    tmpl = WATemplate.query.filter_by(status="Approved").first()
    engaged = outcomes = 0
    for ld in batch:
        if c.channel == "AI Call":
            st = random.choices(["Connected", "Failed", "Busy", "No Answer"], [0.35, 0.3, 0.15, 0.2])[0]
            dur = random.randint(40, 400) if st == "Connected" else 0
            db.session.add(CallLog(lead_id=ld.id, user_id=current_user().id, contact_name=ld.name, phone=ld.phone,
                                   status=st, duration_sec=dur, cost=round(dur / 60 * 0.9, 2)))
            if st == "Connected":
                engaged += 1
        else:
            st = random.choices(["Delivered", "Sent", "Failed"], [0.7, 0.2, 0.1])[0]
            body = (tmpl.body if tmpl else "Hi {{1}}, reaching out from GenAIlakes.").replace("{{1}}", ld.name.split()[0]).replace("{{2}}", "the 20th")
            db.session.add(WAMessage(recipient=ld.phone, recipient_name=ld.name, template_id=tmpl.id if tmpl else None,
                                     content=body, context=f"Campaign: {c.name}", status=st))
            if st == "Delivered" and random.random() < 0.2:
                engaged += 1
        if random.random() < 0.02:
            outcomes += 1
    c.sent += len(batch)
    c.engaged += engaged
    c.outcomes += outcomes
    if c.sent >= c.audience_size:
        c.status = "Completed"
    audit("CAMPAIGN", f"Campaign batch dispatched: {c.name}", f"{len(batch)} sent, {engaged} engaged")
    db.session.commit()
    return jsonify({"ok": True, "sent": len(batch), "engaged": engaged, "total_sent": c.sent,
                    "progress": c.progress, "status": c.status})


@bp.route("/<int:cid>/delete", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def delete(cid):
    c = db.session.get(Campaign, cid)
    if c:
        audit("DELETE", f"Campaign deleted: {c.name}")
        db.session.delete(c)
        db.session.commit()
        flash("Campaign deleted.", "info")
    return redirect(url_for("campaigns.index"))
