from datetime import datetime
import secrets

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify

from models import db, User, ROLE_LABELS, AuditLog
from utils import audit, current_user

bp = Blueprint("auth", __name__)

ROLE_META = [
    ("customer", "Customer", "shopping-cart", "Browse products & track orders"),
    ("admin", "Administrator", "shield", "Manage users, products & settings"),
    ("super_admin", "Super Admin", "shield", "Complete system control & administration"),
    ("sales_executive", "Sales Executive", "users", "Work leads, calls & deals"),
    ("team_lead", "Team Lead", "user-circle", "Coach and track your team"),
    ("manager", "Manager", "bar-chart-3", "Pipeline oversight & targets"),
]

# in-memory reset tokens (demo)
_reset_tokens = {}


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role = request.form.get("role") or "super_admin"
        remember = bool(request.form.get("remember"))
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return render_template("login.html", roles=ROLE_META, selected=role, email=email), 401
        if not user.is_active:
            flash("This account is deactivated. Contact your administrator.", "danger")
            return render_template("login.html", roles=ROLE_META, selected=role, email=email), 403
        if user.role != role:
            flash(f"This account is registered as {user.role_label}. Select that role on the wheel.", "warning")
            return render_template("login.html", roles=ROLE_META, selected=user.role, email=email), 403
        session.clear()
        session["user_id"] = user.id
        session.permanent = remember
        user.last_login = datetime.utcnow()
        audit("LOGIN", "User Login", f"Signed in as {user.role_label}", user=user)
        db.session.commit()
        nxt = request.args.get("next")
        return redirect(nxt if nxt and nxt.startswith("/") else url_for("main.dashboard"))
    return render_template("login.html", roles=ROLE_META, selected=request.args.get("role", "super_admin"), email="")


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    u = current_user()
    if u:
        audit("LOGOUT", "User Logout", user=u)
        db.session.commit()
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    token = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user:
            token = secrets.token_urlsafe(24)
            _reset_tokens[token] = (user.id, datetime.utcnow())
            audit("SECURITY", "Password reset requested", user=user)
            db.session.commit()
        flash("If that email exists, a reset link has been generated below (demo mode: no email is sent).", "info")
    return render_template("forgot.html", token=token)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    data = _reset_tokens.get(token)
    if not data or (datetime.utcnow() - data[1]).total_seconds() > 3600:
        flash("Reset link is invalid or expired.", "danger")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        pw = request.form.get("password") or ""
        if len(pw) < 6 or pw != request.form.get("confirm"):
            flash("Passwords must match and be at least 6 characters.", "danger")
        else:
            user = db.session.get(User, data[0])
            user.set_password(pw)
            audit("SECURITY", "Password reset completed", user=user)
            db.session.commit()
            _reset_tokens.pop(token, None)
            flash("Password updated. Please sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("reset.html", token=token)


@bp.route("/request-access", methods=["GET", "POST"])
def request_access():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        if not name or not email:
            flash("Name and email are required.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "warning")
        else:
            u = User(name=name, email=email, phone=request.form.get("phone"), role="customer", is_active=False)
            u.set_password(secrets.token_urlsafe(8))
            db.session.add(u)
            db.session.flush()
            audit("ACCESS_REQUEST", f"Access requested by {name}", email, user=u)
            db.session.commit()
            flash("Request submitted. An administrator will activate your account.", "success")
            return redirect(url_for("auth.login"))
    return render_template("request_access.html")
