"""Turn raw CSV rows into accepted transactions or rejected rows with reasons.

This module is pure logic: it never opens files. It receives the rows that
loader.load_rows() produced and returns two lists.

A row is accepted only if ALL of these hold:
- All six required fields are present and not blank (spaces are trimmed).
- timestamp matches YYYY-MM-DD HH:MM:SS exactly (zero-padded).
- amount is a finite number from 0 up to MAX_AMOUNT (zero is allowed).
- status is "approved" or "declined", in any letter case.
- The row has no surplus fields.
- Its transaction_id was not already accepted earlier in the file.

Every problem found in a row is reported, not just the first one.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from payguard.models import (
    MAX_AMOUNT,
    REQUIRED_COLUMNS,
    TIMESTAMP_FORMAT,
    VALID_STATUSES,
    Transaction,
    ValidationIssue,
)

RawRow = dict[str, Any]


def clean(row: RawRow, column: str) -> str:
    """Return a field as trimmed text, or "" if the field is missing."""
    value = row.get(column)
    if isinstance(value, str):
        return value.strip()
    return ""


def parse_timestamp(text: str) -> datetime | None:
    """Parse YYYY-MM-DD HH:MM:SS, or return None if the text does not match exactly."""
    try:
        parsed = datetime.strptime(text, TIMESTAMP_FORMAT)
    except ValueError:
        return None
    # strptime is forgiving ("2026-10-5 9:00:00" works), so write the value
    # back out and insist it is identical to what we were given.
    if parsed.strftime(TIMESTAMP_FORMAT) != text:
        return None
    return parsed


def parse_amount(text: str) -> tuple[Decimal | None, str | None]:
    """Return (amount, None) if the text is a usable amount, else (None, reason)."""
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None, f"amount is not a number: {text!r}"
    # Decimal happily accepts "NaN" and "Infinity", so they need their own check.
    if not amount.is_finite():
        return None, f"amount must be a finite number: {text!r}"
    if amount < 0:
        return None, f"amount cannot be negative: {text!r}"
    if amount > MAX_AMOUNT:
        return None, f"amount is above the allowed maximum of {MAX_AMOUNT}: {text!r}"
    return amount, None


def parse_row(source_line: int, row: RawRow) -> tuple[Transaction | None, list[str]]:
    """Check one row on its own (duplicates are checked later, across rows).

    Returns (transaction, []) for a good row, or (None, reasons) for a bad one.
    """
    reasons = []

    if "_extra" in row:
        reasons.append("row has more fields than the header")

    values = {}
    for column in REQUIRED_COLUMNS:
        values[column] = clean(row, column)
        if not values[column]:
            reasons.append(f"missing required field: {column}")

    # Format checks only run on fields that are present, so one empty field
    # produces one reason, not two.
    timestamp = None
    if values["timestamp"]:
        timestamp = parse_timestamp(values["timestamp"])
        if timestamp is None:
            reasons.append(f"invalid timestamp {values['timestamp']!r}; expected YYYY-MM-DD HH:MM:SS")

    amount = None
    if values["amount"]:
        amount, amount_problem = parse_amount(values["amount"])
        if amount_problem:
            reasons.append(amount_problem)

    status = values["status"].lower()
    if status and status not in VALID_STATUSES:
        reasons.append(f"unsupported status {values['status']!r}; allowed: {', '.join(VALID_STATUSES)}")

    if reasons:
        return None, reasons

    transaction = Transaction(
        source_line=source_line,
        transaction_id=values["transaction_id"],
        timestamp=timestamp,
        account_id=values["account_id"],
        amount=amount,
        merchant=values["merchant"],
        status=status,
    )
    return transaction, []


def validate_rows(raw_rows: list[tuple[int, RawRow]]) -> tuple[list[Transaction], list[ValidationIssue]]:
    """Validate every row. Returns (accepted, rejected); nothing is silently dropped.

    Duplicate policy: the first ACCEPTED row keeps a transaction_id. Later rows
    with the same ID are rejected. A rejected row never claims an ID, so a valid
    row that comes after it is still accepted. IDs are compared exactly (after
    trimming spaces), so "TX1" and "tx1" are different IDs.
    """
    accepted = []
    rejected = []
    accepted_on_line = {}   # transaction_id -> line where it was accepted

    for source_line, row in raw_rows:
        transaction, reasons = parse_row(source_line, row)
        transaction_id = clean(row, "transaction_id")

        if transaction_id in accepted_on_line:
            first_line = accepted_on_line[transaction_id]
            reasons.append(f"duplicate transaction_id {transaction_id!r}: already accepted on line {first_line}")

        if reasons:
            rejected.append(ValidationIssue(source_line, transaction_id, tuple(reasons)))
        else:
            accepted.append(transaction)
            accepted_on_line[transaction_id] = source_line

    return accepted, rejected
