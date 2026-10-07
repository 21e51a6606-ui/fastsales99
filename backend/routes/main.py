from datetime import datetime, timedelta, date
import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import func

from models import (db, User, Lead, Deal, CallLog, Payment, WalletTransaction, AIAgent, Product,
                    Notification, Setting, STAGE_LABEL)
from utils import login_required, current_user, audit, ADMIN_ROLES

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    return redirect(url_for("main.dashboard") if current_user() else url_for("auth.login"))


def _month_start():
    t = date.today()
    return datetime(t.year, t.month, 1)


@bp.route("/dashboard")
@login_required
def dashboard():
    u = current_user()
    mstart = _month_start()
    ystart = datetime(date.today().year, 1, 1)

    active_users = User.query.filter_by(is_active=True).filter(User.role != "customer").count()
    role_counts = dict(db.session.query(User.role, func.count(User.id)).filter_by(is_active=True).group_by(User.role).all())

    calls_mtd = CallLog.query.filter(CallLog.created_at >= mstart).count()
    connected_mtd = CallLog.query.filter(CallLog.created_at >= mstart, CallLog.status == "Connected").count()
    connect_rate = round(100 * connected_mtd / calls_mtd, 1) if calls_mtd else 0.0
    leads_mtd = Lead.query.filter(Lead.created_at >= mstart).count()

    wallet_total = db.session.query(func.coalesce(func.sum(User.wallet_balance), 0)).scalar()
    tx_count = WalletTransaction.query.count()

    revenue_ytd = db.session.query(func.coalesce(func.sum(Deal.value), 0)).filter(
        Deal.stage == "closed_won", Deal.updated_at >= ystart).scalar()
    # monthly revenue sparkline (last 8 months)
    spark = []
    for i in range(7, -1, -1):
        m = (date.today().replace(day=1) - timedelta(days=30 * i)).replace(day=1)
        m_end = (m + timedelta(days=32)).replace(day=1)
        v = db.session.query(func.coalesce(func.sum(Deal.value), 0)).filter(
            Deal.stage == "closed_won", Deal.updated_at >= m, Deal.updated_at < m_end).scalar()
        spark.append(float(v))

    recent_calls = CallLog.query.order_by(CallLog.created_at.desc()).limit(12).all()
    live_feed = recent_calls[:6]
    recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(5).all()

    # wallet trend: last 30 days balance & daily spend
    since = datetime.utcnow() - timedelta(days=30)
    txs = WalletTransaction.query.filter(WalletTransaction.created_at >= since).order_by(WalletTransaction.created_at).all()
    trend = {}
    for t in txs:
        d = t.created_at.date().isoformat()
        row = trend.setdefault(d, {"balance": 0, "spend": 0})
        row["balance"] = t.balance_after
        if t.kind == "debit":
            row["spend"] += t.amount
    wallet_trend = [{"date": k, **v} for k, v in sorted(trend.items())]

    deals_by_product = [[n, int(c)] for n, c in db.session.query(Product.name, func.count(Deal.id)).join(
        Deal, Deal.product_id == Product.id).group_by(Product.name).all()]
    revenue_by_product = [[n, float(v)] for n, v in db.session.query(Product.name, func.coalesce(func.sum(Deal.value), 0)).join(
        Deal, Deal.product_id == Product.id).filter(Deal.stage == "closed_won").group_by(Product.name).all()]

    total_leads = Lead.query.count()
    converted = Lead.query.filter_by(status="Converted").count() + Deal.query.filter_by(stage="closed_won").count()
    conversion = round(100 * converted / total_leads, 1) if total_leads else 0.0
    alerts = []
    if connect_rate < 30:
        alerts.append(("warning", f"Connect rate is {connect_rate}% — optimize call timing and first-touch scripts."))
    if conversion < 5:
        alerts.append(("critical", f"Conversion is {conversion}% — review objection handling and follow-up quality."))
    unassigned = Lead.query.filter(Lead.assigned_to.is_(None)).count()
    if unassigned > 50:
        alerts.append(("warning", f"{unassigned} leads are unassigned — rebalance from Lead Assignment."))
    if not alerts:
        alerts.append(("ok", "All operating metrics are within target."))

    agents = AIAgent.query.order_by(AIAgent.created_at).all()
    agent_split = {
        "Active": sum(1 for a in agents if a.status == "Active"),
        "Inactive": sum(1 for a in agents if a.status != "Active"),
        "Unassigned Products": sum(1 for a in agents if not a.product_id),
    }
    agents_updated_24h = sum(1 for a in agents if a.updated_at and a.updated_at >= datetime.utcnow() - timedelta(days=1))

    return render_template(
        "dashboard.html",
        active_users=active_users, role_counts=role_counts, calls_mtd=calls_mtd, connect_rate=connect_rate,
        leads_mtd=leads_mtd, wallet_total=wallet_total, tx_count=tx_count, revenue_ytd=revenue_ytd,
        spark=spark, recent_calls=recent_calls, live_feed=live_feed, recent_payments=recent_payments,
        wallet_trend=wallet_trend, deals_by_product=deals_by_product, revenue_by_product=revenue_by_product,
        alerts=alerts, conversion=conversion, agents=agents, agent_split=agent_split,
        agents_updated_24h=agents_updated_24h,
    )


@bp.route("/dashboard/live-feed")
@login_required
def live_feed():
    rows = CallLog.query.order_by(CallLog.created_at.desc()).limit(6).all()
    return jsonify([c.to_dict() for c in rows])


@bp.route("/search")
@login_required
def search():
    q = (request.args.get("q") or "").strip()
    results = {"leads": [], "deals": [], "users": [], "products": []}
    if q:
        like = f"%{q}%"
        results["leads"] = [l.to_dict() for l in Lead.query.filter(
            (Lead.name.ilike(like)) | (Lead.phone.ilike(like)) | (Lead.email.ilike(like))).limit(8)]
        results["deals"] = [d.to_dict() for d in Deal.query.filter(
            (Deal.title.ilike(like)) | (Deal.contact_name.ilike(like)) | (Deal.company.ilike(like))).limit(6)]
        results["users"] = [u.to_dict() for u in User.query.filter(
            (User.name.ilike(like)) | (User.email.ilike(like))).limit(5)]
        results["products"] = [p.to_dict() for p in Product.query.filter(
            (Product.name.ilike(like)) | (Product.sku.ilike(like))).limit(5)]
    if request.args.get("format") == "json":
        return jsonify(results)
    return render_template("search.html", q=q, results=results)


# ---------------- notifications ----------------
@bp.route("/notifications")
@login_required
def notifications():
    u = current_user()
    rows = Notification.query.filter_by(user_id=u.id).order_by(Notification.created_at.desc()).limit(30).all()
    if request.args.get("format") == "json":
        return jsonify([{"id": n.id, "title": n.title, "body": n.body, "level": n.level,
                         "is_read": n.is_read, "created_at": n.created_at.isoformat()} for n in rows])
    return render_template("notifications.html", rows=rows)


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notifications_read_all():
    u = current_user()
    Notification.query.filter_by(user_id=u.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"ok": True})


# ---------------- bulletin ----------------
@bp.route("/bulletin", methods=["POST"])
@login_required
def bulletin():
    u = current_user()
    if u.role not in ADMIN_ROLES:
        return jsonify({"error": "forbidden"}), 403
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    recipients = User.query.filter_by(is_active=True).all()
    for r in recipients:
        db.session.add(Notification(user_id=r.id, title=title, body=body, level="info"))
    audit("BULLETIN", f"Bulletin sent: {title}", f"{len(recipients)} recipients")
    db.session.commit()
    flash(f"Bulletin sent to {len(recipients)} users.", "success")
    return redirect(url_for("main.dashboard"))


# ---------------- settings ----------------
@bp.route("/settings")
@login_required
def settings():
    u = current_user()
    tab = request.args.get("tab", "security")
    org = {k: Setting.get(k, "") for k in ("org_name", "wacto_api_key", "meta_token", "fb_page_id",
                                             "fb_form_id", "fb_access_token", "call_target", "conversion_target")}
    return render_template("settings.html", tab=tab, org=org)


@bp.route("/settings/verify-password", methods=["POST"])
@login_required
def verify_password():
    u = current_user()
    data = request.get_json(silent=True) or request.form
    ok = u.check_password(data.get("password") or "")
    return jsonify({"ok": ok})


@bp.route("/settings/password", methods=["POST"])
@login_required
def change_password():
    u = current_user()
    cur = request.form.get("current") or ""
    new = request.form.get("new") or ""
    conf = request.form.get("confirm") or ""
    if not u.check_password(cur):
        flash("Current password is incorrect.", "danger")
    elif len(new) < 6:
        flash("New password must be at least 6 characters.", "danger")
    elif new != conf:
        flash("New passwords do not match.", "danger")
    else:
        u.set_password(new)
        audit("SECURITY", "Password changed")
        db.session.commit()
        flash("Password updated successfully.", "success")
    return redirect(url_for("main.settings", tab="security"))


@bp.route("/settings/preferences", methods=["POST"])
@login_required
def save_preferences():
    u = current_user()
    tab = request.form.get("tab", "notifications")
    if tab == "notifications":
        u.pref_notify_email = bool(request.form.get("notify_email"))
        u.pref_notify_sms = bool(request.form.get("notify_sms"))
        u.pref_notify_push = bool(request.form.get("notify_push"))
    elif tab == "privacy":
        u.pref_privacy_profile = request.form.get("profile_visibility", "team")
    elif tab == "appearance":
        u.pref_dark = request.form.get("theme") == "dark"
    elif tab == "communication":
        u.pref_comm_channel = request.form.get("channel", "whatsapp")
        if u.role in ADMIN_ROLES:
            Setting.put("wacto_api_key", request.form.get("wacto_api_key", ""))
            Setting.put("meta_token", request.form.get("meta_token", ""))
    elif tab == "facebook":
        if u.role in ADMIN_ROLES:
            Setting.put("fb_page_id", request.form.get("fb_page_id", ""))
            Setting.put("fb_form_id", request.form.get("fb_form_id", ""))
            Setting.put("fb_access_token", request.form.get("fb_access_token", ""))
    elif tab == "targets":
        if u.role in ADMIN_ROLES:
            Setting.put("call_target", request.form.get("call_target", "5000"))
            Setting.put("conversion_target", request.form.get("conversion_target", "100"))
            Setting.put("org_name", request.form.get("org_name", "GenAIlakes"))
    audit("UPDATE", f"Settings updated ({tab})")
    db.session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("main.settings", tab=tab))


@bp.route("/settings/theme", methods=["POST"])
@login_required
def toggle_theme():
    u = current_user()
    data = request.get_json(silent=True) or {}
    u.pref_dark = bool(data.get("dark"))
    db.session.commit()
    return jsonify({"ok": True, "dark": u.pref_dark})


# ---------------- help ----------------
HELP_SECTIONS = [
    ("trending-up", "Sales Operations", ["Optimizing lead qualification and conversion strategies",
                                         "Building and managing high-performance sales pipelines",
                                         "Lead scoring algorithms and prioritization framework",
                                         "Multi-channel prospect engagement best practices",
                                         "Sales funnel optimization and conversion rate analysis"]),
    ("users", "CRM & Lead Management", ["Advanced lead segmentation and targeting strategies",
                                        "Customer lifecycle management and retention tactics",
                                        "Automated lead distribution and territory management",
                                        "Prospect nurturing campaigns and drip sequences",
                                        "Integration with existing CRM systems and data migration"]),
    ("bar-chart-3", "Call Intelligence & Analytics", ["Real-time call analytics and performance monitoring",
                                                     "AI-powered conversation intelligence and insights",
                                                     "Sales coaching through call transcript analysis",
                                                     "Competitor mention tracking and market intelligence",
                                                     "Voice sentiment analysis and customer intent detection"]),
    ("shield", "Compliance & Security", ["TCPA and telemarketing compliance requirements",
                                         "Do-Not-Call (DNC) list management and regulations",
                                         "Call recording consent and legal compliance frameworks",
                                         "Data privacy regulations (GDPR, CCPA) and implementation",
                                         "Security protocols and enterprise-grade encryption standards"]),
    ("target", "Sales Performance Management", ["KPI tracking and sales metrics dashboards",
                                                "Team performance benchmarking and scorecards",
                                                "Quota management and commission calculation",
                                                "Sales forecasting and pipeline health indicators",
                                                "Agent productivity optimization strategies"]),
    ("zap", "Enterprise Integration", ["API documentation and integration guidelines",
                                       "Webhook configuration for real-time data sync",
                                       "Single Sign-On (SSO) and authentication setup",
                                       "Third-party integrations (Salesforce, HubSpot, Zoho)",
                                       "Custom workflow automation and business logic"]),
]
FAQS = [
    ("How does the AI-powered lead scoring system work?",
     "Each lead receives a 0-100 score computed from source quality, engagement (calls connected, WhatsApp replies), "
     "deal stage and recency. Scores are recomputed nightly and whenever a call or message is logged."),
    ("What are the compliance requirements for outbound sales calls?",
     "Calls must honour DND/DNC registries, play a recording disclosure, and respect calling-hour windows. "
     "The platform blocks dialing to numbers flagged as DNC and logs consent on every connected call."),
    ("How is conversation intelligence used to improve sales performance?",
     "Connected calls are transcribed and scored (QA score). Coaches review low-scoring calls, and objection "
     "patterns are surfaced in Analytics."),
    ("Can the platform integrate with our existing CRM and sales tools?",
     "Yes. Generate an API key under API Keys and use the REST endpoints under /api/v1 to sync leads, deals and call logs."),
    ("What reporting and analytics capabilities are available for sales leadership?",
     "Analytics provides call and lead volume trends, connection and conversion rates, rep leaderboards and target attainment."),
    ("How does the system handle high-volume outbound calling operations?",
     "AI agents dial in parallel from the campaign queue, respect wallet balance, retry busy/no-answer numbers and hand off hot leads to humans."),
]


@bp.route("/help")
@login_required
def help_page():
    q = (request.args.get("q") or "").strip().lower()
    sections = HELP_SECTIONS
    faqs = FAQS
    if q:
        sections = [(i, t, [a for a in arts if q in a.lower()]) for i, t, arts in HELP_SECTIONS]
        sections = [s for s in sections if s[2]]
        faqs = [f for f in FAQS if q in f[0].lower() or q in f[1].lower()]
    return render_template("help.html", sections=sections, faqs=faqs, q=q)


@bp.route("/help/ticket", methods=["POST"])
@login_required
def help_ticket():
    subject = request.form.get("subject", "").strip()
    if subject:
        audit("SUPPORT", f"Support ticket: {subject}", request.form.get("message", ""))
        db.session.commit()
        flash("Support ticket submitted. Our team will respond within 15 minutes.", "success")
    return redirect(url_for("main.help_page"))


@bp.route("/profile")
@login_required
def profile():
    u = current_user()
    my_calls = CallLog.query.filter_by(user_id=u.id).count()
    my_leads = Lead.query.filter_by(assigned_to=u.id).count()
    my_deals = Deal.query.filter_by(owner_id=u.id).count()
    return render_template("profile.html", my_calls=my_calls, my_leads=my_leads, my_deals=my_deals)


@bp.route("/profile", methods=["POST"])
@login_required
def profile_save():
    u = current_user()
    u.name = request.form.get("name", u.name).strip() or u.name
    u.phone = request.form.get("phone", u.phone)
    audit("UPDATE", "Profile updated")
    db.session.commit()
    flash("Profile saved.", "success")
    return redirect(url_for("main.profile"))
