"""SQLite access layer (PRD §7).

A single-file database at ``data/collections.db`` by default. This module owns
the schema and the read/write helpers used by the seed script and (later) the
function tools. All amounts are whole rupees stored as INTEGER.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import get_settings
from .models import Customer, Invoice, InvoiceStatus

# --- Schema ----------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id           TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    phone        TEXT NOT NULL,
    email        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id          TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    amount_inr  INTEGER NOT NULL,
    issue_date  DATE NOT NULL,
    due_date    DATE NOT NULL,
    status      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS promises_to_pay (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id   TEXT NOT NULL REFERENCES invoices(id),
    call_id      TEXT,
    promised_date DATE NOT NULL,
    amount_inr   INTEGER NOT NULL,
    created_at   TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS disputes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id   TEXT NOT NULL REFERENCES invoices(id),
    call_id      TEXT,
    dispute_type TEXT NOT NULL,
    details      TEXT,
    created_at   TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS escalations (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id            TEXT NOT NULL REFERENCES customers(id),
    call_id                TEXT,
    reason                 TEXT NOT NULL,
    preferred_callback_time TEXT,
    created_at             TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS calls (
    id             TEXT PRIMARY KEY,
    customer_id    TEXT REFERENCES customers(id),
    started_at     TIMESTAMP,
    ended_at       TIMESTAMP,
    outcome        TEXT,
    summary        TEXT,
    transcript_path TEXT,
    avg_latency_ms INTEGER,
    p95_latency_ms INTEGER
);
"""


# --- Connection ------------------------------------------------------------

def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enforced.

    Ensures the parent directory exists. Pass ``:memory:`` for a throwaway DB.
    """
    if db_path is None:
        db_path = get_settings().db_path
    db_path = str(db_path)
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they do not already exist."""
    conn.executescript(SCHEMA)
    conn.commit()


# --- Writes used by the seed script ---------------------------------------

def insert_customer(conn: sqlite3.Connection, customer: Customer) -> None:
    conn.execute(
        "INSERT INTO customers (id, company_name, contact_name, phone, email) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            customer.id,
            customer.company_name,
            customer.contact_name,
            customer.phone,
            customer.email,
        ),
    )


def insert_invoice(conn: sqlite3.Connection, invoice: Invoice) -> None:
    conn.execute(
        "INSERT INTO invoices (id, customer_id, amount_inr, issue_date, due_date, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            invoice.id,
            invoice.customer_id,
            invoice.amount_inr,
            invoice.issue_date.isoformat(),
            invoice.due_date.isoformat(),
            invoice.status.value,
        ),
    )


# --- Reads -----------------------------------------------------------------

def get_customer(conn: sqlite3.Connection, customer_id: str) -> Customer | None:
    row = conn.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()
    if row is None:
        return None
    return Customer(
        id=row["id"],
        company_name=row["company_name"],
        contact_name=row["contact_name"],
        phone=row["phone"],
        email=row["email"],
    )


def get_open_invoices(conn: sqlite3.Connection, customer_id: str) -> list[Invoice]:
    """Return the customer's invoices that are not fully paid, oldest due first."""
    rows = conn.execute(
        "SELECT * FROM invoices WHERE customer_id = ? AND status != ? "
        "ORDER BY due_date ASC",
        (customer_id, InvoiceStatus.PAID.value),
    ).fetchall()
    return [
        Invoice(
            id=row["id"],
            customer_id=row["customer_id"],
            amount_inr=row["amount_inr"],
            issue_date=row["issue_date"],
            due_date=row["due_date"],
            status=InvoiceStatus(row["status"]),
        )
        for row in rows
    ]


def get_invoice(conn: sqlite3.Connection, invoice_id: str) -> Invoice | None:
    row = conn.execute(
        "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
    ).fetchone()
    if row is None:
        return None
    return Invoice(
        id=row["id"],
        customer_id=row["customer_id"],
        amount_inr=row["amount_inr"],
        issue_date=row["issue_date"],
        due_date=row["due_date"],
        status=InvoiceStatus(row["status"]),
    )


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    """Row count for a table. Table name is validated against the known schema."""
    allowed = {
        "customers", "invoices", "promises_to_pay",
        "disputes", "escalations", "calls",
    }
    if table not in allowed:
        raise ValueError(f"Unknown table: {table}")
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
