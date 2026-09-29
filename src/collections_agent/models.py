"""Enums and typed models shared across the app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from pydantic import BaseModel


class CallOutcome(str, Enum):
    """Exactly one of these is logged per call (PRD §5.2)."""

    PROMISE_TO_PAY = "PROMISE_TO_PAY"
    ALREADY_PAID = "ALREADY_PAID"
    DISPUTE = "DISPUTE"
    ESCALATED = "ESCALATED"
    WRONG_CONTACT = "WRONG_CONTACT"
    NO_RESOLUTION = "NO_RESOLUTION"


class InvoiceStatus(str, Enum):
    """Lifecycle status of an invoice (PRD §7)."""

    OPEN = "OPEN"
    PAID = "PAID"
    UNDER_REVIEW = "UNDER_REVIEW"


class DisputeType(str, Enum):
    """Kind of dispute raised by the customer (PRD §6)."""

    ALREADY_PAID = "ALREADY_PAID"
    DISPUTE = "DISPUTE"


class Customer(BaseModel):
    """A B2B customer record."""

    id: str
    company_name: str
    contact_name: str
    phone: str
    email: str


class Invoice(BaseModel):
    """An invoice belonging to a customer. Amounts are whole rupees."""

    id: str
    customer_id: str
    amount_inr: int
    issue_date: date
    due_date: date
    status: InvoiceStatus


@dataclass
class CallState:
    """Mutable per-call state shared with the function tools."""

    customer_id: str
    call_id: str
    started_at: str  # ISO timestamp
    verified: bool = False
    outcome_logged: bool = False
