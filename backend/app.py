"""FastSales / Genailakes admin portal - Flask application factory."""
import os
from datetime import datetime

import click
from flask import Flask, render_template, redirect, url_for, g

from models import db, User, Notification, ROLE_LABELS, DEAL_STAGES
from utils import current_user, register_filters


def _create_admin(name, email, password, phone=None):
    email = email.strip().lower()
    if User.query.filter(db.func.lower(User.email) == email).first():
        raise SystemExit(f"A user with email {email} already exists.")
    u = User(name=name.strip(), email=email, phone=phone, role="super_admin", department="Management")
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


def create_app():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    frontend = os.path.join(os.path.dirname(base_dir), "frontend")
    app = Flask(__name__, instance_relative_config=True,
                template_folder=os.path.join(frontend, "templates"),
                static_folder=os.path.join(frontend, "static"))
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "fastsales.db")),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
    )
    db.init_app(app)
    register_filters(app)

    from routes.auth import bp as auth_bp
    from routes.main import bp as main_bp
    from routes.deals import bp as deals_bp
    from routes.employees import bp as employees_bp
    from routes.leads import bp as leads_bp
    from routes.products import bp as products_bp
    from routes.agents import bp as agents_bp
    from routes.apikeys import bp as apikeys_bp
    from routes.payments import bp as payments_bp
    from routes.analytics import bp as analytics_bp
    from routes.audit import bp as audit_bp
    from routes.campaigns import bp as campaigns_bp
    from routes.whatsapp import bp as whatsapp_bp
    from routes.api import bp as api_bp

    for bp in (auth_bp, main_bp, deals_bp, employees_bp, leads_bp, products_bp, agents_bp,
               apikeys_bp, payments_bp, analytics_bp, audit_bp, campaigns_bp, whatsapp_bp, api_bp):
        app.register_blueprint(bp)

    CUSTOMER_ALLOWED = ("main.", "auth.", "products.index", "static")

    @app.before_request
    def restrict_customers():
        from flask import request, abort
        u = current_user()
        ep = request.endpoint or ""
        if u and u.role == "customer" and not ep.startswith(CUSTOMER_ALLOWED):
            abort(403)

    @app.context_processor
    def inject_globals():
        u = current_user()
        unread = Notification.query.filter_by(user_id=u.id, is_read=False).count() if u else 0
        return {
            "current_user": u,
            "unread_notifications": unread,
            "ROLE_LABELS": ROLE_LABELS,
            "DEAL_STAGES": DEAL_STAGES,
            "now": datetime.utcnow(),
            "brand": "Genailakes",
        }

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="You do not have access to this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="The page you are looking for was not found."), 404

    @app.cli.command("create-admin")
    @click.option("--name", prompt=True, help="Full name of the administrator.")
    @click.option("--email", prompt=True, help="Login email.")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option("--phone", default=None)
    def create_admin_cmd(name, email, password, phone):
        """Create the first Super Admin account (or another one later)."""
        _create_admin(name, email, password, phone)
        print(f"Super Admin created: {email}")

    with app.app_context():
        db.create_all()
        # Optional non-interactive bootstrap for server deploys:
        # set ADMIN_EMAIL and ADMIN_PASSWORD (and optionally ADMIN_NAME) on the first start.
        if User.query.count() == 0 and os.environ.get("ADMIN_EMAIL") and os.environ.get("ADMIN_PASSWORD"):
            _create_admin(os.environ.get("ADMIN_NAME", "Administrator"),
                          os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"])
            print(f"Created Super Admin from environment: {os.environ['ADMIN_EMAIL']}")

    return app


app = create_app()

if __name__ == "__main__":
    # Development only. In production run through Gunicorn (see deploy/ and README).
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG", "1") == "1")
