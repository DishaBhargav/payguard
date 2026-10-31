"""Numbers that describe the accepted transactions.

The spending rule used by every money figure in this module:
    ONLY APPROVED transactions count as spending.

Declined transactions are still counted in accepted_count and status_counts,
and their combined value is reported separately as declined_value, but they
are left out of total_value, average_value, daily totals and top accounts.

This module is pure logic: it does no file or terminal I/O.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from payguard.models import APPROVED, DECLINED, Transaction

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Summary:
    """Headline numbers for a set of accepted transactions."""

    accepted_count: int               # every accepted row, approved or declined
    status_counts: dict[str, int]     # e.g. {"approved": 10, "declined": 2}
    total_value: Decimal              # sum of APPROVED amounts
    average_value: Decimal            # total_value / approved count, rounded half-up to 0.01
    declined_value: Decimal           # sum of DECLINED amounts, for information only


def approved_only(transactions: list[Transaction]) -> list[Transaction]:
    """Keep only the approved transactions."""
    return [t for t in transactions if t.status == APPROVED]


def summarize(transactions: list[Transaction]) -> Summary:
    """Count and total the accepted transactions."""
    status_counts = Counter(t.status for t in transactions)
    approved = approved_only(transactions)

    # Starting the sums at Decimal("0") keeps the result a Decimal even when empty.
    total = sum((t.amount for t in approved), Decimal("0"))
    declined_value = sum((t.amount for t in transactions if t.status == DECLINED), Decimal("0"))

    if approved:
        average = (total / len(approved)).quantize(CENT, rounding=ROUND_HALF_UP)
    else:
        average = Decimal("0.00")

    return Summary(
        accepted_count=len(transactions),
        status_counts=dict(sorted(status_counts.items())),
        total_value=total,
        average_value=average,
        declined_value=declined_value,
    )


def daily_totals(transactions: list[Transaction]) -> dict[date, Decimal]:
    """Approved spending per calendar day, oldest day first.

    A day is the date part of the timestamp (no time zones). Days that have no
    approved transactions do not appear.
    """
    totals = defaultdict(Decimal)
    for t in approved_only(transactions):
        totals[t.timestamp.date()] += t.amount
    return dict(sorted(totals.items()))


def account_rank(item: tuple[str, Decimal]) -> tuple[Decimal, str]:
    """Sort key: biggest total first; equal totals are ordered by account ID."""
    account_id, total = item
    return (-total, account_id)


def top_accounts(transactions: list[Transaction], limit: int = 5) -> list[tuple[str, Decimal]]:
    """The accounts with the highest approved spending, as (account_id, total) pairs."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    totals = defaultdict(Decimal)
    for t in approved_only(transactions):
        totals[t.account_id] += t.amount
    ranked = sorted(totals.items(), key=account_rank)
    return ranked[:limit]
