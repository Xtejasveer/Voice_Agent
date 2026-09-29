"""Seed the SQLite database with fictional Indian B2B customers and invoices.

Usage::

    python scripts/seed.py            # create + seed if the DB does not exist
    python scripts/seed.py --reset    # delete the DB file, then recreate + seed

Amounts range from 8,000 to 4,50,000 rupees; days overdue from 5 to 90. Due
dates are computed relative to today, so the data never goes stale. At least
one customer (Verma Industries) has multiple overdue invoices.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Allow `python scripts/seed.py` to import the package without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from collections_agent.config import get_settings  # noqa: E402
from collections_agent.db import (  # noqa: E402
    get_connection,
    init_db,
    insert_customer,
    insert_invoice,
)
from collections_agent.models import Customer, Invoice, InvoiceStatus  # noqa: E402

# Net-30 terms: issue date is 30 days before the due date.
_TERMS_DAYS = 30

# (customer, [(invoice_id, amount_inr, days_overdue), ...])
_SEED = [
    (
        Customer(
            id="CUST-001",
            company_name="Sharma Textiles Private Limited",
            contact_name="Rohit Sharma",
            phone="+91 98765 43210",
            email="rohit.sharma@sharmatextiles.example",
        ),
        [("INV-4217", 12_500, 15)],
    ),
    (
        Customer(
            id="CUST-002",
            company_name="Patel Exports",
            contact_name="Anjali Patel",
            phone="+91 91234 56780",
            email="anjali.patel@patelexports.example",
        ),
        [("INV-5108", 8_000, 5)],
    ),
    (
        Customer(
            id="CUST-003",
            company_name="Verma Industries",
            contact_name="Suresh Verma",
            phone="+91 99887 76655",
            email="suresh.verma@vermaindustries.example",
        ),
        # Multiple overdue invoices.
        [
            ("INV-3301", 45_000, 60),
            ("INV-3302", 1_20_000, 30),
            ("INV-3303", 18_500, 10),
        ],
    ),
    (
        Customer(
            id="CUST-004",
            company_name="Nair Logistics",
            contact_name="Priya Nair",
            phone="+91 90000 12345",
            email="priya.nair@nairlogistics.example",
        ),
        [
            ("INV-6621", 4_50_000, 90),
            ("INV-6622", 75_000, 45),
        ],
    ),
    (
        Customer(
            id="CUST-005",
            company_name="Reddy Software Solutions",
            contact_name="Karthik Reddy",
            phone="+91 98111 22333",
            email="karthik.reddy@reddysoft.example",
        ),
        [("INV-7788", 2_25_000, 20)],
    ),
    (
        Customer(
            id="CUST-006",
            company_name="Iyer Foods",
            contact_name="Lakshmi Iyer",
            phone="+91 93456 78901",
            email="lakshmi.iyer@iyerfoods.example",
        ),
        [("INV-9012", 33_000, 75)],
    ),
    (
        Customer(
            id="CUST-007",
            company_name="Gupta Pharma Distributors",
            contact_name="Amit Gupta",
            phone="+91 96700 88990",
            email="amit.gupta@guptapharma.example",
        ),
        [
            ("INV-1450", 90_000, 50),
            ("INV-1451", 15_750, 7),
        ],
    ),
]


def seed_database(db_path: str) -> dict[str, int]:
    """Create the schema and insert all seed data. Returns row counts.

    Assumes an empty database; callers use ``--reset`` to start clean.
    """
    today = date.today()
    conn = get_connection(db_path)
    try:
        init_db(conn)
        n_customers = 0
        n_invoices = 0
        for customer, invoices in _SEED:
            insert_customer(conn, customer)
            n_customers += 1
            for invoice_id, amount_inr, days_overdue in invoices:
                due = today - timedelta(days=days_overdue)
                issue = due - timedelta(days=_TERMS_DAYS)
                insert_invoice(
                    conn,
                    Invoice(
                        id=invoice_id,
                        customer_id=customer.id,
                        amount_inr=amount_inr,
                        issue_date=issue,
                        due_date=due,
                        status=InvoiceStatus.OPEN,
                    ),
                )
                n_invoices += 1
        conn.commit()
        return {"customers": n_customers, "invoices": n_invoices}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the collections database.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing database file before seeding.",
    )
    args = parser.parse_args(argv)

    db_path = get_settings().db_path
    path = Path(db_path)

    if args.reset and path.exists():
        path.unlink()
        print(f"Removed existing database at {db_path}")

    if path.exists() and not args.reset:
        print(
            f"Database already exists at {db_path}. "
            "Re-run with --reset to recreate it."
        )
        return 1

    counts = seed_database(db_path)
    print(
        f"Seeded {db_path}: "
        f"{counts['customers']} customers, {counts['invoices']} invoices."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
