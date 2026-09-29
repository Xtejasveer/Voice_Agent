"""Unit tests for the deterministic speech formatting helpers (PRD §5.4)."""

from __future__ import annotations

import re
from datetime import date

import pytest

from collections_agent.speech_format import (
    amount_to_spoken,
    date_to_spoken,
    days_to_spoken,
    email_to_spoken,
    integer_to_words,
    invoice_id_to_spoken,
    phone_to_spoken,
)

# §5.4 forbids digits, currency symbols, markdown, emojis, and parentheses in
# spoken output. Commas/periods are ordinary prosodic punctuation and are
# allowed (the PRD's own invoice example uses a comma). Letters are allowed
# because ids are spelled as capitals (e.g. "I N V").
_FORBIDDEN = re.compile(r"[0-9₹$/@()#*_]")


@pytest.mark.parametrize(
    "amount,expected",
    [
        (8_000, "eight thousand rupees"),
        (12_500, "twelve thousand five hundred rupees"),
        (45_000, "forty five thousand rupees"),
        (1_20_000, "one lakh twenty thousand rupees"),
        (2_25_000, "two lakh twenty five thousand rupees"),
        (4_50_000, "four lakh fifty thousand rupees"),
        (100, "one hundred rupees"),
        (123, "one hundred twenty three rupees"),
    ],
)
def test_amount_to_spoken(amount: int, expected: str) -> None:
    assert amount_to_spoken(amount) == expected


def test_integer_to_words_crore() -> None:
    assert integer_to_words(10_000_000) == "one crore"
    assert integer_to_words(0) == "zero"


def test_amount_has_no_symbols_or_digits() -> None:
    for amount in (8_000, 12_500, 45_000, 4_50_000):
        spoken = amount_to_spoken(amount)
        assert not _FORBIDDEN.search(spoken), spoken


def test_invoice_id_to_spoken() -> None:
    assert invoice_id_to_spoken("INV-4217") == "invoice I N V, four two one seven"
    assert invoice_id_to_spoken("INV-3301") == "invoice I N V, three three zero one"


def test_invoice_id_has_no_digits_or_symbols() -> None:
    for inv in ("INV-4217", "INV-9012", "INV-1451"):
        spoken = invoice_id_to_spoken(inv)
        assert not _FORBIDDEN.search(spoken), spoken


@pytest.mark.parametrize(
    "value,expected",
    [
        (date(2026, 9, 15), "the fifteenth of September"),
        (date(2026, 1, 1), "the first of January"),
        (date(2026, 3, 21), "the twenty first of March"),
        (date(2026, 12, 31), "the thirty first of December"),
    ],
)
def test_date_to_spoken(value: date, expected: str) -> None:
    assert date_to_spoken(value) == expected


def test_date_has_no_digits() -> None:
    assert not _FORBIDDEN.search(date_to_spoken(date(2026, 9, 15)))


def test_days_to_spoken() -> None:
    assert days_to_spoken(1) == "one day"
    assert days_to_spoken(45) == "forty five days"
    assert days_to_spoken(90) == "ninety days"


def test_phone_to_spoken() -> None:
    assert phone_to_spoken("+91 98765 43210") == (
        "plus nine one nine eight seven six five four three two one zero"
    )


def test_email_to_spoken() -> None:
    assert email_to_spoken("amit@acme.example") == (
        "a m i t at a c m e dot e x a m p l e"
    )


def test_negative_inputs_raise() -> None:
    with pytest.raises(ValueError):
        amount_to_spoken(-1)
    with pytest.raises(ValueError):
        integer_to_words(-5)
    with pytest.raises(ValueError):
        days_to_spoken(-1)
