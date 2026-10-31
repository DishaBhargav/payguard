"""Tests for payguard.rules, using small hand-written fixtures with known answers.

Defaults used in the examples: HIGH_VALUE > 1000.00, VELOCITY 3 within 5 minutes
(inclusive), HIGH_DAILY_SPEND > 3000.00 using approved rows only.
"""
import random
import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from payguard.models import FlaggedTransaction, RuleConfig
from payguard.rules import (
    HIGH_DAILY_SPEND,
    HIGH_VALUE,
    RULE_ORDER,
    VELOCITY,
    apply_rules,
    find_high_daily_spend,
    find_high_value,
    find_velocity,
)
from tests.helpers import make_tx

DAY = "2026-10-05"


def at(*times):
    """Full timestamps on the example day from short HH:MM:SS strings."""
    return [f"{DAY} {t}" for t in times]


def txs(account, whens, amount="20.00", status="approved"):
    """One transaction per timestamp for one account, with unique IDs like A-1, A-2."""
    return [make_tx(f"{account}-{n}", amount, status, account, when) for n, when in enumerate(whens, start=1)]


def ids(transactions):
    return [t.transaction_id for t in transactions]


class HighValueTests(unittest.TestCase):
    def test_threshold_boundary_is_strictly_greater(self):
        rows = [make_tx("T1", "999.99"), make_tx("T2", "1000.00"), make_tx("T3", "1000.01")]
        self.assertEqual(ids(find_high_value(rows, Decimal("1000.00"))), ["T3"])

    def test_declined_transactions_are_checked_too(self):
        rows = [make_tx("T1", "2500.00", "declined")]
        self.assertEqual(ids(find_high_value(rows, Decimal("1000.00"))), ["T1"])

    def test_custom_threshold(self):
        rows = [make_tx("T1", "50.00"), make_tx("T2", "50.01")]
        self.assertEqual(ids(find_high_value(rows, Decimal("50.00"))), ["T2"])

    def test_results_keep_input_order(self):
        rows = [make_tx("T9", "2000.00"), make_tx("T1", "3000.00")]
        self.assertEqual(ids(find_high_value(rows, Decimal("1000.00"))), ["T9", "T1"])

    def test_empty_input(self):
        self.assertEqual(find_high_value([], Decimal("1000.00")), [])


class VelocityTests(unittest.TestCase):
    def test_three_transactions_exactly_five_minutes_apart_are_flagged(self):
        rows = txs("A", at("09:00:00", "09:02:30", "09:05:00"))
        self.assertEqual(ids(find_velocity(rows, 5, 3)), ["A-1", "A-2", "A-3"])

    def test_five_minutes_and_one_second_is_not_flagged(self):
        rows = txs("A", at("09:00:00", "09:02:30", "09:05:01"))
        self.assertEqual(find_velocity(rows, 5, 3), [])

    def test_burst_is_flagged_but_a_stray_later_transaction_is_not(self):
        rows = txs("A", at("10:00:00", "10:01:00", "10:02:00", "10:09:00"))
        self.assertEqual(ids(find_velocity(rows, 5, 3)), ["A-1", "A-2", "A-3"])

    def test_late_burst_flags_only_its_own_rows(self):
        rows = txs("A", at("09:00:00", "09:10:00", "09:11:00", "09:12:00"))
        self.assertEqual(ids(find_velocity(rows, 5, 3)), ["A-2", "A-3", "A-4"])

    def test_overlapping_windows_flag_every_row_in_a_rolling_chain(self):
        # No single 5-minute window holds all five rows, but each row sits in a window of three.
        rows = txs("A", at("12:00:00", "12:02:00", "12:04:00", "12:06:00", "12:08:00"))
        self.assertEqual(len(find_velocity(rows, 5, 3)), 5)

    def test_two_transactions_are_below_the_minimum_count(self):
        rows = txs("A", at("15:00:00", "15:01:00"))
        self.assertEqual(find_velocity(rows, 5, 3), [])

    def test_minimum_count_boundary(self):
        three = txs("A", at("09:00:00", "09:01:00", "09:02:00"))
        four = txs("B", at("09:00:00", "09:01:00", "09:02:00", "09:03:00"))
        self.assertEqual(find_velocity(three, 5, 4), [])
        self.assertEqual(len(find_velocity(four, 5, 4)), 4)

    def test_declined_transactions_count_towards_velocity(self):
        rows = txs("A", at("13:00:00", "13:00:40", "13:01:20"), amount="1.00", status="declined")
        self.assertEqual(len(find_velocity(rows, 5, 3)), 3)

    def test_identical_timestamps_still_count(self):
        rows = txs("A", at("14:00:00", "14:00:00", "14:00:00"))
        self.assertEqual(len(find_velocity(rows, 5, 3)), 3)

    def test_window_ignores_midnight(self):
        rows = txs("A", ["2026-10-06 23:58:00", "2026-10-06 23:59:30", "2026-10-07 00:01:00"])
        self.assertEqual(len(find_velocity(rows, 5, 3)), 3)

    def test_different_accounts_are_never_mixed(self):
        rows = (txs("A", at("09:00:00")) + txs("B", at("09:00:10")) + txs("C", at("09:00:20")))
        self.assertEqual(find_velocity(rows, 5, 3), [])

    def test_input_order_does_not_matter_and_output_keeps_input_order(self):
        rows = txs("A", at("09:00:00", "09:01:00", "09:02:00"))
        reversed_rows = list(reversed(rows))
        self.assertEqual(ids(find_velocity(reversed_rows, 5, 3)), ["A-3", "A-2", "A-1"])

    def test_rows_listed_out_of_time_order_are_still_judged_by_their_times(self):
        # In file order the 09:12 row sits between the others; sorting by time must pull the burst together.
        rows = [
            make_tx("A-1", account_id="A", when=f"{DAY} 09:00:00"),
            make_tx("A-2", account_id="A", when=f"{DAY} 09:12:00"),
            make_tx("A-3", account_id="A", when=f"{DAY} 09:01:00"),
            make_tx("A-4", account_id="A", when=f"{DAY} 09:02:00"),
        ]
        self.assertEqual(ids(find_velocity(rows, 5, 3)), ["A-1", "A-3", "A-4"])

    def test_custom_window_and_count(self):
        near = txs("A", at("09:00:00", "09:09:00"))
        far = txs("B", at("09:00:00", "09:11:00"))
        self.assertEqual(len(find_velocity(near, 10, 2)), 2)
        self.assertEqual(find_velocity(far, 10, 2), [])

    def test_large_burst_is_all_flagged(self):
        rows = txs("A", [f"{DAY} 09:00:{second:02d}" for second in range(10)])
        self.assertEqual(len(find_velocity(rows, 5, 3)), 10)

    def test_empty_and_single_inputs(self):
        self.assertEqual(find_velocity([], 5, 3), [])
        self.assertEqual(find_velocity(txs("A", at("09:00:00")), 5, 3), [])

    def test_fast_algorithm_agrees_with_a_slow_obvious_one_on_random_data(self):
        rng = random.Random(1234)          # fixed seed, so this test is deterministic
        start = datetime(2026, 10, 5, 9, 0, 0)
        for trial in range(200):
            rows = []
            for n in range(30):
                when = (start + timedelta(seconds=rng.randint(0, 1200))).strftime("%Y-%m-%d %H:%M:%S")
                rows.append(make_tx(f"T{n}", "10.00", account_id=rng.choice(["A", "B", "C", "D"]), when=when))
            self.assertEqual(set(ids(find_velocity(rows, 5, 3))), slow_velocity(rows, 5, 3),
                             msg=f"disagreement in trial {trial}")


def slow_velocity(rows, window_minutes, min_count):
    """Obviously-correct (but slow) reference: try every row as the start of a window."""
    window = timedelta(minutes=window_minutes)
    flagged = set()
    for first in rows:
        in_window = [r for r in rows
                     if r.account_id == first.account_id
                     and first.timestamp <= r.timestamp <= first.timestamp + window]
        if len(in_window) >= min_count:
            flagged.update(r.transaction_id for r in in_window)
    return flagged


class HighDailySpendTests(unittest.TestCase):
    def test_total_exactly_at_threshold_is_not_flagged(self):
        rows = txs("A", at("09:00:00", "13:00:00", "17:00:00"), amount="1000.00")
        self.assertEqual(find_high_daily_spend(rows, Decimal("3000.00")), [])

    def test_total_one_cent_over_flags_every_row_of_that_day(self):
        rows = [
            make_tx("A-1", "1000.00", when="2026-10-08 09:00:00"),
            make_tx("A-2", "1000.00", when="2026-10-08 13:00:00"),
            make_tx("A-3", "1000.01", when="2026-10-08 17:00:00"),
        ]
        self.assertEqual(ids(find_high_daily_spend(rows, Decimal("3000.00"))), ["A-1", "A-2", "A-3"])

    def test_declined_rows_do_not_count_towards_the_total(self):
        approved = txs("A", at("09:00:00", "13:00:00", "17:00:00"), amount="900.00")   # 2700.00
        declined = [make_tx("A-D", "900.00", "declined", "A", f"{DAY} 20:00:00")]       # would make 3600.00
        self.assertEqual(find_high_daily_spend(approved + declined, Decimal("3000.00")), [])

    def test_declined_rows_are_not_flagged_even_on_a_flagged_day(self):
        approved = [make_tx("A-1", "3000.01", when=f"{DAY} 09:00:00")]
        declined = [make_tx("A-D", "10.00", "declined", "A", f"{DAY} 10:00:00")]
        self.assertEqual(ids(find_high_daily_spend(approved + declined, Decimal("3000.00"))), ["A-1"])

    def test_days_are_never_combined(self):
        rows = [
            make_tx("A-1", "2000.00", when="2026-10-08 09:00:00"),
            make_tx("A-2", "2000.00", when="2026-10-09 09:00:00"),
        ]
        self.assertEqual(find_high_daily_spend(rows, Decimal("3000.00")), [])

    def test_midnight_starts_a_new_day(self):
        rows = [
            make_tx("A-1", "2000.00", when="2026-10-08 23:59:59"),
            make_tx("A-2", "2000.00", when="2026-10-09 00:00:00"),
        ]
        self.assertEqual(find_high_daily_spend(rows, Decimal("3000.00")), [])

    def test_accounts_are_never_combined(self):
        rows = [make_tx("A-1", "2000.00", account_id="A"), make_tx("B-1", "2000.00", account_id="B")]
        self.assertEqual(find_high_daily_spend(rows, Decimal("3000.00")), [])

    def test_empty_input(self):
        self.assertEqual(find_high_daily_spend([], Decimal("3000.00")), [])


class ApplyRulesTests(unittest.TestCase):
    def test_one_transaction_matching_three_rules_gives_one_row_with_three_reasons(self):
        rows = txs("A", at("15:00:00", "15:01:00", "15:02:00"), amount="1200.00")   # 3600.00 in total
        flagged = apply_rules(rows, RuleConfig())
        self.assertEqual(len(flagged), 3)
        for item in flagged:
            self.assertEqual(item.reasons, (HIGH_VALUE, VELOCITY, HIGH_DAILY_SPEND))

    def test_reasons_follow_the_fixed_rule_order(self):
        rows = txs("A", at("15:00:00", "15:01:00", "15:02:00"), amount="1200.00")
        self.assertEqual(apply_rules(rows, RuleConfig())[0].reasons, RULE_ORDER)

    def test_each_rule_only_adds_its_own_reason(self):
        rows = [make_tx("T1", "1000.01"), make_tx("T2", "20.00", account_id="OTHER")]
        flagged = apply_rules(rows, RuleConfig())
        self.assertEqual([(f.transaction.transaction_id, f.reasons) for f in flagged],
                         [("T1", (HIGH_VALUE,))])

    def test_no_transaction_appears_twice(self):
        rows = txs("A", at("15:00:00", "15:01:00", "15:02:00"), amount="1200.00")
        flagged = apply_rules(rows, RuleConfig())
        flagged_ids = [f.transaction.transaction_id for f in flagged]
        self.assertEqual(len(flagged_ids), len(set(flagged_ids)))

    def test_results_follow_input_order(self):
        rows = [make_tx("T2", "2000.00", account_id="X"), make_tx("T1", "2000.00", account_id="Y")]
        flagged = apply_rules(rows, RuleConfig())
        self.assertEqual([f.transaction.transaction_id for f in flagged], ["T2", "T1"])

    def test_nothing_matching_gives_an_empty_list(self):
        self.assertEqual(apply_rules([make_tx("T1", "5.00")], RuleConfig()), [])
        self.assertEqual(apply_rules([], RuleConfig()), [])

    def test_duplicate_ids_are_refused(self):
        rows = [make_tx("T1", "2000.00"), make_tx("T1", "3000.00")]
        with self.assertRaises(ValueError):
            apply_rules(rows, RuleConfig())

    def test_custom_settings_are_used(self):
        rows = [make_tx("T1", "60.00")]
        self.assertEqual(apply_rules(rows, RuleConfig()), [])
        flagged = apply_rules(rows, RuleConfig(high_value_threshold=Decimal("50.00")))
        self.assertIsInstance(flagged[0], FlaggedTransaction)
        self.assertEqual(flagged[0].reasons, (HIGH_VALUE,))


class RuleConfigTests(unittest.TestCase):
    def test_defaults(self):
        config = RuleConfig()
        self.assertEqual(config.high_value_threshold, Decimal("1000.00"))
        self.assertEqual(config.velocity_window_minutes, 5)
        self.assertEqual(config.velocity_min_count, 3)
        self.assertEqual(config.daily_spend_threshold, Decimal("3000.00"))

    def test_nonsense_settings_are_refused(self):
        bad_settings = [
            {"high_value_threshold": Decimal("-1")},
            {"high_value_threshold": Decimal("NaN")},
            {"daily_spend_threshold": Decimal("-0.01")},
            {"daily_spend_threshold": Decimal("Infinity")},
            {"velocity_window_minutes": 0},
            {"velocity_min_count": 1},
        ]
        for settings in bad_settings:
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):
                    RuleConfig(**settings)

    def test_edge_values_that_are_allowed(self):
        config = RuleConfig(high_value_threshold=Decimal("0"), daily_spend_threshold=Decimal("0"),
                            velocity_window_minutes=1, velocity_min_count=2)
        self.assertEqual(config.velocity_min_count, 2)


if __name__ == "__main__":
    unittest.main()
