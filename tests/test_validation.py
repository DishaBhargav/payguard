"""Tests for payguard.validation, using small hand-written rows with known outcomes."""
import unittest
from datetime import datetime
from decimal import Decimal

from payguard.models import MAX_AMOUNT, REQUIRED_COLUMNS
from payguard.validation import validate_rows
from tests.helpers import make_row


def reasons_for(row):
    """Validate one row on its own. Returns its rejection reasons, or () if accepted."""
    accepted, rejected = validate_rows([(2, row)])
    if rejected:
        return rejected[0].reasons
    return ()


class AcceptedRowTests(unittest.TestCase):
    def test_valid_row_is_accepted_with_correct_types(self):
        accepted, rejected = validate_rows([(7, make_row())])
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        tx = accepted[0]
        self.assertEqual(tx.source_line, 7)
        self.assertEqual(tx.transaction_id, "TX1")
        self.assertEqual(tx.timestamp, datetime(2026, 10, 1, 9, 0, 0))
        self.assertIsInstance(tx.amount, Decimal)
        self.assertEqual(tx.amount, Decimal("10.00"))
        self.assertEqual(tx.status, "approved")

    def test_spaces_are_trimmed_and_status_is_lowercased(self):
        row = make_row(transaction_id=" TX1 ", merchant=" Cafe ", status=" APPROVED ")
        tx = validate_rows([(2, row)])[0][0]
        self.assertEqual(tx.transaction_id, "TX1")
        self.assertEqual(tx.merchant, "Cafe")
        self.assertEqual(tx.status, "approved")

    def test_declined_status_is_accepted(self):
        self.assertEqual(reasons_for(make_row(status="Declined")), ())

    def test_empty_dataset_gives_two_empty_lists(self):
        self.assertEqual(validate_rows([]), ([], []))


class MissingFieldTests(unittest.TestCase):
    def test_each_required_field_when_blank_gives_exactly_one_reason(self):
        for column in REQUIRED_COLUMNS:
            with self.subTest(column=column):
                self.assertEqual(reasons_for(make_row(**{column: ""})),
                                 (f"missing required field: {column}",))

    def test_whitespace_only_counts_as_blank(self):
        self.assertEqual(reasons_for(make_row(account_id="   ")),
                         ("missing required field: account_id",))

    def test_field_absent_from_the_row_counts_as_blank(self):
        row = make_row()
        del row["status"]
        self.assertEqual(reasons_for(row), ("missing required field: status",))

    def test_row_with_surplus_fields_is_rejected(self):
        row = make_row()
        row["_extra"] = ["unexpected"]
        self.assertEqual(reasons_for(row), ("row has more fields than the header",))


class TimestampTests(unittest.TestCase):
    def test_bad_timestamps_are_rejected(self):
        bad_values = [
            "2026-13-45 25:61:00",     # impossible values
            "03/10/2026 10:00",        # wrong format
            "2026-10-05",              # date only
            "2026-10-05T09:00:00",     # ISO style with a T
            "2026-10-5 9:00:00",       # not zero-padded
            "not a date",
        ]
        for value in bad_values:
            with self.subTest(timestamp=value):
                reasons = reasons_for(make_row(timestamp=value))
                self.assertEqual(len(reasons), 1)
                self.assertIn("timestamp", reasons[0])

    def test_midnight_and_last_second_of_day_are_valid(self):
        for value in ("2026-10-05 00:00:00", "2026-10-05 23:59:59"):
            with self.subTest(timestamp=value):
                self.assertEqual(reasons_for(make_row(timestamp=value)), ())


class AmountTests(unittest.TestCase):
    def test_non_numeric_amounts_are_rejected(self):
        for value in ("abc", "12,50", "10 USD", "--5"):
            with self.subTest(amount=value):
                reasons = reasons_for(make_row(amount=value))
                self.assertEqual(len(reasons), 1)
                self.assertIn("not a number", reasons[0])

    def test_negative_amount_is_rejected(self):
        reasons = reasons_for(make_row(amount="-25.00"))
        self.assertEqual(len(reasons), 1)
        self.assertIn("negative", reasons[0])

    def test_zero_is_accepted_and_smallest_positive_amount_too(self):
        for value in ("0", "0.00", "0.01"):
            with self.subTest(amount=value):
                self.assertEqual(reasons_for(make_row(amount=value)), ())

    def test_nan_and_infinity_are_rejected(self):
        for value in ("NaN", "nan", "sNaN", "Infinity", "inf", "-Infinity"):
            with self.subTest(amount=value):
                reasons = reasons_for(make_row(amount=value))
                self.assertEqual(len(reasons), 1)
                self.assertIn("finite", reasons[0])

    def test_maximum_amount_boundary(self):
        self.assertEqual(reasons_for(make_row(amount=str(MAX_AMOUNT))), ())
        self.assertEqual(len(reasons_for(make_row(amount=str(MAX_AMOUNT + Decimal("0.01"))))), 1)

    def test_absurdly_large_exponent_is_rejected_without_crashing(self):
        reasons = reasons_for(make_row(amount="1e999999"))
        self.assertEqual(len(reasons), 1)
        self.assertIn("maximum", reasons[0])


class StatusTests(unittest.TestCase):
    def test_unsupported_statuses_are_rejected(self):
        for value in ("refunded", "pending", "approve"):
            with self.subTest(status=value):
                reasons = reasons_for(make_row(status=value))
                self.assertEqual(len(reasons), 1)
                self.assertIn("status", reasons[0])


class MultipleReasonTests(unittest.TestCase):
    def test_every_problem_in_a_row_is_reported(self):
        row = make_row(timestamp="yesterday", amount="abc", status="refunded", merchant="")
        reasons = reasons_for(row)
        self.assertEqual(len(reasons), 4)
        joined = " | ".join(reasons)
        for word in ("merchant", "timestamp", "amount", "status"):
            self.assertIn(word, joined)


class DuplicateIdTests(unittest.TestCase):
    def test_first_row_wins_and_later_copy_is_rejected(self):
        rows = [
            (2, make_row(transaction_id="TX1", amount="10.00")),
            (3, make_row(transaction_id="TX1", amount="5000.00")),
        ]
        accepted, rejected = validate_rows(rows)
        self.assertEqual([t.amount for t in accepted], [Decimal("10.00")])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_line, 3)
        self.assertIn("duplicate", rejected[0].reasons[0])
        self.assertIn("line 2", rejected[0].reasons[0])

    def test_every_later_copy_is_rejected(self):
        rows = [(line, make_row(transaction_id="TX1")) for line in (2, 3, 4)]
        accepted, rejected = validate_rows(rows)
        self.assertEqual(len(accepted), 1)
        self.assertEqual([issue.source_line for issue in rejected], [3, 4])

    def test_rejected_row_does_not_claim_its_id(self):
        rows = [
            (2, make_row(transaction_id="TX1", amount="abc")),    # rejected: bad amount
            (3, make_row(transaction_id="TX1", amount="10.00")),  # valid, so accepted
        ]
        accepted, rejected = validate_rows(rows)
        self.assertEqual([t.source_line for t in accepted], [3])
        self.assertEqual([issue.source_line for issue in rejected], [2])
        self.assertNotIn("duplicate", rejected[0].reasons[0])

    def test_ids_are_case_sensitive(self):
        rows = [(2, make_row(transaction_id="TX1")), (3, make_row(transaction_id="tx1"))]
        accepted, rejected = validate_rows(rows)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(rejected, [])

    def test_spaces_around_an_id_do_not_hide_a_duplicate(self):
        rows = [(2, make_row(transaction_id="TX1")), (3, make_row(transaction_id="  TX1 "))]
        accepted, rejected = validate_rows(rows)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)

    def test_duplicate_with_another_problem_reports_both(self):
        rows = [(2, make_row(transaction_id="TX1")), (3, make_row(transaction_id="TX1", status="refunded"))]
        _, rejected = validate_rows(rows)
        self.assertEqual(len(rejected[0].reasons), 2)


class NoDoubleCountingTests(unittest.TestCase):
    def test_every_row_ends_up_in_exactly_one_list(self):
        rows = [
            (2, make_row(transaction_id="TX1")),
            (3, make_row(transaction_id="TX2", amount="-1")),
            (4, make_row(transaction_id="TX1")),
            (5, make_row(transaction_id="TX3")),
            (6, make_row(transaction_id="", amount="5")),
        ]
        accepted, rejected = validate_rows(rows)
        accepted_lines = {t.source_line for t in accepted}
        rejected_lines = {issue.source_line for issue in rejected}
        self.assertEqual(accepted_lines, {2, 5})
        self.assertEqual(rejected_lines, {3, 4, 6})
        self.assertEqual(accepted_lines & rejected_lines, set())

    def test_source_line_numbers_are_preserved(self):
        rows = [(12, make_row(transaction_id="A")), (40, make_row(transaction_id="B", amount="x"))]
        accepted, rejected = validate_rows(rows)
        self.assertEqual(accepted[0].source_line, 12)
        self.assertEqual(rejected[0].source_line, 40)
        self.assertEqual(rejected[0].transaction_id, "B")


if __name__ == "__main__":
    unittest.main()
