"""Shared definitions: the CSV schema and small data containers.

Every other module imports from here, so there is one place that says what a
transaction looks like and which values are allowed.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# ---- CSV schema -----------------------------------------------------------
REQUIRED_COLUMNS = ("transaction_id", "timestamp", "account_id", "amount", "merchant", "status")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
APPROVED = "approved"
DECLINED = "declined"
VALID_STATUSES = (APPROVED, DECLINED)
# Amounts above this are treated as data errors. This also stops absurd values
# such as 1e999999 from overflowing Decimal arithmetic later on.
MAX_AMOUNT = Decimal("1000000000000")


# ---- Data containers ------------------------------------------------------
# A dataclass is a normal class where Python writes __init__ for us.
# frozen=True means an object cannot be changed after it is created, which
# prevents a whole class of "who modified this?" bugs.

@dataclass(frozen=True)
class Transaction:
    """One accepted (valid) transaction."""

    source_line: int          # line number in the input file (header is line 1)
    transaction_id: str
    timestamp: datetime
    account_id: str
    amount: Decimal
    merchant: str
    status: str               # always lower case: "approved" or "declined"


@dataclass(frozen=True)
class ValidationIssue:
    """One rejected input row and every reason it was rejected."""

    source_line: int
    transaction_id: str       # may be empty if the row had no ID
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RuleConfig:
    """Thresholds for the three review rules (defaults match the sample data)."""

    high_value_threshold: Decimal = Decimal("1000.00")
    velocity_window_minutes: int = 5
    velocity_min_count: int = 3
    daily_spend_threshold: Decimal = Decimal("3000.00")

    def __post_init__(self):
        """Runs right after creation and rejects settings that make no sense."""
        if not self.high_value_threshold.is_finite() or self.high_value_threshold < 0:
            raise ValueError("high_value_threshold must be a finite number, 0 or more")
        if not self.daily_spend_threshold.is_finite() or self.daily_spend_threshold < 0:
            raise ValueError("daily_spend_threshold must be a finite number, 0 or more")
        if self.velocity_window_minutes < 1:
            raise ValueError("velocity_window_minutes must be at least 1")
        if self.velocity_min_count < 2:
            raise ValueError("velocity_min_count must be at least 2")


@dataclass(frozen=True)
class FlaggedTransaction:
    """An accepted transaction that matched at least one review rule.

    A flag means "a person may want to look at this", never "this is fraud".
    """

    transaction: Transaction
    reasons: tuple[str, ...]  # rule names, always in the fixed order of rules.RULE_ORDER
