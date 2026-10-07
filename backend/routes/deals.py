from datetime import datetime, date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import func

from models import db, Deal, Product, User, Lead, CallLog, SalesTarget, DEAL_STAGES, STAGE_PROB, STAGE_LABEL
from utils import login_required, current_user, audit, MANAGEMENT_ROLES

bp = Blueprint("deals", __name__, url_prefix="/deals")


def _scoped_query():
    u = current_user()
    q = Deal.query
    if u.role == "sales_executive":
        q = q.filter(Deal.owner_id == u.id)
    elif u.role == "team_lead":
        ids = [u.id] + [r.id for r in u.reports]
        q = q.filter(Deal.owner_id.in_(ids))
    return q


@bp.route("/")
@login_required
def index():
    q = _scoped_query()
    search = (request.args.get("q") or "").strip()
    rep = request.args.get("rep", type=int)
    stage = request.args.get("stage")
    product = request.args.get("product", type=int)
    view = request.args.get("view", "kanban")
    per_col = request.args.get("per", 15, type=int)
    if search:
        like = f"%{search}%"
        q = q.filter((Deal.title.ilike(like)) | (Deal.contact_name.ilike(like)) | (Deal.company.ilike(like)))
    if rep:
        q = q.filter(Deal.owner_id == rep)
    if stage:
        q = q.filter(Deal.stage == stage)
    if product:
        q = q.filter(Deal.product_id == product)

    all_deals = q.order_by(Deal.updated_at.desc()).all()
    total_count = len(all_deals)
    open_deals = [d for d in all_deals if d.stage not in ("closed_won", "closed_lost")]
    total_pipeline = sum(d.value for d in open_deals)
    weighted = sum(d.weighted for d in open_deals)
    won = [d for d in all_deals if d.stage == "closed_won"]
    lost = [d for d in all_deals if d.stage == "closed_lost"]
    win_rate = round(100 * len(won) / (len(won) + len(lost)), 1) if (won or lost) else 0.0
    won_value = sum(d.value for d in won)
    mstart = date.today().replace(day=1)
    mend = (mstart + timedelta(days=32)).replace(day=1)
    closing = [d for d in open_deals if d.expected_close and mstart <= d.expected_close < mend]
    closing_value = sum(d.value for d in closing)

    columns = []
    for key, label, prob in DEAL_STAGES:
        items = [d for d in all_deals if d.stage == key]
        columns.append({"key": key, "label": label, "prob": prob, "count": len(items),
                        "value": sum(d.value for d in items), "deals": items[:per_col]})

    reps = User.query.filter(User.role.in_(["manager", "team_lead", "sales_executive", "admin", "super_admin"]),
                             User.is_active == True).order_by(User.name).all()
    products = Product.query.order_by(Product.name).all()

    # targets & incentives
    period = date.today().strftime("%Y-%m")
    targets = SalesTarget.query.filter_by(period=period).all()
    target_rows = []
    for t in targets:
        achieved = db.session.query(func.coalesce(func.sum(Deal.value), 0)).filter(
            Deal.owner_id == t.user_id, Deal.stage == "closed_won",
            Deal.updated_at >= datetime(date.today().year, date.today().month, 1)).scalar()
        pct = round(100 * achieved / t.target_amount, 1) if t.target_amount else 0
        target_rows.append({"user": t.user, "target": t.target_amount, "achieved": achieved, "pct": pct,
                            "incentive": round(achieved * t.incentive_pct / 100, 2), "id": t.id,
                            "incentive_pct": t.incentive_pct})

    return render_template("deals.html", columns=columns, deals=all_deals, total_count=total_count,
                           total_pipeline=total_pipeline, weighted=weighted, win_rate=win_rate, won_value=won_value,
                           won_count=len(won), closing_value=closing_value, closing_count=len(closing),
                           reps=reps, products=products, view=view, per_col=per_col, search=search,
                           sel_rep=rep, sel_stage=stage, sel_product=product, target_rows=target_rows,
                           active_stages=len([c for c in columns if c["key"] not in ("closed_won", "closed_lost")]))


@bp.route("/new", methods=["POST"])
@login_required
def create():
    u = current_user()
    title = request.form.get("title", "").strip()
    contact = request.form.get("contact_name", "").strip()
    if not title and contact:
        title = f"{contact} - Deal"
    if not title:
        flash("Deal title is required.", "danger")
        return redirect(url_for("deals.index"))
    d = Deal(title=title, contact_name=contact, contact_phone=request.form.get("contact_phone"),
             company=request.form.get("company"), value=float(request.form.get("value") or 0),
             stage=request.form.get("stage") or "qualification",
             product_id=request.form.get("product_id", type=int) or None,
             owner_id=request.form.get("owner_id", type=int) or u.id,
             notes=request.form.get("notes"))
    ec = request.form.get("expected_close")
    if ec:
        d.expected_close = date.fromisoformat(ec)
    db.session.add(d)
    db.session.flush()
    audit("CREATE", f"Deal created: {d.title}", f"value={d.value} stage={d.stage}")
    db.session.commit()
    flash("Deal created.", "success")
    return redirect(url_for("deals.index"))


@bp.route("/<int:deal_id>/stage", methods=["POST"])
@login_required
def move_stage(deal_id):
    d = db.session.get(Deal, deal_id)
    if not d:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or request.form
    stage = data.get("stage")
    if stage not in STAGE_PROB:
        return jsonify({"error": "invalid stage"}), 400
    old = d.stage
    d.stage = stage
    d.updated_at = datetime.utcnow()
    if stage == "closed_won" and d.lead:
        d.lead.status = "Converted"
    audit("UPDATE", f"Deal moved: {d.title}", f"{STAGE_LABEL.get(old)} -> {STAGE_LABEL.get(stage)}")
    db.session.commit()
    return jsonify({"ok": True, "deal": d.to_dict()})


@bp.route("/<int:deal_id>/update", methods=["POST"])
@login_required
def update(deal_id):
    d = db.session.get(Deal, deal_id)
    if not d:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or request.form
    for f in ("title", "contact_name", "contact_phone", "company", "notes"):
        if f in data:
            setattr(d, f, data.get(f))
    if "value" in data:
        d.value = float(data.get("value") or 0)
    if data.get("owner_id"):
        d.owner_id = int(data["owner_id"])
    if data.get("product_id"):
        d.product_id = int(data["product_id"])
    if data.get("expected_close"):
        d.expected_close = date.fromisoformat(data["expected_close"])
    audit("UPDATE", f"Deal updated: {d.title}")
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True, "deal": d.to_dict()})
    flash("Deal updated.", "success")
    return redirect(url_for("deals.index"))


@bp.route("/<int:deal_id>/delete", methods=["POST"])
@login_required
def delete(deal_id):
    d = db.session.get(Deal, deal_id)
    if d:
        audit("DELETE", f"Deal deleted: {d.title}")
        db.session.delete(d)
        db.session.commit()
    if request.is_json:
        return jsonify({"ok": True})
    flash("Deal deleted.", "info")
    return redirect(url_for("deals.index"))


@bp.route("/<int:deal_id>/log-call", methods=["POST"])
@login_required
def log_call(deal_id):
    d = db.session.get(Deal, deal_id)
    if not d:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or request.form
    status = data.get("status", "Connected")
    dur = int(data.get("duration") or 0)
    c = CallLog(lead_id=d.lead_id, user_id=current_user().id, contact_name=d.contact_name, phone=d.contact_phone,
                status=status, duration_sec=dur, cost=round(dur / 60 * 0.9, 2), transcript=data.get("notes"))
    db.session.add(c)
    if d.lead:
        d.lead.contacted = True
        d.lead.contacted_at = datetime.utcnow()
        if d.lead.status == "New":
            d.lead.status = "Contacted"
    audit("CALL", f"Call logged for {d.contact_name}", f"{status} {dur}s")
    db.session.commit()
    return jsonify({"ok": True, "call": c.to_dict()})


@bp.route("/<int:deal_id>")
@login_required
def detail(deal_id):
    d = db.session.get(Deal, deal_id)
    if not d:
        return jsonify({"error": "not found"}), 404
    calls = CallLog.query.filter_by(lead_id=d.lead_id).order_by(CallLog.created_at.desc()).limit(10).all() if d.lead_id else []
    return jsonify({"deal": d.to_dict(), "notes": d.notes, "calls": [c.to_dict() for c in calls]})


@bp.route("/targets", methods=["POST"])
@login_required
def save_target():
    u = current_user()
    if u.role not in MANAGEMENT_ROLES:
        flash("Only management can set targets.", "danger")
        return redirect(url_for("deals.index"))
    uid = request.form.get("user_id", type=int)
    period = request.form.get("period") or date.today().strftime("%Y-%m")
    t = SalesTarget.query.filter_by(user_id=uid, period=period).first()
    if not t:
        t = SalesTarget(user_id=uid, period=period)
        db.session.add(t)
    t.target_amount = float(request.form.get("target_amount") or 0)
    t.incentive_pct = float(request.form.get("incentive_pct") or 0)
    audit("UPDATE", "Sales target saved", f"user={uid} period={period} target={t.target_amount}")
    db.session.commit()
    flash("Target saved.", "success")
    return redirect(url_for("deals.index"))
