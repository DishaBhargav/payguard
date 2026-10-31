"""The review rules.

IMPORTANT: a rule match is a REVIEW FLAG. It means "a person may want to look
at this", not "this is fraud". Large amounts and bursts of payments are often
perfectly normal.

Three rules, each a separate function that can be tested on its own:

HIGH_VALUE        amount STRICTLY GREATER than the threshold.
                  Looks at every accepted transaction, approved or declined,
                  because a declined large attempt is still worth a look.

VELOCITY          at least `min_count` transactions from the SAME account inside
                  a window of `window_minutes`. The window is INCLUSIVE: rows
                  exactly `window_minutes` apart still fit together.
                  Looks at every accepted transaction, approved or declined.
                  Every row that belongs to such a window is flagged.

HIGH_DAILY_SPEND  an account's APPROVED total for one calendar day is STRICTLY
                  GREATER than the threshold. Declined rows do not count towards
                  the total and are never flagged by this rule. Every approved
                  row of that account on that day is flagged.

apply_rules() runs all three and merges the results so each transaction
appears at most once, with all of its reasons.

This module is pure logic: it does no file or terminal I/O.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from payguard.analytics import approved_only
from payguard.models import FlaggedTransaction, RuleConfig, Transaction

HIGH_VALUE = "HIGH_VALUE"
VELOCITY = "VELOCITY"
HIGH_DAILY_SPEND = "HIGH_DAILY_SPEND"

# Reasons are always listed in this order, so the output never changes between runs.
RULE_ORDER = (HIGH_VALUE, VELOCITY, HIGH_DAILY_SPEND)


def find_high_value(transactions: list[Transaction], threshold: Decimal) -> list[Transaction]:
    """Transactions whose amount is strictly greater than the threshold."""
    return [t for t in transactions if t.amount > threshold]


def time_order(t: Transaction) -> tuple:
    """Sort key: earliest first; equal timestamps are ordered by ID so ties are deterministic."""
    return (t.timestamp, t.transaction_id)


def find_velocity(transactions: list[Transaction], window_minutes: int, min_count: int) -> list[Transaction]:
    """Transactions that belong to a burst: min_count or more from one account within the window.

    Method (a "sliding window"): per account, sort by time. Walk through the
    rows with an `end` position. Keep a `start` position as far back as
    possible while the rows from start to end still fit inside the window. If
    that stretch holds at least min_count rows, flag all of them.
    """
    window = timedelta(minutes=window_minutes)

    by_account = defaultdict(list)
    for t in transactions:
        by_account[t.account_id].append(t)

    flagged_ids = set()
    for account_rows in by_account.values():
        account_rows.sort(key=time_order)
        start = 0
        for end in range(len(account_rows)):
            # Too wide? Drop the oldest row from the window. ">" (not ">=") is
            # what makes the window inclusive.
            while start < end and account_rows[end].timestamp - account_rows[start].timestamp > window:
                start += 1
            if end - start + 1 >= min_count:
                for t in account_rows[start:end + 1]:
                    flagged_ids.add(t.transaction_id)

    # Return in the original input order, not in the order we happened to find them.
    return [t for t in transactions if t.transaction_id in flagged_ids]


def find_high_daily_spend(transactions: list[Transaction], threshold: Decimal) -> list[Transaction]:
    """Approved transactions that make up an account-day total strictly above the threshold.

    A day is the date part of the timestamp (no time zones).
    """
    approved = approved_only(transactions)

    totals = defaultdict(Decimal)
    for t in approved:
        totals[(t.account_id, t.timestamp.date())] += t.amount

    return [t for t in approved if totals[(t.account_id, t.timestamp.date())] > threshold]


def apply_rules(transactions: list[Transaction], config: RuleConfig) -> list[FlaggedTransaction]:
    """Run every rule and merge the matches: one result per transaction, all reasons kept.

    The input must have unique transaction IDs, which validate_rows() guarantees.
    Results follow the input order.
    """
    ids = [t.transaction_id for t in transactions]
    if len(ids) != len(set(ids)):
        raise ValueError("transaction IDs must be unique; run validate_rows() first")

    matches = {
        HIGH_VALUE: find_high_value(transactions, config.high_value_threshold),
        VELOCITY: find_velocity(transactions, config.velocity_window_minutes, config.velocity_min_count),
        HIGH_DAILY_SPEND: find_high_daily_spend(transactions, config.daily_spend_threshold),
    }

    reasons_by_id = defaultdict(list)
    for rule_name in RULE_ORDER:
        for t in matches[rule_name]:
            reasons_by_id[t.transaction_id].append(rule_name)

    return [
        FlaggedTransaction(t, tuple(reasons_by_id[t.transaction_id]))
        for t in transactions
        if t.transaction_id in reasons_by_id
    ]
