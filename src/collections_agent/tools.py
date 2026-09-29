"""Pure tool logic (PRD §6), independent of LiveKit.

Each function validates its inputs, reads/writes SQLite, and returns a small
JSON-serialisable dict. On invalid input it returns ``{"error": "<reason>"}``
(a human-readable message the LLM can relay and retry from) rather than
raising, so the conversation can recover. Amounts and dates are echoed back in
spoken form (via speech_format) so the LLM never has to convert them itself.

Keeping this logic free of LiveKit makes it directly unit-testable; the thin
@function_tool wrappers in agent.py just supply per-call state and record the
calls to the transcript.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from .db import (
    get_customer,
    get_invoice,
    get_open_invoices,
    insert_dispute,
    insert_escalation,
    insert_promise,
    set_invoice_status,
    upsert_call,
)
from .models import CallOutcome, DisputeType, InvoiceStatus
from .speech_format import (
    amount_to_spoken,
    date_to_spoken,
    days_to_spoken,
    invoice_id_to_spoken,
)

# A promise-to-pay date must be today or later and within this many days.
MAX_PROMISE_DAYS = 60


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_customer_context(
    conn: sqlite3.Connection, customer_id: str, today: date
) -> dict:
    """Load the customer and their open invoices, with raw and spoken values."""
    customer = get_customer(conn, customer_id)
    if customer is None:
        return {"error": f"No customer found for id {customer_id}."}

    invoices = get_open_invoices(conn, customer_id)
    open_invoices = []
    for inv in invoices:
        days_overdue = (today - inv.due_date).days
        open_invoices.append(
            {
                "invoice_id": inv.id,
                "invoice_id_spoken": invoice_id_to_spoken(inv.id),
                "amount_inr": inv.amount_inr,
                "amount_spoken": amount_to_spoken(inv.amount_inr),
                "due_date": inv.due_date.isoformat(),
                "due_date_spoken": date_to_spoken(inv.due_date),
                "days_overdue": days_overdue,
                "days_overdue_spoken": days_to_spoken(max(days_overdue, 0)),
                "status": inv.status.value,
            }
        )

    total = sum(inv.amount_inr for inv in invoices)
    return {
        "customer_id": customer.id,
        "company_name": customer.company_name,
        "contact_name": customer.contact_name,
        "open_invoice_count": len(open_invoices),
        "open_invoices": open_invoices,
        "total_open_amount_inr": total,
        "total_open_amount_spoken": amount_to_spoken(total) if total else None,
    }


def validate_promise(
    conn: sqlite3.Connection,
    invoice_id: str,
    promised_date_iso: str,
    amount: int | None,
    today: date,
) -> dict:
    """Validate a promise-to-pay. Returns the resolved values or an error dict."""
    invoice = get_invoice(conn, invoice_id)
    if invoice is None:
        return {"error": f"No invoice found with id {invoice_id}."}

    try:
        promised = date.fromisoformat(promised_date_iso)
    except (ValueError, TypeError):
        return {
            "error": "The promised date is not a valid date. "
            "Ask the caller for a specific day."
        }

    if promised < today:
        return {
            "error": "The promised date is in the past. "
            "Ask for today or a future date."
        }
    if (promised - today).days > MAX_PROMISE_DAYS:
        return {
            "error": f"The promised date is more than {MAX_PROMISE_DAYS} days "
            "away. Ask the caller for an earlier date."
        }

    balance = invoice.amount_inr
    resolved_amount = balance if amount is None else int(amount)
    if resolved_amount <= 0:
        return {"error": "The amount must be greater than zero."}
    if resolved_amount > balance:
        return {
            "error": "The amount is more than the invoice balance of "
            f"{amount_to_spoken(balance)}. Confirm a smaller amount."
        }

    return {
        "ok": True,
        "invoice_id": invoice.id,
        "promised_date": promised,
        "amount": resolved_amount,
        "balance": balance,
    }


def log_promise_to_pay(
    conn: sqlite3.Connection,
    *,
    call_id: str,
    invoice_id: str,
    promised_date_iso: str,
    amount: int | None,
    today: date,
) -> dict:
    """Validate and record a promise to pay; return spoken read-back text."""
    v = validate_promise(conn, invoice_id, promised_date_iso, amount, today)
    if "error" in v:
        return v

    promised: date = v["promised_date"]
    resolved_amount: int = v["amount"]
    insert_promise(
        conn,
        invoice_id=v["invoice_id"],
        call_id=call_id,
        promised_date=promised.isoformat(),
        amount_inr=resolved_amount,
        created_at=_now_iso(),
    )
    conn.commit()

    read_back = (
        f"{amount_to_spoken(resolved_amount)} for "
        f"{invoice_id_to_spoken(v['invoice_id'])} on {date_to_spoken(promised)}"
    )
    return {
        "logged": True,
        "invoice_id": v["invoice_id"],
        "promised_date": promised.isoformat(),
        "amount_inr": resolved_amount,
        "read_back": read_back,
    }


def flag_dispute(
    conn: sqlite3.Connection,
    *,
    call_id: str,
    invoice_id: str,
    dispute_type: str,
    details: str,
) -> dict:
    """Record a dispute / already-paid claim and set the invoice UNDER_REVIEW."""
    invoice = get_invoice(conn, invoice_id)
    if invoice is None:
        return {"error": f"No invoice found with id {invoice_id}."}

    try:
        dtype = DisputeType(dispute_type)
    except ValueError:
        return {
            "error": "dispute_type must be ALREADY_PAID or DISPUTE."
        }

    if not details or not details.strip():
        return {
            "error": "Ask the caller for details first: a payment date and "
            "reference if already paid, or the reason for the dispute."
        }

    insert_dispute(
        conn,
        invoice_id=invoice.id,
        call_id=call_id,
        dispute_type=dtype.value,
        details=details.strip(),
        created_at=_now_iso(),
    )
    set_invoice_status(conn, invoice.id, InvoiceStatus.UNDER_REVIEW)
    conn.commit()
    return {
        "logged": True,
        "invoice_id": invoice.id,
        "dispute_type": dtype.value,
        "status": InvoiceStatus.UNDER_REVIEW.value,
    }


def escalate_to_human(
    conn: sqlite3.Connection,
    *,
    call_id: str,
    customer_id: str,
    reason: str,
    preferred_callback_time: str | None,
) -> dict:
    """Record an escalation to a human agent."""
    if not reason or not reason.strip():
        return {"error": "A reason is required to escalate."}
    insert_escalation(
        conn,
        customer_id=customer_id,
        call_id=call_id,
        reason=reason.strip(),
        preferred_callback_time=preferred_callback_time,
        created_at=_now_iso(),
    )
    conn.commit()
    return {
        "logged": True,
        "reason": reason.strip(),
        "preferred_callback_time": preferred_callback_time,
    }


def finalize_call(
    conn: sqlite3.Connection,
    *,
    call_id: str,
    customer_id: str,
    started_at: str,
    ended_at: str,
    outcome: str,
    summary: str,
    transcript_path: str,
    avg_latency_ms: int | None = None,
    p95_latency_ms: int | None = None,
) -> dict:
    """Write the final call record. Validates the outcome enum."""
    try:
        oc = CallOutcome(outcome)
    except ValueError:
        valid = ", ".join(o.value for o in CallOutcome)
        return {"error": f"outcome must be one of: {valid}."}

    upsert_call(
        conn,
        call_id=call_id,
        customer_id=customer_id,
        started_at=started_at,
        ended_at=ended_at,
        outcome=oc.value,
        summary=summary,
        transcript_path=transcript_path,
        avg_latency_ms=avg_latency_ms,
        p95_latency_ms=p95_latency_ms,
    )
    conn.commit()
    return {"logged": True, "outcome": oc.value}
