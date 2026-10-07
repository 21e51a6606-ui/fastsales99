from datetime import datetime, timedelta, date
import random

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import func

from models import db, WATemplate, WAMessage, WASession, Lead, Setting
from utils import login_required, role_required, current_user, audit

bp = Blueprint("whatsapp", __name__, url_prefix="/dashboard")

CATEGORIES = ["Marketing", "Utility", "Authentication"]


def _provider_health():
    wacto = "Healthy" if Setting.get("wacto_api_key") else "Config Error"
    meta = "Healthy" if Setting.get("meta_token") else "Config Error"
    since = datetime.utcnow() - timedelta(days=1)
    inbound = WAMessage.query.filter(WAMessage.direction == "in", WAMessage.created_at >= since).count()
    return {"wacto": wacto, "meta": meta, "webhook": f"{inbound} inbound (24h)" if inbound else "Idle (Last 24h)",
            "queue": WAMessage.query.filter_by(status="Queued").count(),
            "failed": WAMessage.query.filter_by(status="Failed").count()}


@bp.route("/whatsapp")
@login_required
def index():
    tab = request.args.get("tab", "dashboard")
    today = datetime.combine(date.today(), datetime.min.time())
    templates = WATemplate.query.order_by(WATemplate.created_at.desc()).all()
    stats = {
        "templates": len(templates),
        "approved": sum(1 for t in templates if t.status == "Approved"),
        "pending": sum(1 for t in templates if t.status == "Pending"),
        "failed": sum(1 for t in templates if t.status == "Failed"),
        "contacts": Lead.query.filter(Lead.phone.isnot(None)).count(),
        "sent_today": WAMessage.query.filter(WAMessage.created_at >= today, WAMessage.direction == "out").count(),
        "delivered_today": WAMessage.query.filter(WAMessage.created_at >= today, WAMessage.status == "Delivered").count(),
        "failed_today": WAMessage.query.filter(WAMessage.created_at >= today, WAMessage.status == "Failed").count(),
    }
    page = request.args.get("page", 1, type=int)
    q = (request.args.get("q") or "").strip()
    cq = Lead.query.filter(Lead.phone.isnot(None))
    if q:
        like = f"%{q}%"
        cq = cq.filter((Lead.name.ilike(like)) | (Lead.phone.ilike(like)))
    contacts = cq.order_by(Lead.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    dispatch = WAMessage.query.order_by(WAMessage.created_at.desc()).limit(10).all()
    activity = WAMessage.query.order_by(WAMessage.created_at.desc()).limit(100).all()
    # conversations grouped by recipient
    convs = {}
    for m in WAMessage.query.order_by(WAMessage.created_at.desc()).limit(300).all():
        convs.setdefault(m.recipient, {"name": m.recipient_name or m.recipient, "phone": m.recipient,
                                        "last": m.content, "at": m.created_at, "count": 0})["count"] += 1
    sess = WASession.query.first()
    return render_template("whatsapp.html", tab=tab, templates=templates, stats=stats, health=_provider_health(),
                           contacts=contacts, dispatch=dispatch, activity=activity, convs=list(convs.values()),
                           categories=CATEGORIES, q=q, session_row=sess)


@bp.route("/whatsapp/template/add", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def template_add():
    name = request.form.get("name", "").strip().lower().replace(" ", "_")
    body = request.form.get("body", "").strip()
    if not name or not body:
        flash("Template name and body are required.", "danger")
        return redirect(url_for("whatsapp.index", tab="templates"))
    t = WATemplate(name=name, category=request.form.get("category") or "Marketing",
                   language=request.form.get("language") or "en", body=body, status="Pending")
    db.session.add(t)
    audit("CREATE", f"WhatsApp template submitted: {name}")
    db.session.commit()
    flash("Template submitted for approval.", "success")
    return redirect(url_for("whatsapp.index", tab="templates"))


@bp.route("/whatsapp/template/<int:tid>/status", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def template_status(tid):
    t = db.session.get(WATemplate, tid)
    if not t:
        return jsonify({"error": "not found"}), 404
    status = (request.get_json(silent=True) or request.form).get("status")
    if status not in ("Approved", "Pending", "Failed"):
        return jsonify({"error": "bad status"}), 400
    t.status = status
    audit("UPDATE", f"WhatsApp template {status.lower()}: {t.name}")
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True})
    return redirect(url_for("whatsapp.index", tab="templates"))


@bp.route("/whatsapp/template/<int:tid>/delete", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def template_delete(tid):
    t = db.session.get(WATemplate, tid)
    if t:
        WAMessage.query.filter_by(template_id=t.id).update({"template_id": None})
        audit("DELETE", f"WhatsApp template deleted: {t.name}")
        db.session.delete(t)
        db.session.commit()
    return redirect(url_for("whatsapp.index", tab="templates"))


@bp.route("/whatsapp/send", methods=["POST"])
@login_required
def send_direct():
    data = request.get_json(silent=True) or request.form
    to = (data.get("phone") or "").strip()
    content = (data.get("content") or "").strip()
    tid = data.get("template_id")
    if not to:
        msg = "Recipient phone is required."
        return (jsonify({"error": msg}), 400) if request.is_json else _flash_redirect(msg, "danger", "direct")
    tmpl = db.session.get(WATemplate, int(tid)) if tid else None
    if tmpl and not content:
        content = tmpl.body
    if not content:
        msg = "Message content is required."
        return (jsonify({"error": msg}), 400) if request.is_json else _flash_redirect(msg, "danger", "direct")
    lead = Lead.query.filter_by(phone=to).first()
    configured = bool(Setting.get("wacto_api_key") or Setting.get("meta_token"))
    status = "Sent" if configured else "Failed"
    m = WAMessage(recipient=to, recipient_name=lead.name if lead else data.get("name"), template_id=tmpl.id if tmpl else None,
                  content=content, context="Direct", status=status)
    db.session.add(m)
    audit("WHATSAPP", f"Direct message to {to}", f"status={status}")
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": status != "Failed", "status": status, "id": m.id,
                        "hint": None if configured else "No provider configured. Add a Wacto/Meta key in Settings > Communication."})
    return _flash_redirect(f"Message {status.lower()} to {to}." + ("" if configured else " Configure a provider in Settings to actually deliver."),
                           "success" if configured else "warning", "direct")


def _flash_redirect(msg, cat, tab):
    flash(msg, cat)
    return redirect(url_for("whatsapp.index", tab=tab))


@bp.route("/whatsapp/webhook", methods=["POST"])
def webhook():
    """Inbound webhook (Meta/Wacto style). Records inbound messages and delivery receipts."""
    payload = request.get_json(silent=True) or {}
    phone = payload.get("from") or payload.get("phone")
    text = payload.get("text") or payload.get("body")
    mid = payload.get("message_id")
    if mid and payload.get("status"):
        m = db.session.get(WAMessage, int(mid))
        if m:
            m.status = payload["status"].title()
            db.session.commit()
            return jsonify({"ok": True, "updated": m.id})
    if phone and text:
        lead = Lead.query.filter_by(phone=phone).first()
        m = WAMessage(recipient=phone, recipient_name=lead.name if lead else None, content=text,
                      direction="in", context="Inbound", status="Delivered")
        db.session.add(m)
        db.session.commit()
        return jsonify({"ok": True, "id": m.id})
    return jsonify({"error": "unrecognised payload"}), 400


# ---------- chat conversation page ----------
@bp.route("/chat-conversation")
@login_required
def chat():
    sess = WASession.query.first()
    convs = []
    if sess and sess.status == "Connected":
        grouped = {}
        for m in WAMessage.query.order_by(WAMessage.created_at.asc()).all():
            grouped.setdefault(m.recipient, {"phone": m.recipient, "name": m.recipient_name or m.recipient, "messages": []})
            grouped[m.recipient]["messages"].append(m)
        convs = sorted(grouped.values(), key=lambda c: c["messages"][-1].created_at, reverse=True)
    return render_template("chat.html", session_row=sess, convs=convs)


@bp.route("/chat-conversation/reply", methods=["POST"])
@login_required
def chat_reply():
    data = request.get_json(silent=True) or {}
    to, text = data.get("phone"), (data.get("text") or "").strip()
    if not to or not text:
        return jsonify({"error": "phone and text required"}), 400
    lead = Lead.query.filter_by(phone=to).first()
    m = WAMessage(recipient=to, recipient_name=lead.name if lead else None, content=text, context="Live Chat", status="Sent")
    db.session.add(m)
    db.session.commit()
    return jsonify({"ok": True, "id": m.id, "at": m.created_at.isoformat()})


# ---------- web automation (session connect) ----------
@bp.route("/web-automation")
@login_required
def web_automation():
    sess = WASession.query.first()
    return render_template("web_automation.html", session_row=sess)


@bp.route("/web-automation/connect", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def wa_connect():
    sess = WASession.query.first()
    if not sess:
        sess = WASession()
        db.session.add(sess)
    sess.phone = request.form.get("phone") or sess.phone
    sess.label = request.form.get("label") or sess.label
    sess.status = "Connected"
    sess.connected_at = datetime.utcnow()
    audit("WHATSAPP", f"WhatsApp Web session connected: {sess.phone}")
    db.session.commit()
    flash("WhatsApp Web session connected (simulated QR pairing).", "success")
    return redirect(url_for("whatsapp.web_automation"))


@bp.route("/web-automation/disconnect", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def wa_disconnect():
    sess = WASession.query.first()
    if sess:
        sess.status = "Disconnected"
        audit("WHATSAPP", "WhatsApp Web session disconnected")
        db.session.commit()
    flash("Session disconnected.", "info")
    return redirect(url_for("whatsapp.web_automation"))
