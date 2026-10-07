"""SQLAlchemy models for the FastSales / Genailakes admin portal."""
from datetime import datetime, date
import secrets

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

ROLES = ["super_admin", "admin", "manager", "team_lead", "sales_executive", "customer"]
ROLE_LABELS = {
    "super_admin": "Super Admin",
    "admin": "Administrator",
    "manager": "Manager",
    "team_lead": "Team Lead",
    "sales_executive": "Sales Executive",
    "customer": "Customer",
}

DEAL_STAGES = [
    ("qualification", "Qualification", 10),
    ("needs_analysis", "Needs Analysis", 20),
    ("value_proposition", "Value Proposition", 40),
    ("proposal", "Proposal / Quote", 60),
    ("negotiation", "Negotiation / Review", 80),
    ("closed_won", "Closed Won", 100),
    ("closed_lost", "Closed Lost", 0),
]
STAGE_PROB = {k: p for k, _, p in DEAL_STAGES}
STAGE_LABEL = {k: l for k, l, _ in DEAL_STAGES}

LEAD_STATUSES = ["New", "Contacted", "Interested", "Not Interested", "Follow Up", "Converted", "Lost"]
CALL_STATUSES = ["Connected", "Failed", "Busy", "No Answer"]


def short_id():
    return secrets.token_hex(4)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(32))
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(32), nullable=False, default="sales_executive")
    department = db.Column(db.String(64), default="Sales")
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_active = db.Column(db.Boolean, default=True)
    wallet_balance = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    # preferences
    pref_dark = db.Column(db.Boolean, default=False)
    pref_notify_email = db.Column(db.Boolean, default=True)
    pref_notify_sms = db.Column(db.Boolean, default=False)
    pref_notify_push = db.Column(db.Boolean, default=True)
    pref_privacy_profile = db.Column(db.String(16), default="team")
    pref_comm_channel = db.Column(db.String(16), default="whatsapp")

    manager = db.relationship("User", remote_side=[id], backref="reports")

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def initials(self):
        parts = self.name.split()
        return "".join(p[0] for p in parts[:2]).upper()

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "email": self.email, "phone": self.phone,
            "role": self.role, "role_label": self.role_label, "department": self.department,
            "manager_id": self.manager_id, "is_active": self.is_active,
        }


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    sku = db.Column(db.String(40), unique=True, nullable=False)
    category = db.Column(db.String(60), default="Others")
    status = db.Column(db.String(20), default="Active")
    price = db.Column(db.Float, default=0.0)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = db.relationship("User", secondary="product_team", backref="products")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "sku": self.sku, "category": self.category,
                "status": self.status, "price": self.price, "description": self.description,
                "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat(),
                "team": [u.id for u in self.team]}


product_team = db.Table(
    "product_team",
    db.Column("product_id", db.Integer, db.ForeignKey("products.id"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
)


class Lead(db.Model):
    __tablename__ = "leads"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160))
    phone = db.Column(db.String(32), index=True)
    company = db.Column(db.String(120))
    source = db.Column(db.String(40), default="Others")
    status = db.Column(db.String(32), default="New")
    priority = db.Column(db.String(16), default="Medium")
    score = db.Column(db.Integer, default=50)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"))
    contacted = db.Column(db.Boolean, default=False)
    contacted_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = db.relationship("Product", backref="leads")
    assignee = db.relationship("User", backref="leads")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email, "phone": self.phone,
                "company": self.company, "source": self.source, "status": self.status,
                "priority": self.priority, "score": self.score,
                "product": self.product.name if self.product else None,
                "product_id": self.product_id, "assigned_to": self.assigned_to,
                "assignee": self.assignee.name if self.assignee else None,
                "contacted": self.contacted,
                "contacted_at": self.contacted_at.isoformat() if self.contacted_at else None,
                "created_at": self.created_at.isoformat()}


class AssignmentHistory(db.Model):
    __tablename__ = "assignment_history"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"))
    from_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    to_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    method = db.Column(db.String(40), default="manual")
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lead = db.relationship("Lead")
    from_user = db.relationship("User", foreign_keys=[from_user_id])
    to_user = db.relationship("User", foreign_keys=[to_user_id])


class Deal(db.Model):
    __tablename__ = "deals"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    contact_name = db.Column(db.String(120))
    contact_phone = db.Column(db.String(32))
    company = db.Column(db.String(120))
    value = db.Column(db.Float, default=0.0)
    stage = db.Column(db.String(32), default="qualification")
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"))
    expected_close = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = db.relationship("Product", backref="deals")
    owner = db.relationship("User", backref="deals")
    lead = db.relationship("Lead", backref="deals")

    @property
    def probability(self):
        return STAGE_PROB.get(self.stage, 0)

    @property
    def weighted(self):
        return self.value * self.probability / 100.0

    def to_dict(self):
        return {"id": self.id, "title": self.title, "contact_name": self.contact_name,
                "contact_phone": self.contact_phone, "company": self.company, "value": self.value,
                "stage": self.stage, "stage_label": STAGE_LABEL.get(self.stage, self.stage),
                "probability": self.probability, "weighted": self.weighted,
                "product": self.product.name if self.product else None, "product_id": self.product_id,
                "owner": self.owner.name if self.owner else None, "owner_id": self.owner_id,
                "expected_close": self.expected_close.isoformat() if self.expected_close else None,
                "updated_at": self.updated_at.isoformat()}


class SalesTarget(db.Model):
    __tablename__ = "sales_targets"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    period = db.Column(db.String(7))  # YYYY-MM
    target_amount = db.Column(db.Float, default=0.0)
    incentive_pct = db.Column(db.Float, default=0.0)
    user = db.relationship("User")


class CallLog(db.Model):
    __tablename__ = "call_logs"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    agent_id = db.Column(db.Integer, db.ForeignKey("ai_agents.id"))
    contact_name = db.Column(db.String(120))
    phone = db.Column(db.String(32))
    status = db.Column(db.String(20), default="Failed")
    duration_sec = db.Column(db.Integer, default=0)
    cost = db.Column(db.Float, default=0.0)
    qa_score = db.Column(db.Float)
    transcript = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    lead = db.relationship("Lead", backref="calls")
    user = db.relationship("User")
    agent = db.relationship("AIAgent")

    @property
    def duration_label(self):
        m, s = divmod(self.duration_sec or 0, 60)
        return f"{m}m {s}s"

    def to_dict(self):
        return {"id": self.id, "contact_name": self.contact_name, "phone": self.phone,
                "status": self.status, "duration_sec": self.duration_sec, "duration": self.duration_label,
                "cost": self.cost, "qa_score": self.qa_score, "user": self.user.name if self.user else None,
                "created_at": self.created_at.isoformat()}


class AIAgent(db.Model):
    __tablename__ = "ai_agents"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(12), default=short_id, unique=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")
    voice = db.Column(db.String(40), default="Female - Indian English")
    system_prompt = db.Column(db.Text)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    product = db.relationship("Product", backref="agents")

    def to_dict(self):
        return {"id": self.id, "public_id": self.public_id, "name": self.name,
                "description": self.description, "status": self.status, "voice": self.voice,
                "product": self.product.name if self.product else None, "product_id": self.product_id,
                "updated_at": self.updated_at.isoformat()}


class APIKey(db.Model):
    __tablename__ = "api_keys"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    prefix = db.Column(db.String(12))
    key_hash = db.Column(db.String(256), nullable=False)
    scopes = db.Column(db.String(200), default="read")
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_active = db.Column(db.Boolean, default=True)
    last_used = db.Column(db.DateTime)
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    owner = db.relationship("User")

    @staticmethod
    def generate():
        raw = "fs_live_" + secrets.token_urlsafe(32)
        return raw

    def set_key(self, raw):
        self.prefix = raw[:12]
        self.key_hash = generate_password_hash(raw)

    def matches(self, raw):
        return check_password_hash(self.key_hash, raw)


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(40), unique=True)
    organization = db.Column(db.String(120), default="GenAIlakes")
    amount = db.Column(db.Float, default=0.0)
    method = db.Column(db.String(30), default="UPI")
    status = db.Column(db.String(20), default="Paid")
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True)
    organization = db.Column(db.String(120), default="GenAIlakes")
    amount = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default="Open")  # Open / Paid / Overdue
    issued_on = db.Column(db.Date, default=date.today)
    due_on = db.Column(db.Date)
    description = db.Column(db.String(200))


class WalletTransaction(db.Model):
    __tablename__ = "wallet_transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    kind = db.Column(db.String(10))  # credit / debit
    amount = db.Column(db.Float, default=0.0)
    balance_after = db.Column(db.Float, default=0.0)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(12), default=short_id)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(40), index=True)  # LOGIN, CREATE, UPDATE, DELETE, ASSIGN ...
    title = db.Column(db.String(160))
    details = db.Column(db.Text)
    ip = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user = db.relationship("User")


class Campaign(db.Model):
    __tablename__ = "campaigns"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    channel = db.Column(db.String(30), default="WhatsApp")
    strategy = db.Column(db.String(200))
    status = db.Column(db.String(20), default="Draft")  # Draft / Active / Paused / Completed
    audience_size = db.Column(db.Integer, default=0)
    sent = db.Column(db.Integer, default=0)
    engaged = db.Column(db.Integer, default=0)
    outcomes = db.Column(db.Integer, default=0)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship("Product")

    @property
    def progress(self):
        return round(100 * self.sent / self.audience_size, 1) if self.audience_size else 0

    @property
    def engagement_rate(self):
        return round(100 * self.engaged / self.sent, 1) if self.sent else 0


class WATemplate(db.Model):
    __tablename__ = "wa_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(40), default="Marketing")
    language = db.Column(db.String(10), default="en")
    body = db.Column(db.Text)
    status = db.Column(db.String(20), default="Pending")  # Approved / Pending / Failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WAMessage(db.Model):
    __tablename__ = "wa_messages"
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(32))
    recipient_name = db.Column(db.String(120))
    template_id = db.Column(db.Integer, db.ForeignKey("wa_templates.id"))
    content = db.Column(db.Text)
    context = db.Column(db.String(60), default="Direct")
    direction = db.Column(db.String(10), default="out")
    status = db.Column(db.String(20), default="Queued")  # Queued / Sent / Delivered / Failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    template = db.relationship("WATemplate")


class WASession(db.Model):
    __tablename__ = "wa_sessions"
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(32))
    label = db.Column(db.String(120))
    status = db.Column(db.String(20), default="Disconnected")
    provider = db.Column(db.String(30), default="WhatsApp Web")
    connected_at = db.Column(db.DateTime)


class Setting(db.Model):
    """Organization-wide key/value settings (provider config etc.)."""
    __tablename__ = "settings"
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text)

    @staticmethod
    def get(key, default=None):
        s = db.session.get(Setting, key)
        return s.value if s and s.value not in (None, "") else default

    @staticmethod
    def put(key, value):
        s = db.session.get(Setting, key)
        if not s:
            s = Setting(key=key)
            db.session.add(s)
        s.value = value


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(160))
    body = db.Column(db.String(400))
    level = db.Column(db.String(12), default="info")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
