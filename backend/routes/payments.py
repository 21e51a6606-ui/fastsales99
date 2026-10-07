from datetime import datetime, date, timedelta
import secrets

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import func

from models import db, Payment, Invoice, WalletTransaction, CallLog, User, Setting
from utils import login_required, role_required, current_user, audit

bp = Blueprint("payments", __name__, url_prefix="/dashboard/admin/payments")


@bp.route("/")
@login_required
def index():
    tab = request.args.get("tab", "history")
    today = date.today()
    for inv in Invoice.query.filter(Invoice.status == "Open", Invoice.due_on < today).all():
        inv.status = "Overdue"
    db.session.commit()
    active_invoices = Invoice.query.filter(Invoice.status.in_(["Open", "Overdue"])).count()
    outstanding = db.session.query(func.coalesce(func.sum(Invoice.amount), 0)).filter(Invoice.status.in_(["Open", "Overdue"])).scalar()
    overdue = db.session.query(func.coalesce(func.sum(Invoice.amount), 0)).filter(Invoice.status == "Overdue").scalar()
    next_due = Invoice.query.filter(Invoice.status.in_(["Open", "Overdue"])).order_by(Invoice.due_on).first()
    last_payment = Payment.query.filter_by(status="Paid").order_by(Payment.created_at.desc()).first()

    payments = Payment.query.order_by(Payment.created_at.desc()).limit(100).all()
    invoices = Invoice.query.order_by(Invoice.issued_on.desc()).all()
    cstatus = request.args.get("cstatus")
    cq = CallLog.query
    if cstatus:
        cq = cq.filter(CallLog.status == cstatus)
    calls = cq.order_by(CallLog.created_at.desc()).limit(100).all()
    wallet = WalletTransaction.query.order_by(WalletTransaction.created_at.desc()).limit(100).all()
    org = Setting.get("org_name", "GenAIlakes")
    return render_template("payments.html", tab=tab, active_invoices=active_invoices, outstanding=outstanding,
                           overdue=overdue, next_due=next_due, last_payment=last_payment, payments=payments,
                           invoices=invoices, calls=calls, wallet=wallet, cstatus=cstatus, org=org)


@bp.route("/topup", methods=["POST"])
@login_required
def topup():
    u = current_user()
    amount = float(request.form.get("amount") or 0)
    if amount <= 0:
        flash("Enter a valid amount.", "danger")
        return redirect(url_for("payments.index", tab="wallet"))
    method = request.form.get("method") or "UPI"
    ref = "PAY-" + secrets.token_hex(3).upper()
    db.session.add(Payment(reference=ref, organization=Setting.get("org_name", "GenAIlakes"), amount=amount,
                           method=method, status="Paid", description="Wallet top-up"))
    u.wallet_balance = (u.wallet_balance or 0) + amount
    db.session.add(WalletTransaction(user_id=u.id, kind="credit", amount=amount, balance_after=u.wallet_balance,
                                     description=f"Top-up {ref}"))
    audit("PAYMENT", f"Wallet top-up ₹{amount:,.0f}", ref)
    db.session.commit()
    flash(f"Wallet credited with ₹{amount:,.0f} ({ref}).", "success")
    return redirect(url_for("payments.index", tab="wallet"))


@bp.route("/invoice/create", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def create_invoice():
    amount = float(request.form.get("amount") or 0)
    if amount <= 0:
        flash("Enter a valid amount.", "danger")
        return redirect(url_for("payments.index", tab="invoices"))
    n = Invoice.query.count() + 1
    inv = Invoice(number=f"INV-{date.today().year}-{n:03d}", organization=Setting.get("org_name", "GenAIlakes"),
                  amount=amount, status="Open", issued_on=date.today(),
                  due_on=date.today() + timedelta(days=int(request.form.get("due_days") or 15)),
                  description=request.form.get("description"))
    db.session.add(inv)
    audit("CREATE", f"Invoice created: {inv.number}", f"₹{amount}")
    db.session.commit()
    flash(f"Invoice {inv.number} created.", "success")
    return redirect(url_for("payments.index", tab="invoices"))


@bp.route("/invoice/<int:iid>/pay", methods=["POST"])
@login_required
def pay_invoice(iid):
    inv = db.session.get(Invoice, iid)
    if not inv or inv.status == "Paid":
        return jsonify({"error": "invalid invoice"}), 400
    u = current_user()
    ref = "PAY-" + secrets.token_hex(3).upper()
    db.session.add(Payment(reference=ref, organization=inv.organization, amount=inv.amount,
                           method=(request.get_json(silent=True) or {}).get("method", "UPI"), status="Paid",
                           description=f"Payment for {inv.number}"))
    inv.status = "Paid"
    audit("PAYMENT", f"Invoice paid: {inv.number}", ref)
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True, "reference": ref})
    flash(f"Invoice {inv.number} marked paid.", "success")
    return redirect(url_for("payments.index", tab="invoices"))


@bp.route("/invoice/<int:iid>")
@login_required
def invoice_view(iid):
    inv = db.session.get(Invoice, iid)
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("payments.index", tab="invoices"))
    return render_template("invoice.html", inv=inv)


@bp.route("/charge-calls", methods=["POST"])
@login_required
@role_required("super_admin", "admin")
def charge_calls():
    """Debit the wallet for calls not yet billed (demo settlement)."""
    u = current_user()
    since = datetime.utcnow() - timedelta(days=int(request.form.get("days") or 1))
    total = db.session.query(func.coalesce(func.sum(CallLog.cost), 0)).filter(CallLog.created_at >= since).scalar()
    if total <= 0:
        flash("No call charges to settle.", "info")
        return redirect(url_for("payments.index", tab="wallet"))
    u.wallet_balance = (u.wallet_balance or 0) - total
    db.session.add(WalletTransaction(user_id=u.id, kind="debit", amount=total, balance_after=u.wallet_balance,
                                     description="Call charges settlement"))
    audit("PAYMENT", f"Call charges settled ₹{total:,.2f}")
    db.session.commit()
    flash(f"Settled ₹{total:,.2f} of call charges.", "success")
    return redirect(url_for("payments.index", tab="wallet"))
