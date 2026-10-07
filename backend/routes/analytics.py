from datetime import datetime, timedelta, date

from flask import Blueprint, render_template, request, jsonify
from sqlalchemy import func

from models import db, CallLog, Lead, Deal, User, Setting
from utils import login_required


bp = Blueprint("analytics", __name__, url_prefix="/analytics")


def _range():
    rng = request.args.get("range", "30")
    if rng == "custom":
        try:
            start = datetime.fromisoformat(request.args.get("start"))
            end = datetime.fromisoformat(request.args.get("end")) + timedelta(days=1)
        except (TypeError, ValueError):
            start, end = datetime.utcnow() - timedelta(days=30), datetime.utcnow()
    else:
        days = int(rng) if rng.isdigit() else 30
        end = datetime.utcnow() + timedelta(minutes=1)
        start = end - timedelta(days=days)
    return start, end, rng


def compute(start, end):
    calls_q = CallLog.query.filter(CallLog.created_at >= start, CallLog.created_at < end)
    total_calls = calls_q.count()
    connected = calls_q.filter(CallLog.status == "Connected").count()
    conn_rate = round(100 * connected / total_calls, 1) if total_calls else 0.0
    total_leads = Lead.query.filter(Lead.created_at >= start, Lead.created_at < end).count()
    converted = Deal.query.filter(Deal.stage == "closed_won", Deal.updated_at >= start, Deal.updated_at < end).count()
    conv_rate = round(100 * converted / total_leads, 1) if total_leads else 0.0
    avg_qa = db.session.query(func.avg(CallLog.qa_score)).filter(
        CallLog.created_at >= start, CallLog.created_at < end, CallLog.qa_score.isnot(None)).scalar() or 0
    avg_dur = db.session.query(func.avg(CallLog.duration_sec)).filter(
        CallLog.created_at >= start, CallLog.created_at < end, CallLog.status == "Connected").scalar() or 0
    call_target = int(Setting.get("call_target", "5000"))
    conv_target = int(Setting.get("conversion_target", "100"))

    # daily series
    days = []
    d = start.date()
    while d < end.date() + timedelta(days=1) and len(days) < 400:
        days.append(d)
        d += timedelta(days=1)
    by_day = {x: {"calls": 0, "connected": 0, "leads": 0, "converted": 0} for x in days}
    for c in calls_q.all():
        k = c.created_at.date()
        if k in by_day:
            by_day[k]["calls"] += 1
            if c.status == "Connected":
                by_day[k]["connected"] += 1
    for l in Lead.query.filter(Lead.created_at >= start, Lead.created_at < end).all():
        k = l.created_at.date()
        if k in by_day:
            by_day[k]["leads"] += 1
    for dl in Deal.query.filter(Deal.stage == "closed_won", Deal.updated_at >= start, Deal.updated_at < end).all():
        k = dl.updated_at.date()
        if k in by_day:
            by_day[k]["converted"] += 1
    series = []
    for k in days:
        row = by_day[k]
        series.append({"date": k.isoformat(), **row,
                       "conn_rate": round(100 * row["connected"] / row["calls"], 1) if row["calls"] else 0,
                       "conv_rate": round(100 * row["converted"] / row["leads"], 1) if row["leads"] else 0})

    status_split = dict(db.session.query(CallLog.status, func.count(CallLog.id)).filter(
        CallLog.created_at >= start, CallLog.created_at < end).group_by(CallLog.status).all())
    lead_status = dict(db.session.query(Lead.status, func.count(Lead.id)).group_by(Lead.status).all())
    source_split = dict(db.session.query(Lead.source, func.count(Lead.id)).group_by(Lead.source).all())

    # rep leaderboard
    reps = User.query.filter(User.role.in_(["manager", "team_lead", "sales_executive"]), User.is_active == True).all()
    board = []
    for r in reps:
        rc = CallLog.query.filter(CallLog.user_id == r.id, CallLog.created_at >= start, CallLog.created_at < end)
        tc = rc.count()
        cc = rc.filter(CallLog.status == "Connected").count()
        won = db.session.query(func.coalesce(func.sum(Deal.value), 0)).filter(
            Deal.owner_id == r.id, Deal.stage == "closed_won", Deal.updated_at >= start, Deal.updated_at < end).scalar()
        board.append({"name": r.name, "role": r.role_label, "calls": tc, "connected": cc,
                      "rate": round(100 * cc / tc, 1) if tc else 0, "won": float(won),
                      "leads": Lead.query.filter_by(assigned_to=r.id).count()})
    board.sort(key=lambda x: (-x["won"], -x["connected"]))

    return {
        "total_calls": total_calls, "connected": connected, "conn_rate": conn_rate, "total_leads": total_leads,
        "converted": converted, "conv_rate": conv_rate, "avg_qa": round(float(avg_qa), 1),
        "avg_dur": int(avg_dur), "call_target": call_target, "conv_target": conv_target,
        "call_pct": round(100 * total_calls / call_target, 1) if call_target else 0,
        "conv_pct": round(100 * converted / conv_target, 1) if conv_target else 0,
        "series": series, "status_split": status_split, "lead_status": lead_status,
        "source_split": source_split, "board": board,
    }


@bp.route("/")
@login_required
def index():
    start, end, rng = _range()
    data = compute(start, end)
    return render_template("analytics.html", data=data, rng=rng, start=start.date().isoformat(),
                           end=(end - timedelta(days=1)).date().isoformat())


@bp.route("/data")
@login_required
def data():
    start, end, _ = _range()
    return jsonify(compute(start, end))
