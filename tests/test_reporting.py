"""Tests for payguard.reporting: CSV report contents, file errors, and the terminal summary."""
import csv
import dataclasses
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path, PureWindowsPath

from payguard.analytics import daily_totals, summarize, top_accounts
from payguard.models import FlaggedTransaction, RuleConfig, ValidationIssue
from payguard.reporting import (
    ERRORS_COLUMNS,
    FLAGGED_COLUMNS,
    MAX_DAYS_SHOWN,
    REVIEW_NOTE,
    ReportError,
    RunResult,
    format_summary,
    money,
    plain,
    report_paths,
    reproduce_command,
    safe_cell,
    write_flagged_report,
    write_validation_report,
)
from payguard.rules import HIGH_DAILY_SPEND, HIGH_VALUE, VELOCITY, apply_rules
from tests.helpers import make_tx


def read_csv(path):
    """Read a CSV back as a list of dicts, the way a spreadsheet user would see it."""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class HelperTests(unittest.TestCase):
    def test_money_has_two_places_commas_and_rounds_half_up(self):
        self.assertEqual(money(Decimal("1234.5")), "1,234.50")
        self.assertEqual(money(Decimal("0")), "0.00")
        self.assertEqual(money(Decimal("1000000")), "1,000,000.00")
        self.assertEqual(money(Decimal("0.025")), "0.03")     # half-up, not half-even
        self.assertEqual(money(Decimal("0.024")), "0.02")

    def test_plain_never_uses_scientific_notation(self):
        self.assertEqual(plain(Decimal("1E+3")), "1000")
        self.assertEqual(plain(Decimal("1000.00")), "1000.00")

    def test_safe_cell_neutralises_formula_starters(self):
        for text in ("=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx", '=HYPERLINK("http://x")'):
            with self.subTest(text=text):
                self.assertEqual(safe_cell(text), "'" + text)

    def test_safe_cell_leaves_ordinary_text_alone(self):
        for text in ("Coffee Shop", "", "A=B", "AC001", "Corner Store, Main St"):
            with self.subTest(text=text):
                self.assertEqual(safe_cell(text), text)

    def test_report_paths(self):
        flagged_path, errors_path = report_paths(Path("out"))
        self.assertEqual(flagged_path, Path("out") / "flagged_transactions.csv")
        self.assertEqual(errors_path, Path("out") / "validation_errors.csv")


class TempFolderTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)


class FlaggedReportTests(TempFolderTestCase):
    def test_columns_and_one_row_per_flagged_transaction(self):
        flagged = [
            FlaggedTransaction(make_tx("T1", "1000.01", when="2026-10-02 12:00:00", account_id="AC9", line=40),
                               (HIGH_VALUE,)),
            FlaggedTransaction(make_tx("T2", "20.00", "declined", "AC8", "2026-10-05 09:00:00", line=135),
                               (VELOCITY,)),
        ]
        path = self.root / "flagged.csv"
        write_flagged_report(path, flagged)
        rows = read_csv(path)
        self.assertEqual(list(rows[0].keys()), FLAGGED_COLUMNS)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {
            "source_line": "40", "transaction_id": "T1", "timestamp": "2026-10-02 12:00:00",
            "account_id": "AC9", "amount": "1000.01", "merchant": "Test Merchant",
            "status": "approved", "flag_reasons": "HIGH_VALUE", "review_note": REVIEW_NOTE,
        })
        self.assertEqual(rows[1]["status"], "declined")
        self.assertEqual(rows[1]["flag_reasons"], "VELOCITY")

    def test_every_matching_reason_is_kept_in_one_row(self):
        item = FlaggedTransaction(make_tx("T1"), (HIGH_VALUE, VELOCITY, HIGH_DAILY_SPEND))
        write_flagged_report(self.root / "f.csv", [item])
        rows = read_csv(self.root / "f.csv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["flag_reasons"], "HIGH_VALUE;VELOCITY;HIGH_DAILY_SPEND")

    def test_every_row_carries_the_not_proof_of_fraud_note(self):
        items = [FlaggedTransaction(make_tx(f"T{n}"), (HIGH_VALUE,)) for n in range(3)]
        write_flagged_report(self.root / "f.csv", items)
        notes = {row["review_note"] for row in read_csv(self.root / "f.csv")}
        self.assertEqual(notes, {REVIEW_NOTE})
        self.assertIn("not proof of fraud", REVIEW_NOTE)

    def test_amounts_keep_their_digits_without_scientific_notation(self):
        for given, expected in (("5", "5"), ("1000.00", "1000.00"), ("0.10", "0.10"), ("1E+3", "1000")):
            with self.subTest(amount=given):
                write_flagged_report(self.root / "f.csv", [FlaggedTransaction(make_tx("T1", given), (HIGH_VALUE,))])
                self.assertEqual(read_csv(self.root / "f.csv")[0]["amount"], expected)

    def test_text_with_commas_quotes_and_unicode_survives(self):
        tricky = dataclasses.replace(make_tx("T1"), merchant='Café "Rupee" ₹, Main St')
        write_flagged_report(self.root / "f.csv", [FlaggedTransaction(tricky, (HIGH_VALUE,))])
        self.assertEqual(read_csv(self.root / "f.csv")[0]["merchant"], 'Café "Rupee" ₹, Main St')

    def test_formula_like_input_is_neutralised(self):
        evil = dataclasses.replace(make_tx("=cmd|' /C calc'!A0"), merchant='=HYPERLINK("http://example.com")')
        write_flagged_report(self.root / "f.csv", [FlaggedTransaction(evil, (HIGH_VALUE,))])
        row = read_csv(self.root / "f.csv")[0]
        self.assertTrue(row["merchant"].startswith("'="))
        self.assertTrue(row["transaction_id"].startswith("'="))

    def test_empty_list_writes_only_the_header(self):
        write_flagged_report(self.root / "f.csv", [])
        text = (self.root / "f.csv").read_text(encoding="utf-8")
        self.assertEqual(text, ",".join(FLAGGED_COLUMNS) + "\n")

    def test_missing_folders_are_created(self):
        path = self.root / "a" / "b" / "c" / "f.csv"
        write_flagged_report(path, [])
        self.assertTrue(path.exists())

    def test_existing_file_is_replaced_not_appended_to(self):
        path = self.root / "f.csv"
        write_flagged_report(path, [FlaggedTransaction(make_tx("T1"), (HIGH_VALUE,))] * 2)
        write_flagged_report(path, [FlaggedTransaction(make_tx("T2"), (HIGH_VALUE,))])
        rows = read_csv(path)
        self.assertEqual([row["transaction_id"] for row in rows], ["T2"])

    def test_same_input_gives_identical_bytes_and_unix_line_endings(self):
        items = [FlaggedTransaction(make_tx("T1"), (HIGH_VALUE,))]
        write_flagged_report(self.root / "one.csv", items)
        write_flagged_report(self.root / "two.csv", items)
        first = (self.root / "one.csv").read_bytes()
        self.assertEqual(first, (self.root / "two.csv").read_bytes())
        self.assertNotIn(b"\r", first)

    def test_folder_that_is_really_a_file_raises_report_error(self):
        blocker = self.root / "blocker"
        blocker.write_text("I am a file")
        with self.assertRaises(ReportError) as ctx:
            write_flagged_report(blocker / "f.csv", [])
        self.assertIn("cannot create output folder", str(ctx.exception))

    def test_target_that_is_really_a_folder_raises_report_error(self):
        target = self.root / "f.csv"
        target.mkdir()
        with self.assertRaises(ReportError) as ctx:
            write_flagged_report(target, [])
        self.assertIn("cannot write", str(ctx.exception))


class ValidationReportTests(TempFolderTestCase):
    def test_source_line_id_and_every_reason_are_written(self):
        issues = [
            ValidationIssue(12, "", ("missing required field: transaction_id",)),
            ValidationIssue(50, "TX1", ("invalid timestamp 'x'; expected YYYY-MM-DD HH:MM:SS", "amount is not a number: 'abc'")),
        ]
        write_validation_report(self.root / "e.csv", issues)
        rows = read_csv(self.root / "e.csv")
        self.assertEqual(list(rows[0].keys()), ERRORS_COLUMNS)
        self.assertEqual(rows[0], {"source_line": "12", "transaction_id": "",
                                   "reasons": "missing required field: transaction_id"})
        self.assertEqual(rows[1]["source_line"], "50")
        self.assertEqual(rows[1]["reasons"],
                         "invalid timestamp 'x'; expected YYYY-MM-DD HH:MM:SS | amount is not a number: 'abc'")

    def test_empty_list_writes_only_the_header(self):
        write_validation_report(self.root / "e.csv", [])
        self.assertEqual((self.root / "e.csv").read_text(encoding="utf-8"), ",".join(ERRORS_COLUMNS) + "\n")

    def test_formula_like_id_is_neutralised(self):
        write_validation_report(self.root / "e.csv", [ValidationIssue(2, "=1+1", ("x",))])
        self.assertEqual(read_csv(self.root / "e.csv")[0]["transaction_id"], "'=1+1")

    def test_unwritable_target_raises_report_error(self):
        target = self.root / "e.csv"
        target.mkdir()
        with self.assertRaises(ReportError):
            write_validation_report(target, [])


def build_result(transactions, rejected=(), config=None, output_dir="out", input_path="in.csv"):
    """Assemble a RunResult from real analytics and rule code."""
    config = config or RuleConfig()
    return RunResult(
        input_path=Path(input_path),
        output_dir=Path(output_dir),
        config=config,
        rows_read=len(transactions) + len(rejected),
        summary=summarize(transactions),
        top_accounts=top_accounts(transactions),
        daily_totals=daily_totals(transactions),
        rejected=list(rejected),
        flagged=apply_rules(transactions, config),
    )


class SummaryTests(unittest.TestCase):
    def setUp(self):
        transactions = [
            make_tx("T1", "1500.00", "approved", "AC1", "2026-10-01 09:00:00"),
            make_tx("T2", "100.00", "approved", "AC2", "2026-10-02 09:00:00"),
            make_tx("T3", "900.00", "declined", "AC2", "2026-10-02 10:00:00"),
        ]
        rejected = [ValidationIssue(5, "T9", ("amount is not a number: 'x'",))]
        self.text = format_summary(build_result(transactions, rejected))

    def test_says_clearly_that_flags_are_not_proof_of_fraud(self):
        self.assertIn("NOT proof of fraud", self.text)
        self.assertNotIn("fraudulent", self.text.lower())

    def test_shows_the_configuration_in_use(self):
        self.assertIn("amount > 1000.00", self.text)
        self.assertIn(">= 3 transactions from one account within 5 minutes (inclusive)", self.text)
        self.assertIn("approved total per account per day > 3000.00", self.text)
        self.assertIn("approved transactions only", self.text)

    def test_shows_data_quality_counts(self):
        self.assertRegex(self.text, r"rows read:\s+4")
        self.assertRegex(self.text, r"accepted:\s+3")
        self.assertRegex(self.text, r"rejected:\s+1")

    def test_money_figures_count_approved_only(self):
        self.assertRegex(self.text, r"total approved value:\s+1,600\.00")
        self.assertRegex(self.text, r"average approved:\s+800\.00")
        self.assertRegex(self.text, r"declined value:\s+900\.00 \(not counted as spending\)")
        self.assertIn("approved 2, declined 1", self.text)

    def test_lists_top_accounts_and_daily_totals(self):
        self.assertIn("1. AC1  1,500.00", self.text)
        self.assertIn("2026-10-02  100.00", self.text)

    def test_shows_flag_counts_for_every_rule(self):
        self.assertIn("transactions flagged for review: 1", self.text)
        self.assertIn("HIGH_VALUE: 1", self.text)
        self.assertIn("VELOCITY: 0", self.text)
        self.assertIn("HIGH_DAILY_SPEND: 0", self.text)

    def test_names_the_report_files(self):
        self.assertIn("flagged_transactions.csv  (1 rows)", self.text)
        self.assertIn("validation_errors.csv  (1 rows)", self.text)

    def test_empty_result_prints_without_crashing(self):
        text = format_summary(build_result([]))
        self.assertRegex(text, r"accepted:\s+0")
        self.assertIn("status counts:        none", text)
        self.assertIn("(none)", text)
        self.assertIn("transactions flagged for review: 0", text)

    def test_long_daily_lists_are_cut_with_a_note(self):
        transactions = [make_tx(f"T{n}", "10.00", when=f"2026-10-{n:02d} 09:00:00") for n in range(1, MAX_DAYS_SHOWN + 3)]
        text = format_summary(build_result(transactions))
        self.assertIn("... and 2 more days (not printed)", text)

    def test_paths_are_shown_with_forward_slashes_even_for_windows_paths(self):
        # PureWindowsPath behaves like a Windows path on any system, so this test
        # checks the Windows case even when it runs on Linux or macOS.
        result = build_result([], input_path="x.csv", output_dir="out")
        windows = dataclasses.replace(result, input_path=PureWindowsPath("data\\transactions.csv"),
                                      output_dir=PureWindowsPath("reports\\run1"))
        text = format_summary(windows)
        self.assertIn("data/transactions.csv", text)
        self.assertIn("reports/run1/flagged_transactions.csv", text)
        self.assertIn("reports/run1/validation_errors.csv", text)
        self.assertNotIn("\\", text)

    def test_reproduce_command_repeats_the_run_and_quotes_awkward_paths(self):
        config = RuleConfig(high_value_threshold=Decimal("1E+3"), velocity_window_minutes=7)
        result = build_result([], config=config, input_path="my data/in.csv", output_dir="out")
        command = reproduce_command(result)
        self.assertIn("--input 'my data/in.csv'", command)
        self.assertIn("--high-value-threshold 1000 ", command)
        self.assertIn("--velocity-window-minutes 7", command)
        self.assertTrue(command.startswith("python main.py"))


if __name__ == "__main__":
    unittest.main()
