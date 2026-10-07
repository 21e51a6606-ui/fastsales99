from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from models import db, User, Lead, AssignmentHistory, Deal, CallLog, ROLE_LABELS
from utils import login_required, role_required, current_user, audit, ADMIN_ROLES, MANAGEMENT_ROLES

bp = Blueprint("employees", __name__, url_prefix="/user-management")

STAFF_ROLES = ["manager", "team_lead", "sales_executive", "admin"]


@bp.route("/")
@login_required
@role_required("super_admin", "admin", "manager", "team_lead")
def index():
    tab = request.args.get("tab", "hierarchy")
    q = (request.args.get("q") or "").strip()
    users = User.query.filter(User.role != "customer").order_by(User.role, User.name).all()
    if q:
        like = q.lower()
        users = [u for u in users if like in u.name.lower() or like in u.email.lower() or like in (u.department or "").lower()]
    managers = [u for u in users if u.role == "manager"]
    unplaced = [u for u in users if u.role in ("team_lead", "sales_executive") and not u.manager_id]
    stats = {}
    for u in users:
        stats[u.id] = {"leads": Lead.query.filter_by(assigned_to=u.id).count(),
                       "deals": Deal.query.filter_by(owner_id=u.id).count(),
                       "calls": CallLog.query.filter_by(user_id=u.id).count()}
    return render_template("employees.html", tab=tab, q=q, users=users, managers=managers, unplaced=unplaced,
                           stats=stats, roles=STAFF_ROLES, ROLE_LABELS=ROLE_LABELS)


@bp.route("/add", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def add():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "sales_executive")
    if not name or not email:
        flash("Name and email are required.", "danger")
        return redirect(url_for("employees.index", tab="employees"))
    if User.query.filter_by(email=email).first():
        flash("Email already exists.", "danger")
        return redirect(url_for("employees.index", tab="employees"))
    if role not in STAFF_ROLES or (role == "admin" and current_user().role != "super_admin"):
        flash("Invalid role.", "danger")
        return redirect(url_for("employees.index", tab="employees"))
    u = User(name=name, email=email, phone=request.form.get("phone"), role=role,
             department=request.form.get("department") or "Sales",
             manager_id=request.form.get("manager_id", type=int) or None)
    u.set_password(request.form.get("password") or "welcome123")
    db.session.add(u)
    db.session.flush()
    audit("CREATE", f"Employee added: {name}", f"role={role}")
    db.session.commit()
    flash(f"{name} added as {ROLE_LABELS[role]}.", "success")
    return redirect(url_for("employees.index", tab="employees"))


@bp.route("/<int:uid>/update", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def update(uid):
    u = db.session.get(User, uid)
    if not u:
        flash("User not found.", "danger")
        return redirect(url_for("employees.index"))
    u.name = request.form.get("name", u.name).strip() or u.name
    u.phone = request.form.get("phone", u.phone)
    u.department = request.form.get("department", u.department)
    role = request.form.get("role")
    if role in STAFF_ROLES and (role != "admin" or current_user().role == "super_admin"):
        u.role = role
    mid = request.form.get("manager_id", type=int)
    u.manager_id = mid or None
    if request.form.get("password"):
        u.set_password(request.form["password"])
    audit("UPDATE", f"Employee updated: {u.name}")
    db.session.commit()
    flash("Employee updated.", "success")
    return redirect(url_for("employees.index", tab="employees"))


@bp.route("/<int:uid>/toggle", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def toggle(uid):
    u = db.session.get(User, uid)
    if not u or u.id == current_user().id:
        return jsonify({"error": "cannot change this user"}), 400
    u.is_active = not u.is_active
    audit("UPDATE", f"Employee {'activated' if u.is_active else 'deactivated'}: {u.name}")
    db.session.commit()
    return jsonify({"ok": True, "is_active": u.is_active})


@bp.route("/<int:uid>/delete", methods=["POST"])
@login_required
@role_required("super_admin")
def delete(uid):
    u = db.session.get(User, uid)
    if not u or u.id == current_user().id:
        flash("Cannot delete this user.", "danger")
        return redirect(url_for("employees.index"))
    Lead.query.filter_by(assigned_to=u.id).update({"assigned_to": None})
    User.query.filter_by(manager_id=u.id).update({"manager_id": None})
    audit("DELETE", f"Employee deleted: {u.name}")
    db.session.delete(u)
    db.session.commit()
    flash("Employee removed; their leads are now unassigned.", "info")
    return redirect(url_for("employees.index", tab="employees"))


@bp.route("/<int:uid>/assign-lead", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager", "team_lead")
def assign_lead(uid):
    """Assign N unassigned leads (round-robin from the pool) to this employee."""
    u = db.session.get(User, uid)
    if not u:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or request.form
    n = int(data.get("count") or 10)
    pool = Lead.query.filter(Lead.assigned_to.is_(None)).order_by(Lead.priority.desc(), Lead.created_at).limit(n).all()
    for ld in pool:
        ld.assigned_to = u.id
        db.session.add(AssignmentHistory(lead_id=ld.id, from_user_id=current_user().id, to_user_id=u.id,
                                         method="manual", note="Assigned from Employee Management"))
    audit("ASSIGN", f"{len(pool)} leads assigned to {u.name}")
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True, "assigned": len(pool)})
    flash(f"{len(pool)} leads assigned to {u.name}.", "success")
    return redirect(url_for("employees.index"))
