"""Unit tests for the SQLite layer and the seed data."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from collections_agent.db import (
    count_rows,
    get_connection,
    get_customer,
    get_invoice,
    get_open_invoices,
    init_db,
)
from collections_agent.models import Customer, Invoice, InvoiceStatus

# Import the seed module (scripts/ is not a package).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import seed  # noqa: E402


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    yield c
    c.close()


def test_schema_creates_all_tables(conn) -> None:
    for table in (
        "customers", "invoices", "promises_to_pay",
        "disputes", "escalations", "calls",
    ):
        assert count_rows(conn, table) == 0


def test_insert_and_read_customer_and_invoice(conn) -> None:
    customer = Customer(
        id="CUST-999",
        company_name="Test Co",
        contact_name="Test Person",
        phone="+91 90000 00000",
        email="test@test.example",
    )
    seed.insert_customer(conn, customer)
    invoice = Invoice(
        id="INV-0001",
        customer_id="CUST-999",
        amount_inr=10_000,
        issue_date=date(2026, 1, 1),
        due_date=date(2026, 1, 31),
        status=InvoiceStatus.OPEN,
    )
    seed.insert_invoice(conn, invoice)
    conn.commit()

    got_customer = get_customer(conn, "CUST-999")
    assert got_customer is not None
    assert got_customer.contact_name == "Test Person"

    got_invoice = get_invoice(conn, "INV-0001")
    assert got_invoice is not None
    assert got_invoice.amount_inr == 10_000
    assert got_invoice.due_date == date(2026, 1, 31)


def test_get_open_invoices_excludes_paid(conn) -> None:
    seed.insert_customer(
        conn,
        Customer(
            id="CUST-999", company_name="Test Co", contact_name="P",
            phone="+91 90000 00000", email="t@test.example",
        ),
    )
    seed.insert_invoice(
        conn,
        Invoice(
            id="INV-OPEN", customer_id="CUST-999", amount_inr=5_000,
            issue_date=date(2026, 1, 1), due_date=date(2026, 1, 31),
            status=InvoiceStatus.OPEN,
        ),
    )
    seed.insert_invoice(
        conn,
        Invoice(
            id="INV-PAID", customer_id="CUST-999", amount_inr=5_000,
            issue_date=date(2026, 1, 1), due_date=date(2026, 1, 31),
            status=InvoiceStatus.PAID,
        ),
    )
    conn.commit()

    open_invoices = get_open_invoices(conn, "CUST-999")
    assert [inv.id for inv in open_invoices] == ["INV-OPEN"]


def test_seed_database_populates(tmp_path) -> None:
    db_path = str(tmp_path / "collections.db")
    counts = seed.seed_database(db_path)

    assert counts["customers"] == 7
    assert counts["invoices"] == 11

    conn = get_connection(db_path)
    try:
        # Default demo customer must exist.
        assert get_customer(conn, "CUST-001") is not None

        # At least one customer with multiple overdue invoices.
        multi = get_open_invoices(conn, "CUST-003")
        assert len(multi) >= 2

        # All amounts within the specified range.
        rows = conn.execute("SELECT amount_inr FROM invoices").fetchall()
        for (amount,) in rows:
            assert 8_000 <= amount <= 4_50_000

        # Due dates are in the past (overdue) and computed relative to today.
        today = date.today()
        due_rows = conn.execute("SELECT due_date FROM invoices").fetchall()
        for (due,) in due_rows:
            due_date = date.fromisoformat(due)
            overdue_days = (today - due_date).days
            assert 5 <= overdue_days <= 90
    finally:
        conn.close()


def test_seed_database_all_relative_to_today(tmp_path) -> None:
    """issue_date should always be 30 days before due_date (net-30)."""
    db_path = str(tmp_path / "collections.db")
    seed.seed_database(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT issue_date, due_date FROM invoices").fetchall()
        for issue, due in rows:
            gap = date.fromisoformat(due) - date.fromisoformat(issue)
            assert gap == timedelta(days=30)
    finally:
        conn.close()
