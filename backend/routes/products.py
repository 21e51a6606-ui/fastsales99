from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from models import db, Product, User, Lead, Deal, AIAgent
from utils import login_required, role_required, audit

bp = Blueprint("products", __name__, url_prefix="/products")

CATEGORIES = ["Software", "Education", "Services", "Hardware", "Others"]


@bp.route("/")
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status")
    cat = request.args.get("category")
    base = Product.query
    if q:
        like = f"%{q}%"
        base = base.filter((Product.name.ilike(like)) | (Product.sku.ilike(like)))
    if status:
        base = base.filter(Product.status == status)
    if cat:
        base = base.filter(Product.category == cat)
    products = base.order_by(Product.created_at.desc()).all()
    stats = {p.id: {"leads": Lead.query.filter_by(product_id=p.id).count(),
                    "deals": Deal.query.filter_by(product_id=p.id).count(),
                    "agents": AIAgent.query.filter_by(product_id=p.id).count()} for p in products}
    staff = User.query.filter(User.is_active == True, User.role.in_(["manager", "team_lead", "sales_executive"])).order_by(User.name).all()
    return render_template("products.html", products=products, stats=stats, staff=staff, categories=CATEGORIES,
                           q=q, status=status, cat=cat)


@bp.route("/add", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def add():
    name = request.form.get("name", "").strip()
    sku = request.form.get("sku", "").strip().upper()
    if not name or not sku:
        flash("Name and SKU are required.", "danger")
        return redirect(url_for("products.index"))
    if Product.query.filter_by(sku=sku).first():
        flash("SKU already exists.", "danger")
        return redirect(url_for("products.index"))
    p = Product(name=name, sku=sku, category=request.form.get("category") or "Others",
                status=request.form.get("status") or "Active", price=float(request.form.get("price") or 0),
                description=request.form.get("description"))
    db.session.add(p)
    db.session.flush()
    audit("CREATE", f"Product created: {name}", sku)
    db.session.commit()
    flash("Product added.", "success")
    return redirect(url_for("products.index"))


@bp.route("/<int:pid>/update", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def update(pid):
    p = db.session.get(Product, pid)
    if not p:
        flash("Product not found.", "danger")
        return redirect(url_for("products.index"))
    p.name = request.form.get("name", p.name).strip() or p.name
    p.category = request.form.get("category", p.category)
    p.status = request.form.get("status", p.status)
    p.price = float(request.form.get("price") or p.price or 0)
    p.description = request.form.get("description", p.description)
    audit("UPDATE", f"Product updated: {p.name}")
    db.session.commit()
    flash("Product updated.", "success")
    return redirect(url_for("products.index"))


@bp.route("/<int:pid>/team", methods=["POST"])
@login_required
@role_required("super_admin", "admin", "manager")
def assign_team(pid):
    p = db.session.get(Product, pid)
    if not p:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    ids = [int(i) for i in (data.get("user_ids") or request.form.getlist("user_ids"))]
    p.team = User.query.filter(User.id.in_(ids)).all() if ids else []
    audit("ASSIGN", f"Team assigned to product {p.name}", f"{len(p.team)} members")
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True, "team": [u.id for u in p.team]})
    flash("Team updated.", "success")
    return redirect(url_for("products.index"))


@bp.route("/<int:pid>/delete", methods=["POST"])
@login_required
@role_required("super_admin")
def delete(pid):
    p = db.session.get(Product, pid)
    if p:
        Lead.query.filter_by(product_id=p.id).update({"product_id": None})
        Deal.query.filter_by(product_id=p.id).update({"product_id": None})
        AIAgent.query.filter_by(product_id=p.id).update({"product_id": None})
        audit("DELETE", f"Product deleted: {p.name}")
        db.session.delete(p)
        db.session.commit()
        flash("Product deleted.", "info")
    return redirect(url_for("products.index"))
