"""Small builders shared by the test files, so each test only states what matters."""
from datetime import datetime
from decimal import Decimal

from payguard.models import TIMESTAMP_FORMAT, Transaction


def make_tx(transaction_id="TX1", amount="10.00", status="approved",
            account_id="AC1", when="2026-10-01 09:00:00", line=2):
    """Build an accepted Transaction from plain strings."""
    return Transaction(
        source_line=line,
        transaction_id=transaction_id,
        timestamp=datetime.strptime(when, TIMESTAMP_FORMAT),
        account_id=account_id,
        amount=Decimal(amount),
        merchant="Test Merchant",
        status=status,
    )


def make_row(**overrides):
    """Build a raw CSV row (all text). Pass keyword arguments to change fields."""
    row = {
        "transaction_id": "TX1",
        "timestamp": "2026-10-01 09:00:00",
        "account_id": "AC1",
        "amount": "10.00",
        "merchant": "Test Merchant",
        "status": "approved",
    }
    row.update(overrides)
    return row
