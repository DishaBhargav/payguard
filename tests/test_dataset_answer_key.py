"""Check PayGuard against the answer key that scripts/generate_data.py wrote.

data/planted_cases.csv says, for every planted row, whether it must be accepted
or rejected and which rules must flag it. The answer key was written by hand
(inside the generator) and never uses PayGuard's code, so agreement here means
validate_rows() and apply_rules() both behave as designed on the full dataset.
"""
import csv
import unittest
from pathlib import Path

from payguard.loader import load_rows
from payguard.models import RuleConfig
from payguard.rules import apply_rules
from payguard.validation import validate_rows

DATA_FOLDER = Path(__file__).resolve().parent.parent / "data"

# Every deliberately bad row has exactly one problem, and its rejection reason
# must mention the field at fault.
EXPECTED_WORD = {
    "bad_empty_transaction_id": "transaction_id",
    "bad_empty_account_id": "account_id",
    "bad_timestamp_impossible": "timestamp",
    "bad_timestamp_format": "timestamp",
    "bad_amount_text": "amount",
    "bad_amount_negative": "amount",
    "bad_amount_nan": "amount",
    "bad_amount_infinity": "amount",
    "bad_amount_inf_short": "amount",
    "bad_amount_empty": "amount",
    "bad_status_unsupported": "status",
    "bad_merchant_empty": "merchant",
    "bad_row_too_short": "status",
    "duplicate_changed_amount": "duplicate",
    "duplicate_exact_copy": "duplicate",
    "bad_row_then_valid_same_id": "amount",
}


class DatasetAnswerKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_rows = load_rows(DATA_FOLDER / "transactions.csv")
        cls.accepted, cls.rejected = validate_rows(cls.raw_rows)
        with open(DATA_FOLDER / "planted_cases.csv", newline="", encoding="utf-8") as f:
            cls.key = list(csv.DictReader(f))

    def test_every_row_is_either_accepted_or_rejected(self):
        self.assertEqual(len(self.accepted) + len(self.rejected), len(self.raw_rows))

    def test_rejected_lines_match_the_answer_key(self):
        expected = {int(k["source_line"]) for k in self.key if k["expected_result"] == "rejected"}
        actual = {issue.source_line for issue in self.rejected}
        self.assertEqual(actual, expected)

    def test_planted_rows_that_should_be_accepted_are_accepted(self):
        expected = {int(k["source_line"]) for k in self.key if k["expected_result"] == "accepted"}
        actual = {t.source_line for t in self.accepted}
        self.assertTrue(expected.issubset(actual))

    def test_each_bad_row_has_one_reason_naming_the_right_field(self):
        case_by_line = {int(k["source_line"]): k["case"] for k in self.key}
        for issue in self.rejected:
            case = case_by_line[issue.source_line]
            with self.subTest(line=issue.source_line, case=case):
                self.assertEqual(len(issue.reasons), 1)
                self.assertIn(EXPECTED_WORD[case], issue.reasons[0])

    def test_no_transaction_id_is_accepted_twice(self):
        ids = [t.transaction_id for t in self.accepted]
        self.assertEqual(len(ids), len(set(ids)))

    def test_rule_flags_match_the_answer_key_exactly(self):
        flagged = apply_rules(self.accepted, RuleConfig())
        actual = {item.transaction.source_line: ";".join(item.reasons) for item in flagged}
        expected = {int(k["source_line"]): k["expected_flags"]
                    for k in self.key if k["expected_result"] == "accepted" and k["expected_flags"]}
        # Comparing whole dictionaries also proves that no unplanned row was flagged
        # and that every planted flag (with all its reasons) was found.
        self.assertEqual(actual, expected)

    def test_flagged_report_has_one_row_per_transaction(self):
        flagged = apply_rules(self.accepted, RuleConfig())
        lines = [item.transaction.source_line for item in flagged]
        self.assertEqual(len(lines), len(set(lines)))
        expected_count = sum(1 for k in self.key if k["expected_flags"])
        self.assertEqual(len(lines), expected_count)


if __name__ == "__main__":
    unittest.main()
