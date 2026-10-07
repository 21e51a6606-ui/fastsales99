from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from models import db, AIAgent, Product, CallLog
from utils import login_required, role_required, audit

bp = Blueprint("agents", __name__, url_prefix="/ai-agents")

VOICES = ["Female - Indian English", "Male - Indian English", "Female - Hindi", "Male - Hindi", "Female - US English"]


@bp.route("/")
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    prod = request.args.get("product", type=int)
    base = AIAgent.query
    if q:
        base = base.filter(AIAgent.name.ilike(f"%{q}%"))
    if prod:
        base = base.filter(AIAgent.product_id == prod)
    agents = base.order_by(AIAgent.created_at).all()
    calls = {a.id: CallLog.query.filter_by(agent_id=a.id).count() for a in agents}
    products = Product.query.order_by(Product.name).all()
    return render_template("agents.html", agents=agents, products=products, calls=calls, voices=VOICES, q=q, prod=prod)


@bp.route("/add", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def add():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Agent name is required.", "danger")
        return redirect(url_for("agents.index"))
    a = AIAgent(name=name, description=request.form.get("description"), status=request.form.get("status") or "Active",
                voice=request.form.get("voice") or VOICES[0], system_prompt=request.form.get("system_prompt"),
                product_id=request.form.get("product_id", type=int) or None)
    db.session.add(a)
    db.session.flush()
    audit("CREATE", f"AI agent created: {name}")
    db.session.commit()
    flash("Agent added.", "success")
    return redirect(url_for("agents.index"))


@bp.route("/<int:aid>/update", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def update(aid):
    a = db.session.get(AIAgent, aid)
    if not a:
        flash("Agent not found.", "danger")
        return redirect(url_for("agents.index"))
    a.name = request.form.get("name", a.name).strip() or a.name
    a.description = request.form.get("description", a.description)
    a.status = request.form.get("status", a.status)
    a.voice = request.form.get("voice", a.voice)
    a.system_prompt = request.form.get("system_prompt", a.system_prompt)
    a.product_id = request.form.get("product_id", type=int) or None
    audit("UPDATE", f"AI agent updated: {a.name}")
    db.session.commit()
    flash("Agent updated.", "success")
    return redirect(url_for("agents.index"))


@bp.route("/<int:aid>/toggle", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def toggle(aid):
    a = db.session.get(AIAgent, aid)
    if not a:
        return jsonify({"error": "not found"}), 404
    a.status = "Inactive" if a.status == "Active" else "Active"
    audit("UPDATE", f"AI agent {a.status.lower()}: {a.name}")
    db.session.commit()
    return jsonify({"ok": True, "status": a.status})


@bp.route("/<int:aid>/delete", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def delete(aid):
    a = db.session.get(AIAgent, aid)
    if a:
        CallLog.query.filter_by(agent_id=a.id).update({"agent_id": None})
        audit("DELETE", f"AI agent deleted: {a.name}")
        db.session.delete(a)
        db.session.commit()
        flash("Agent deleted.", "info")
    return redirect(url_for("agents.index"))


@bp.route("/<int:aid>/test", methods=["POST"])
@login_required
def test_agent(aid):
    """Simulated conversation turn with the agent (rule-based demo responder)."""
    a = db.session.get(AIAgent, aid)
    if not a:
        return jsonify({"error": "not found"}), 404
    msg = ((request.get_json(silent=True) or {}).get("message") or "").lower()
    prod = a.product.name if a.product else "our program"
    if any(w in msg for w in ("price", "cost", "fee")):
        reply = f"The {prod} is priced at ₹{a.product.price:,.0f} with flexible EMI options." if a.product else "Let me connect you with a counsellor for pricing."
    elif any(w in msg for w in ("hi", "hello", "hey")):
        reply = f"Hello! I'm {a.name}, your assistant for {prod}. How can I help you today?"
    elif "when" in msg or "start" in msg:
        reply = "The next cohort starts on the 20th. Would you like me to reserve a seat for you?"
    elif "yes" in msg:
        reply = "Great! I've noted your interest. A counsellor will call you shortly to complete enrolment."
    else:
        reply = f"Thanks for asking. {prod} is designed for working professionals; shall I share the brochure on WhatsApp?"
    return jsonify({"reply": reply})
