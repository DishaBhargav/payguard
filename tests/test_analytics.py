"""Tests for payguard.analytics. Reminder of the rule: only APPROVED transactions count as spending."""
import unittest
from datetime import date
from decimal import Decimal

from payguard.analytics import daily_totals, summarize, top_accounts
from tests.helpers import make_tx


class SummaryTests(unittest.TestCase):
    def test_empty_input_gives_zeros_and_does_not_crash(self):
        summary = summarize([])
        self.assertEqual(summary.accepted_count, 0)
        self.assertEqual(summary.status_counts, {})
        self.assertEqual(summary.total_value, 0)
        self.assertEqual(summary.average_value, 0)
        self.assertEqual(summary.declined_value, 0)

    def test_declined_rows_are_counted_but_not_added_to_spending(self):
        transactions = [
            make_tx("TX1", "10.00", "approved"),
            make_tx("TX2", "20.00", "approved"),
            make_tx("TX3", "500.00", "declined"),
        ]
        summary = summarize(transactions)
        self.assertEqual(summary.accepted_count, 3)
        self.assertEqual(summary.status_counts, {"approved": 2, "declined": 1})
        self.assertEqual(summary.total_value, Decimal("30.00"))
        self.assertEqual(summary.average_value, Decimal("15.00"))     # 30 / 2 approved, not / 3
        self.assertEqual(summary.declined_value, Decimal("500.00"))

    def test_only_declined_transactions_means_zero_spending(self):
        summary = summarize([make_tx("TX1", "99.00", "declined")])
        self.assertEqual(summary.total_value, 0)
        self.assertEqual(summary.average_value, Decimal("0.00"))
        self.assertEqual(summary.declined_value, Decimal("99.00"))

    def test_money_is_exact_decimal_not_float(self):
        # With floats, 0.1 + 0.2 is 0.30000000000000004.
        summary = summarize([make_tx("TX1", "0.10"), make_tx("TX2", "0.20")])
        self.assertEqual(summary.total_value, Decimal("0.30"))

    def test_average_rounds_half_up_to_two_places(self):
        # 0.01 + 0.04 = 0.05; 0.05 / 2 = 0.025, which rounds up to 0.03.
        summary = summarize([make_tx("TX1", "0.01"), make_tx("TX2", "0.04")])
        self.assertEqual(summary.average_value, Decimal("0.03"))


class DailyTotalTests(unittest.TestCase):
    def test_totals_are_per_calendar_day_oldest_first(self):
        transactions = [
            make_tx("TX1", "10.00", when="2026-10-02 09:00:00"),
            make_tx("TX2", "5.00", when="2026-10-01 09:00:00"),
            make_tx("TX3", "7.50", when="2026-10-02 18:00:00", account_id="AC2"),
        ]
        totals = daily_totals(transactions)
        self.assertEqual(list(totals), [date(2026, 10, 1), date(2026, 10, 2)])
        self.assertEqual(totals[date(2026, 10, 1)], Decimal("5.00"))
        self.assertEqual(totals[date(2026, 10, 2)], Decimal("17.50"))

    def test_declined_rows_are_excluded_and_all_declined_days_are_omitted(self):
        transactions = [
            make_tx("TX1", "10.00", "approved", when="2026-10-01 09:00:00"),
            make_tx("TX2", "900.00", "declined", when="2026-10-01 10:00:00"),
            make_tx("TX3", "900.00", "declined", when="2026-10-02 10:00:00"),
        ]
        totals = daily_totals(transactions)
        self.assertEqual(totals, {date(2026, 10, 1): Decimal("10.00")})

    def test_midnight_splits_days(self):
        transactions = [
            make_tx("TX1", "1.00", when="2026-10-01 23:59:59"),
            make_tx("TX2", "2.00", when="2026-10-02 00:00:00"),
        ]
        totals = daily_totals(transactions)
        self.assertEqual(totals[date(2026, 10, 1)], Decimal("1.00"))
        self.assertEqual(totals[date(2026, 10, 2)], Decimal("2.00"))

    def test_empty_input(self):
        self.assertEqual(daily_totals([]), {})


class TopAccountTests(unittest.TestCase):
    def test_accounts_are_ranked_by_approved_total_highest_first(self):
        transactions = [
            make_tx("TX1", "10.00", account_id="AC1"),
            make_tx("TX2", "50.00", account_id="AC2"),
            make_tx("TX3", "5.00", account_id="AC1"),
            make_tx("TX4", "30.00", account_id="AC3"),
        ]
        self.assertEqual(top_accounts(transactions), [
            ("AC2", Decimal("50.00")),
            ("AC3", Decimal("30.00")),
            ("AC1", Decimal("15.00")),
        ])

    def test_limit_keeps_only_the_top_accounts(self):
        transactions = [make_tx(f"TX{n}", str(n), account_id=f"AC{n}") for n in range(1, 8)]
        result = top_accounts(transactions, limit=3)
        self.assertEqual([account for account, _ in result], ["AC7", "AC6", "AC5"])

    def test_ties_are_broken_by_account_id(self):
        transactions = [make_tx("TX1", "10.00", account_id="AC9"), make_tx("TX2", "10.00", account_id="AC2")]
        result = top_accounts(transactions)
        self.assertEqual([account for account, _ in result], ["AC2", "AC9"])

    def test_declined_spending_is_ignored(self):
        transactions = [
            make_tx("TX1", "10.00", "approved", account_id="AC1"),
            make_tx("TX2", "999.00", "declined", account_id="AC2"),
        ]
        self.assertEqual(top_accounts(transactions), [("AC1", Decimal("10.00"))])

    def test_empty_input_and_invalid_limit(self):
        self.assertEqual(top_accounts([]), [])
        with self.assertRaises(ValueError):
            top_accounts([make_tx()], limit=0)


if __name__ == "__main__":
    unittest.main()
