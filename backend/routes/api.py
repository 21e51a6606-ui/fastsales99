"""Public REST API (v1) secured by API keys generated under /api-keys."""
from datetime import datetime

from flask import Blueprint, request, jsonify

from models import db, Lead, Deal, CallLog, Product, User, AIAgent, LEAD_STATUSES, STAGE_PROB
from utils import api_key_required

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def _page(q, serializer):
    page = request.args.get("page", 1, type=int)
    per = min(request.args.get("per_page", 50, type=int), 200)
    p = q.paginate(page=page, per_page=per, error_out=False)
    return jsonify({"items": [serializer(i) for i in p.items], "page": p.page, "pages": p.pages, "total": p.total})


@bp.route("/ping")
def ping():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat(), "service": "fastsales-api"})


@bp.route("/leads")
@api_key_required("read")
def leads():
    q = Lead.query
    if request.args.get("status"):
        q = q.filter(Lead.status == request.args["status"])
    if request.args.get("assigned_to"):
        q = q.filter(Lead.assigned_to == request.args.get("assigned_to", type=int))
    if request.args.get("phone"):
        q = q.filter(Lead.phone == request.args["phone"])
    return _page(q.order_by(Lead.created_at.desc()), Lead.to_dict)


@bp.route("/leads", methods=["POST"])
@api_key_required("write")
def create_lead():
    data = request.get_json(silent=True) or {}
    name, phone = (data.get("name") or "").strip(), (data.get("phone") or "").strip()
    if not name or not phone:
        return jsonify({"error": "name and phone are required"}), 400
    if Lead.query.filter_by(phone=phone).first():
        return jsonify({"error": "lead with this phone already exists"}), 409
    ld = Lead(name=name, phone=phone, email=data.get("email"), company=data.get("company"),
              source=data.get("source") or "API", priority=data.get("priority") or "Medium",
              product_id=data.get("product_id"), notes=data.get("notes"))
    db.session.add(ld)
    db.session.commit()
    return jsonify(ld.to_dict()), 201


@bp.route("/leads/<int:lid>", methods=["GET", "PATCH"])
@api_key_required("read")
def lead_detail(lid):
    ld = db.session.get(Lead, lid)
    if not ld:
        return jsonify({"error": "not found"}), 404
    if request.method == "PATCH":
        data = request.get_json(silent=True) or {}
        if data.get("status") in LEAD_STATUSES:
            ld.status = data["status"]
        for f in ("name", "email", "company", "priority", "notes"):
            if f in data:
                setattr(ld, f, data[f])
        db.session.commit()
    return jsonify(ld.to_dict())


@bp.route("/deals")
@api_key_required("read")
def deals():
    q = Deal.query
    if request.args.get("stage") in STAGE_PROB:
        q = q.filter(Deal.stage == request.args["stage"])
    return _page(q.order_by(Deal.updated_at.desc()), Deal.to_dict)


@bp.route("/deals", methods=["POST"])
@api_key_required("write")
def create_deal():
    data = request.get_json(silent=True) or {}
    if not data.get("title"):
        return jsonify({"error": "title required"}), 400
    d = Deal(title=data["title"], contact_name=data.get("contact_name"), contact_phone=data.get("contact_phone"),
             company=data.get("company"), value=float(data.get("value") or 0),
             stage=data.get("stage") if data.get("stage") in STAGE_PROB else "qualification",
             product_id=data.get("product_id"), owner_id=data.get("owner_id"), lead_id=data.get("lead_id"))
    db.session.add(d)
    db.session.commit()
    return jsonify(d.to_dict()), 201


@bp.route("/calls")
@api_key_required("read")
def calls():
    q = CallLog.query
    if request.args.get("status"):
        q = q.filter(CallLog.status == request.args["status"])
    return _page(q.order_by(CallLog.created_at.desc()), CallLog.to_dict)


@bp.route("/calls", methods=["POST"])
@api_key_required("calls")
def create_call():
    data = request.get_json(silent=True) or {}
    phone = data.get("phone")
    if not phone:
        return jsonify({"error": "phone required"}), 400
    lead = Lead.query.filter_by(phone=phone).first()
    dur = int(data.get("duration_sec") or 0)
    c = CallLog(lead_id=lead.id if lead else None, contact_name=data.get("contact_name") or (lead.name if lead else None),
                phone=phone, status=data.get("status") or "Connected", duration_sec=dur, cost=round(dur / 60 * 0.9, 2),
                qa_score=data.get("qa_score"), transcript=data.get("transcript"), agent_id=data.get("agent_id"))
    db.session.add(c)
    if lead:
        lead.contacted = True
        lead.contacted_at = datetime.utcnow()
    db.session.commit()
    return jsonify(c.to_dict()), 201


@bp.route("/products")
@api_key_required("read")
def products():
    return jsonify([p.to_dict() for p in Product.query.all()])


@bp.route("/agents")
@api_key_required("read")
def agents():
    return jsonify([a.to_dict() for a in AIAgent.query.all()])


@bp.route("/users")
@api_key_required("admin")
def users():
    return jsonify([u.to_dict() for u in User.query.all()])


@bp.route("/stats")
@api_key_required("read")
def stats():
    total_calls = CallLog.query.count()
    connected = CallLog.query.filter_by(status="Connected").count()
    return jsonify({
        "leads": Lead.query.count(), "deals": Deal.query.count(), "calls": total_calls,
        "connect_rate": round(100 * connected / total_calls, 1) if total_calls else 0,
        "pipeline_value": float(db.session.query(db.func.coalesce(db.func.sum(Deal.value), 0)).filter(
            Deal.stage.notin_(["closed_won", "closed_lost"])).scalar()),
    })
