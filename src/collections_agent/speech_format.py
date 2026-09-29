"""Deterministic conversion of amounts, dates, and IDs to spoken text.

The LLM's output goes straight to TTS, so this module produces speech-safe
strings (PRD §5.4):
- Currency: words, not symbols ("twelve thousand five hundred rupees").
- Amounts use the Indian numbering system (lakh / crore).
- Invoice numbers: digit by digit ("invoice I N V, four two one seven").
- Dates: spoken form, day + month, no year ("the fifteenth of September").
- Phone numbers / emails: spelled out character by character.
- No symbols, digits, markdown, or hyphens in the output. Compound number
  words are joined with spaces ("forty five", not "forty-five") so that no
  hyphen ever reaches the TTS or trips the eval symbol checks.

Everything here is pure and deterministic, which keeps it unit-testable and
means the LLM never has to do the conversion itself.
"""

from __future__ import annotations

import re
from datetime import date

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
]

_DIGIT_WORDS = _ONES[:10]

_MONTHS = [
    "", "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]

# Ordinal words for days of the month (1-31), space-joined, no hyphens.
_ORDINALS = {
    1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
    6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth",
    11: "eleventh", 12: "twelfth", 13: "thirteenth", 14: "fourteenth",
    15: "fifteenth", 16: "sixteenth", 17: "seventeenth", 18: "eighteenth",
    19: "nineteenth", 20: "twentieth", 21: "twenty first",
    22: "twenty second", 23: "twenty third", 24: "twenty fourth",
    25: "twenty fifth", 26: "twenty sixth", 27: "twenty seventh",
    28: "twenty eighth", 29: "twenty ninth", 30: "thirtieth",
    31: "thirty first",
}


def _under_hundred(n: int) -> str:
    """Words for 0..99, space-joined (e.g. 45 -> 'forty five')."""
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    if ones == 0:
        return _TENS[tens]
    return f"{_TENS[tens]} {_ONES[ones]}"


def _under_thousand(n: int) -> str:
    """Words for 0..999 (e.g. 500 -> 'five hundred', 123 -> 'one hundred twenty three')."""
    if n < 100:
        return _under_hundred(n)
    hundreds, rest = divmod(n, 100)
    if rest == 0:
        return f"{_ONES[hundreds]} hundred"
    return f"{_ONES[hundreds]} hundred {_under_hundred(rest)}"


def integer_to_words(n: int) -> str:
    """Convert a non-negative integer to words using the Indian numbering system.

    Groups by crore (10,000,000), lakh (100,000), thousand, and the final
    0..999. Examples::

        12500   -> "twelve thousand five hundred"
        450000  -> "four lakh fifty thousand"
        10000000 -> "one crore"
    """
    if n < 0:
        raise ValueError("integer_to_words does not support negative numbers")
    if n == 0:
        return "zero"

    crore, rest = divmod(n, 10_000_000)
    lakh, rest = divmod(rest, 100_000)
    thousand, rest = divmod(rest, 1_000)
    hundreds = rest  # 0..999

    parts: list[str] = []
    if crore:
        # Recurse so very large crore counts still read correctly.
        parts.append(f"{integer_to_words(crore)} crore")
    if lakh:
        parts.append(f"{_under_thousand(lakh)} lakh")
    if thousand:
        parts.append(f"{_under_thousand(thousand)} thousand")
    if hundreds:
        parts.append(_under_thousand(hundreds))
    return " ".join(parts)


def amount_to_spoken(amount_inr: int) -> str:
    """Convert whole rupees to spoken words, e.g. 12500 -> 'twelve thousand five hundred rupees'."""
    if amount_inr < 0:
        raise ValueError("amount_to_spoken does not support negative amounts")
    return f"{integer_to_words(amount_inr)} rupees"


def _spell_alnum_segment(segment: str) -> str:
    """Spell one alphanumeric run: letters as spaced capitals, digits as words."""
    tokens: list[str] = []
    for ch in segment:
        if ch.isalpha():
            tokens.append(ch.upper())
        else:  # digit
            tokens.append(_DIGIT_WORDS[int(ch)])
    return " ".join(tokens)


def id_to_spoken(identifier: str) -> str:
    """Spell an alphanumeric id character by character.

    Non-alphanumeric separators (e.g. hyphens) become comma boundaries::

        "INV-4217" -> "I N V, four two one seven"
    """
    segments = [s for s in re.split(r"[^A-Za-z0-9]+", identifier) if s]
    return ", ".join(_spell_alnum_segment(s) for s in segments)


def invoice_id_to_spoken(invoice_id: str) -> str:
    """Spoken invoice reference, e.g. 'INV-4217' -> 'invoice I N V, four two one seven'."""
    return f"invoice {id_to_spoken(invoice_id)}"


def date_to_spoken(value: date) -> str:
    """Spoken date, day + month only (no year), e.g. 'the fifteenth of September'."""
    return f"the {_ORDINALS[value.day]} of {_MONTHS[value.month]}"


def days_to_spoken(days: int) -> str:
    """Spoken day count, e.g. 45 -> 'forty five days', 1 -> 'one day'."""
    if days < 0:
        raise ValueError("days_to_spoken does not support negative values")
    unit = "day" if days == 1 else "days"
    return f"{integer_to_words(days)} {unit}"


def phone_to_spoken(phone: str) -> str:
    """Spell a phone number character by character.

    Digits become words, '+' becomes 'plus', and other separators are dropped::

        "+91 98765 43210" -> "plus nine one nine eight seven six five four three two one zero"
    """
    tokens: list[str] = []
    for ch in phone:
        if ch.isdigit():
            tokens.append(_DIGIT_WORDS[int(ch)])
        elif ch == "+":
            tokens.append("plus")
        # spaces, hyphens, parentheses etc. are separators -> skip
    return " ".join(tokens)


_EMAIL_SYMBOLS = {
    "@": "at",
    ".": "dot",
    "-": "dash",
    "_": "underscore",
    "+": "plus",
}


def email_to_spoken(email: str) -> str:
    """Spell an email character by character.

    Letters become spaced lower-case letters, digits become words, and the
    common symbols are named::

        "amit@acme.example" ->
            "a m i t at a c m e dot e x a m p l e"
    """
    tokens: list[str] = []
    for ch in email:
        if ch.isalpha():
            tokens.append(ch.lower())
        elif ch.isdigit():
            tokens.append(_DIGIT_WORDS[int(ch)])
        elif ch in _EMAIL_SYMBOLS:
            tokens.append(_EMAIL_SYMBOLS[ch])
        # anything else is skipped
    return " ".join(tokens)
