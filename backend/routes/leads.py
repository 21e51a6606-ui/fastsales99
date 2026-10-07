import csv
import io
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response

from models import db, Lead, User, Product, AssignmentHistory, CallLog, Deal, LEAD_STATUSES, CALL_STATUSES
from utils import login_required, role_required, current_user, audit

bp = Blueprint("leads", __name__, url_prefix="/dashboard/admin/lead-assignment")

PAGE_SIZE = 25


def _filtered(base):
    q = (request.args.get("q") or "").strip()
    pr = request.args.get("priority")
    src = request.args.get("source")
    prod = request.args.get("product", type=int)
    st = request.args.get("status")
    if q:
        like = f"%{q}%"
        base = base.filter((Lead.name.ilike(like)) | (Lead.phone.ilike(like)) | (Lead.email.ilike(like)))
    if pr:
        base = base.filter(Lead.priority == pr)
    if src:
        base = base.filter(Lead.source == src)
    if prod:
        base = base.filter(Lead.product_id == prod)
    if st:
        base = base.filter(Lead.status == st)
    return base


@bp.route("/")
@login_required
def index():
    u = current_user()
    tab = request.args.get("tab", "incoming")
    page = request.args.get("page", 1, type=int)
    base = Lead.query
    if u.role == "sales_executive":
        base = base.filter(Lead.assigned_to == u.id)
    incoming_count = Lead.query.filter(Lead.assigned_to.is_(None)).count()
    all_count = Lead.query.count()
    high_count = Lead.query.filter_by(priority="High").filter(Lead.assigned_to.is_(None)).count()
    assignable = User.query.filter(User.is_active == True,
                                   User.role.in_(["manager", "team_lead", "sales_executive"])).order_by(User.name).all()
    if tab == "incoming":
        base = base.filter(Lead.assigned_to.is_(None))
    base = _filtered(base).order_by(Lead.created_at.desc())
    pagination = base.paginate(page=page, per_page=PAGE_SIZE, error_out=False)
    history = AssignmentHistory.query.order_by(AssignmentHistory.created_at.desc()).limit(12).all()
    sources = [r[0] for r in db.session.query(Lead.source).distinct().order_by(Lead.source)]
    products = Product.query.order_by(Product.name).all()
    return render_template("leads.html", tab=tab, pagination=pagination, leads=pagination.items,
                           incoming_count=incoming_count, all_count=all_count, high_count=high_count,
                           assignable=assignable, history=history, sources=sources, products=products,
                           statuses=LEAD_STATUSES, call_statuses=CALL_STATUSES, args=request.args)


@bp.route("/assign", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager", "team_lead")
def assign():
    data = request.get_json(silent=True) or {}
    ids = [int(i) for i in (data.get("lead_ids") or request.form.getlist("lead_ids"))]
    uid = data.get("user_id") or request.form.get("user_id", type=int)
    method = data.get("method", "manual")
    if not ids or not uid:
        return jsonify({"error": "lead_ids and user_id required"}), 400
    target = db.session.get(User, int(uid))
    if not target:
        return jsonify({"error": "user not found"}), 404
    leads = Lead.query.filter(Lead.id.in_(ids)).all()
    for ld in leads:
        db.session.add(AssignmentHistory(lead_id=ld.id, from_user_id=ld.assigned_to or current_user().id,
                                         to_user_id=target.id, method=method,
                                         note=f"Manual assignment for product {ld.product.name if ld.product else '-'}"))
        ld.assigned_to = target.id
    audit("ASSIGN", f"{len(leads)} leads assigned to {target.name}")
    db.session.commit()
    return jsonify({"ok": True, "assigned": len(leads)})


@bp.route("/auto-assign", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def auto_assign():
    """Round-robin all unassigned leads across active sales executives."""
    execs = User.query.filter_by(role="sales_executive", is_active=True).order_by(User.id).all()
    if not execs:
        return jsonify({"error": "no active sales executives"}), 400
    pool = Lead.query.filter(Lead.assigned_to.is_(None)).order_by(Lead.priority.desc(), Lead.created_at).all()
    for i, ld in enumerate(pool):
        tgt = execs[i % len(execs)]
        ld.assigned_to = tgt.id
        db.session.add(AssignmentHistory(lead_id=ld.id, from_user_id=current_user().id, to_user_id=tgt.id,
                                         method="round_robin", note="Automatic round-robin distribution"))
    audit("ASSIGN", f"Auto-assigned {len(pool)} leads", f"{len(execs)} executives")
    db.session.commit()
    return jsonify({"ok": True, "assigned": len(pool), "executives": len(execs)})


@bp.route("/product-move", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def product_move():
    src = request.form.get("from_product", type=int)
    dst = request.form.get("to_product", type=int)
    if not dst:
        flash("Select a destination product.", "danger")
        return redirect(url_for("leads.index", tab="product_move"))
    q = Lead.query
    if src:
        q = q.filter(Lead.product_id == src)
    else:
        q = q.filter(Lead.product_id.is_(None))
    n = q.update({"product_id": dst}, synchronize_session=False)
    audit("UPDATE", f"Moved {n} leads to product #{dst}")
    db.session.commit()
    flash(f"Moved {n} leads.", "success")
    return redirect(url_for("leads.index", tab="product_move"))


@bp.route("/add", methods=["POST"])
@login_required
def add():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    if not name or not phone:
        flash("Name and phone are required.", "danger")
        return redirect(url_for("leads.index"))
    if Lead.query.filter_by(phone=phone).first():
        flash("A lead with this phone already exists.", "warning")
        return redirect(url_for("leads.index"))
    ld = Lead(name=name, phone=phone, email=request.form.get("email"), company=request.form.get("company"),
              source=request.form.get("source") or "Others", priority=request.form.get("priority") or "Medium",
              product_id=request.form.get("product_id", type=int) or None,
              assigned_to=request.form.get("assigned_to", type=int) or None, notes=request.form.get("notes"))
    db.session.add(ld)
    db.session.flush()
    audit("CREATE", f"Lead added: {name}")
    db.session.commit()
    flash("Lead added.", "success")
    return redirect(url_for("leads.index"))


@bp.route("/bulk-upload", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def bulk_upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".csv"):
        flash("Upload a .csv file with columns: name, phone, email, company, source, priority.", "danger")
        return redirect(url_for("leads.index"))
    text = f.read().decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    product_id = request.form.get("product_id", type=int) or None
    added = skipped = 0
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        name, phone = row.get("name"), row.get("phone")
        if not name or not phone:
            skipped += 1
            continue
        if not phone.startswith("+"):
            phone = "+91" + phone.lstrip("0")
        if Lead.query.filter_by(phone=phone).first():
            skipped += 1
            continue
        db.session.add(Lead(name=name, phone=phone, email=row.get("email"), company=row.get("company"),
                            source=row.get("source") or "Bulk Upload",
                            priority=(row.get("priority") or "Medium").title(), product_id=product_id))
        added += 1
    audit("IMPORT", f"Bulk upload: {added} leads added", f"{skipped} skipped")
    db.session.commit()
    flash(f"Imported {added} leads ({skipped} skipped).", "success")
    return redirect(url_for("leads.index"))


@bp.route("/template.csv")
@login_required
def template_csv():
    return Response("name,phone,email,company,source,priority\nJane Doe,+919999999999,jane@example.com,Acme,Website,High\n",
                    mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=leads_template.csv"})


@bp.route("/export.csv")
@login_required
def export_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "name", "phone", "email", "company", "source", "status", "priority", "score", "product",
                "assigned_to", "contacted", "created_at"])
    for ld in _filtered(Lead.query).order_by(Lead.created_at.desc()).all():
        w.writerow([ld.id, ld.name, ld.phone, ld.email, ld.company, ld.source, ld.status, ld.priority, ld.score,
                    ld.product.name if ld.product else "", ld.assignee.name if ld.assignee else "",
                    ld.contacted, ld.created_at.isoformat()])
    audit("EXPORT", "Leads exported to CSV")
    db.session.commit()
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=leads.csv"})


@bp.route("/<int:lead_id>")
@login_required
def detail(lead_id):
    ld = db.session.get(Lead, lead_id)
    if not ld:
        return jsonify({"error": "not found"}), 404
    calls = CallLog.query.filter_by(lead_id=ld.id).order_by(CallLog.created_at.desc()).all()
    hist = AssignmentHistory.query.filter_by(lead_id=ld.id).order_by(AssignmentHistory.created_at.desc()).all()
    return jsonify({"lead": ld.to_dict(), "notes": ld.notes, "calls": [c.to_dict() for c in calls],
                    "history": [{"to": h.to_user.name if h.to_user else None,
                                 "from": h.from_user.name if h.from_user else None, "method": h.method,
                                 "at": h.created_at.isoformat()} for h in hist],
                    "deals": [d.to_dict() for d in ld.deals]})


@bp.route("/<int:lead_id>/update", methods=["POST"])
@login_required
def update(lead_id):
    ld = db.session.get(Lead, lead_id)
    if not ld:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or request.form
    for f in ("name", "email", "phone", "company", "source", "priority", "notes"):
        if f in data and data.get(f) is not None:
            setattr(ld, f, data.get(f))
    if data.get("status") in LEAD_STATUSES:
        ld.status = data["status"]
        if ld.status != "New":
            ld.contacted = True
            ld.contacted_at = ld.contacted_at or datetime.utcnow()
    if "score" in data:
        ld.score = max(0, min(100, int(data.get("score") or 0)))
    if data.get("product_id"):
        ld.product_id = int(data["product_id"])
    audit("UPDATE", f"Lead updated: {ld.name}")
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True, "lead": ld.to_dict()})
    flash("Lead updated.", "success")
    return redirect(url_for("leads.index", tab=request.form.get("tab", "all")))


@bp.route("/<int:lead_id>/call", methods=["POST"])
@login_required
def log_call(lead_id):
    ld = db.session.get(Lead, lead_id)
    if not ld:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or request.form
    status = data.get("status") or "Connected"
    if status not in CALL_STATUSES:
        return jsonify({"error": "bad status"}), 400
    dur = int(data.get("duration") or 0) if status == "Connected" else 0
    c = CallLog(lead_id=ld.id, user_id=current_user().id, contact_name=ld.name, phone=ld.phone, status=status,
                duration_sec=dur, cost=round(dur / 60 * 0.9, 2), transcript=data.get("notes"))
    db.session.add(c)
    ld.contacted = True
    ld.contacted_at = datetime.utcnow()
    if ld.status == "New":
        ld.status = "Contacted"
    if data.get("lead_status") in LEAD_STATUSES:
        ld.status = data["lead_status"]
    # simple scoring
    ld.score = max(0, min(100, (ld.score or 50) + (8 if status == "Connected" else -2)))
    audit("CALL", f"Call with {ld.name} marked {status}", f"{dur}s")
    db.session.commit()
    return jsonify({"ok": True, "call": c.to_dict(), "lead": ld.to_dict()})


@bp.route("/<int:lead_id>/convert", methods=["POST"])
@login_required
def convert(lead_id):
    ld = db.session.get(Lead, lead_id)
    if not ld:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or request.form
    d = Deal(title=f"{ld.name} - Deal", contact_name=ld.name, contact_phone=ld.phone, company=ld.company,
             value=float(data.get("value") or 0), stage="qualification", product_id=ld.product_id,
             owner_id=ld.assigned_to or current_user().id, lead_id=ld.id)
    db.session.add(d)
    ld.status = "Interested" if ld.status in ("New", "Contacted") else ld.status
    audit("CREATE", f"Lead converted to deal: {ld.name}")
    db.session.commit()
    return jsonify({"ok": True, "deal": d.to_dict()})


@bp.route("/<int:lead_id>/delete", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def delete(lead_id):
    ld = db.session.get(Lead, lead_id)
    if ld:
        audit("DELETE", f"Lead deleted: {ld.name}")
        AssignmentHistory.query.filter_by(lead_id=ld.id).delete()
        CallLog.query.filter_by(lead_id=ld.id).update({"lead_id": None})
        Deal.query.filter_by(lead_id=ld.id).update({"lead_id": None})
        db.session.delete(ld)
        db.session.commit()
    return jsonify({"ok": True})


@bp.route("/bulk-delete", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def bulk_delete():
    data = request.get_json(silent=True) or {}
    ids = [int(i) for i in data.get("lead_ids", [])]
    if ids:
        AssignmentHistory.query.filter(AssignmentHistory.lead_id.in_(ids)).delete(synchronize_session=False)
        CallLog.query.filter(CallLog.lead_id.in_(ids)).update({"lead_id": None}, synchronize_session=False)
        Deal.query.filter(Deal.lead_id.in_(ids)).update({"lead_id": None}, synchronize_session=False)
        n = Lead.query.filter(Lead.id.in_(ids)).delete(synchronize_session=False)
        audit("DELETE", f"Bulk deleted {n} leads")
        db.session.commit()
    return jsonify({"ok": True, "deleted": len(ids)})


@bp.route("/history")
@login_required
def history():
    rows = AssignmentHistory.query.order_by(AssignmentHistory.created_at.desc()).limit(200).all()
    return render_template("assignment_history.html", rows=rows)
