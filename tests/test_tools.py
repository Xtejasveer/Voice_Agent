"""Unit tests for the pure tool logic and validation (PRD §6)."""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from collections_agent import tools
from collections_agent.db import count_rows, get_connection, get_invoice

# Seed helper (scripts/ is not a package).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import seed  # noqa: E402

# CUST-001 / INV-4217 is 12,500 rupees in the seed data.
INV = "INV-4217"
BALANCE = 12_500
TODAY = date.today()
_FORBIDDEN_SPOKEN = re.compile(r"[0-9₹$/@()#*_]")


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "collections.db")
    seed.seed_database(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


# --- get_customer_context --------------------------------------------------

def test_get_customer_context(conn) -> None:
    ctx = tools.get_customer_context(conn, "CUST-001", TODAY)
    assert ctx["contact_name"] == "Rohit Sharma"
    assert ctx["open_invoice_count"] == 1
    inv = ctx["open_invoices"][0]
    assert inv["invoice_id"] == INV
    assert inv["amount_inr"] == BALANCE
    # Spoken fields must be TTS-safe (no digits/symbols).
    for field in ("amount_spoken", "due_date_spoken", "invoice_id_spoken", "days_overdue_spoken"):
        assert not _FORBIDDEN_SPOKEN.search(inv[field]), inv[field]


def test_get_customer_context_multiple_invoices(conn) -> None:
    ctx = tools.get_customer_context(conn, "CUST-003", TODAY)
    assert ctx["open_invoice_count"] == 3
    assert ctx["total_open_amount_inr"] == 45_000 + 1_20_000 + 18_500


def test_get_customer_context_unknown(conn) -> None:
    assert "error" in tools.get_customer_context(conn, "CUST-999", TODAY)


# --- log_promise_to_pay ----------------------------------------------------

def test_promise_full_balance(conn) -> None:
    promised = (TODAY + timedelta(days=10)).isoformat()
    res = tools.log_promise_to_pay(
        conn, call_id="c1", invoice_id=INV, promised_date_iso=promised,
        amount=None, today=TODAY,
    )
    assert res["logged"] is True
    assert res["amount_inr"] == BALANCE
    assert count_rows(conn, "promises_to_pay") == 1
    assert not _FORBIDDEN_SPOKEN.search(res["read_back"]), res["read_back"]


def test_promise_partial(conn) -> None:
    promised = (TODAY + timedelta(days=5)).isoformat()
    res = tools.log_promise_to_pay(
        conn, call_id="c1", invoice_id=INV, promised_date_iso=promised,
        amount=5_000, today=TODAY,
    )
    assert res["logged"] is True and res["amount_inr"] == 5_000


def test_promise_date_in_past(conn) -> None:
    past = (TODAY - timedelta(days=1)).isoformat()
    res = tools.log_promise_to_pay(
        conn, call_id="c1", invoice_id=INV, promised_date_iso=past,
        amount=None, today=TODAY,
    )
    assert "error" in res and count_rows(conn, "promises_to_pay") == 0


def test_promise_date_too_far(conn) -> None:
    far = (TODAY + timedelta(days=61)).isoformat()
    res = tools.log_promise_to_pay(
        conn, call_id="c1", invoice_id=INV, promised_date_iso=far,
        amount=None, today=TODAY,
    )
    assert "error" in res and count_rows(conn, "promises_to_pay") == 0


def test_promise_amount_over_balance(conn) -> None:
    promised = (TODAY + timedelta(days=10)).isoformat()
    res = tools.log_promise_to_pay(
        conn, call_id="c1", invoice_id=INV, promised_date_iso=promised,
        amount=BALANCE + 1, today=TODAY,
    )
    assert "error" in res


def test_promise_amount_not_positive(conn) -> None:
    promised = (TODAY + timedelta(days=10)).isoformat()
    res = tools.log_promise_to_pay(
        conn, call_id="c1", invoice_id=INV, promised_date_iso=promised,
        amount=0, today=TODAY,
    )
    assert "error" in res


def test_promise_bad_date_string(conn) -> None:
    res = tools.log_promise_to_pay(
        conn, call_id="c1", invoice_id=INV, promised_date_iso="next Tuesday",
        amount=None, today=TODAY,
    )
    assert "error" in res


def test_promise_unknown_invoice(conn) -> None:
    promised = (TODAY + timedelta(days=10)).isoformat()
    res = tools.log_promise_to_pay(
        conn, call_id="c1", invoice_id="INV-0000", promised_date_iso=promised,
        amount=None, today=TODAY,
    )
    assert "error" in res


# --- flag_dispute ----------------------------------------------------------

def test_flag_dispute_already_paid_sets_under_review(conn) -> None:
    res = tools.flag_dispute(
        conn, call_id="c1", invoice_id=INV, dispute_type="ALREADY_PAID",
        details="Paid on the third of September, reference AB12.",
    )
    assert res["logged"] is True and res["status"] == "UNDER_REVIEW"
    assert count_rows(conn, "disputes") == 1
    assert get_invoice(conn, INV).status.value == "UNDER_REVIEW"


def test_flag_dispute_bad_type(conn) -> None:
    res = tools.flag_dispute(
        conn, call_id="c1", invoice_id=INV, dispute_type="WHATEVER",
        details="something",
    )
    assert "error" in res and count_rows(conn, "disputes") == 0


def test_flag_dispute_requires_details(conn) -> None:
    res = tools.flag_dispute(
        conn, call_id="c1", invoice_id=INV, dispute_type="DISPUTE", details="  ",
    )
    assert "error" in res


# --- escalate_to_human -----------------------------------------------------

def test_escalate(conn) -> None:
    res = tools.escalate_to_human(
        conn, call_id="c1", customer_id="CUST-001",
        reason="Caller requested a human.", preferred_callback_time="tomorrow 10am",
    )
    assert res["logged"] is True and count_rows(conn, "escalations") == 1


def test_escalate_requires_reason(conn) -> None:
    res = tools.escalate_to_human(
        conn, call_id="c1", customer_id="CUST-001", reason="",
        preferred_callback_time=None,
    )
    assert "error" in res


# --- finalize_call ---------------------------------------------------------

def test_finalize_call(conn) -> None:
    res = tools.finalize_call(
        conn, call_id="call-1", customer_id="CUST-001",
        started_at="2026-09-29T10:00:00", ended_at="2026-09-29T10:02:00",
        outcome="PROMISE_TO_PAY", summary="Promised to pay in full.",
        transcript_path="logs/call-1.transcript.json",
    )
    assert res["outcome"] == "PROMISE_TO_PAY"
    row = conn.execute("SELECT outcome, summary FROM calls WHERE id='call-1'").fetchone()
    assert row["outcome"] == "PROMISE_TO_PAY"


def test_finalize_call_bad_outcome(conn) -> None:
    res = tools.finalize_call(
        conn, call_id="call-1", customer_id="CUST-001",
        started_at="x", ended_at="y", outcome="NOPE", summary="s",
        transcript_path="p",
    )
    assert "error" in res and count_rows(conn, "calls") == 0
