"""End-to-end tests: run main() the way the command line does, using temporary folders.

Nothing here depends on the current working directory, the network or the clock.
"""
import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path

from main import build_parser, main
from payguard.reporting import ERRORS_FILENAME, FLAGGED_FILENAME

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INPUT = PROJECT_ROOT / "data" / "transactions.csv"
ANSWER_KEY = PROJECT_ROOT / "data" / "planted_cases.csv"
HEADER = "transaction_id,timestamp,account_id,amount,merchant,status\n"


def run(argv):
    """Run main(argv) and return (exit_code, stdout_text, stderr_text)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(part) for part in argv])
    return code, out.getvalue(), err.getvalue()


def run_expecting_exit(argv):
    """Run main(argv) when argparse is expected to stop the program. Returns (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            main([str(part) for part in argv])
        except SystemExit as exc:
            return exc.code, out.getvalue(), err.getvalue()
    raise AssertionError("main() returned instead of exiting")


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.out_dir = self.root / "out"

    def write_input(self, body, name="input.csv", header=HEADER, newline="\n"):
        path = self.root / name
        path.write_bytes((header + body).replace("\n", newline).encode("utf-8"))
        return path

    def flagged_rows(self):
        return read_csv(self.out_dir / FLAGGED_FILENAME)


class SampleDatasetTests(CliTestCase):
    def test_full_run_succeeds_and_reports_the_expected_counts(self):
        # The expected counts come from the hand-written answer key, not from PayGuard.
        key = read_csv(ANSWER_KEY)
        rows_read = len(read_csv(SAMPLE_INPUT))
        rejected = sum(1 for k in key if k["expected_result"] == "rejected")
        flagged = sum(1 for k in key if k["expected_flags"])

        code, out, err = run(["--input", SAMPLE_INPUT, "--output-dir", self.out_dir])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertRegex(out, rf"rows read:\s+{rows_read}\b")
        self.assertRegex(out, rf"accepted:\s+{rows_read - rejected}\b")
        self.assertRegex(out, rf"rejected:\s+{rejected}\b")
        self.assertIn(f"transactions flagged for review: {flagged}", out)
        self.assertEqual(len(self.flagged_rows()), flagged)
        self.assertEqual(len(read_csv(self.out_dir / ERRORS_FILENAME)), rejected)

    def test_report_files_match_the_answer_key_exactly(self):
        run(["--input", SAMPLE_INPUT, "--output-dir", self.out_dir])
        key = read_csv(ANSWER_KEY)

        expected_flags = {int(k["source_line"]): k["expected_flags"]
                          for k in key if k["expected_result"] == "accepted" and k["expected_flags"]}
        actual_flags = {int(row["source_line"]): row["flag_reasons"] for row in self.flagged_rows()}
        self.assertEqual(actual_flags, expected_flags)

        expected_rejected = {int(k["source_line"]) for k in key if k["expected_result"] == "rejected"}
        actual_rejected = {int(row["source_line"]) for row in read_csv(self.out_dir / ERRORS_FILENAME)}
        self.assertEqual(actual_rejected, expected_rejected)

    def test_each_transaction_appears_once_in_the_flagged_report(self):
        run(["--input", SAMPLE_INPUT, "--output-dir", self.out_dir])
        ids = [row["transaction_id"] for row in self.flagged_rows()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_input_file_is_never_modified(self):
        before = SAMPLE_INPUT.read_bytes()
        run(["--input", SAMPLE_INPUT, "--output-dir", self.out_dir])
        self.assertEqual(SAMPLE_INPUT.read_bytes(), before)

    def test_summary_says_flags_are_not_proof_of_fraud(self):
        _, out, _ = run(["--input", SAMPLE_INPUT, "--output-dir", self.out_dir])
        self.assertIn("NOT proof of fraud", out)
        for row in self.flagged_rows():
            self.assertIn("not proof of fraud", row["review_note"])

    def test_running_twice_gives_identical_report_bytes(self):
        run(["--input", SAMPLE_INPUT, "--output-dir", self.out_dir])
        first = [(self.out_dir / name).read_bytes() for name in (FLAGGED_FILENAME, ERRORS_FILENAME)]
        run(["--input", SAMPLE_INPUT, "--output-dir", self.out_dir])
        second = [(self.out_dir / name).read_bytes() for name in (FLAGGED_FILENAME, ERRORS_FILENAME)]
        self.assertEqual(first, second)


class ConfigurationTests(CliTestCase):
    def test_defaults_match_the_agreed_specification(self):
        args = build_parser().parse_args([])
        self.assertEqual(str(args.high_value_threshold), "1000.00")
        self.assertEqual(args.velocity_window_minutes, 5)
        self.assertEqual(args.velocity_min_count, 3)
        self.assertEqual(str(args.daily_spend_threshold), "3000.00")
        self.assertEqual(args.output_dir, Path("output"))
        self.assertEqual(args.input, Path("data/transactions.csv"))

    def test_high_value_boundary_through_the_command_line(self):
        path = self.write_input(
            "T1,2026-10-01 09:00:00,A1,999.99,Shop,approved\n"
            "T2,2026-10-01 10:00:00,A2,1000.00,Shop,approved\n"
            "T3,2026-10-01 11:00:00,A3,1000.01,Shop,approved\n")
        run(["--input", path, "--output-dir", self.out_dir])
        self.assertEqual([row["transaction_id"] for row in self.flagged_rows()], ["T3"])

    def test_custom_high_value_threshold(self):
        path = self.write_input("T1,2026-10-01 09:00:00,A1,60.00,Shop,approved\n")
        run(["--input", path, "--output-dir", self.out_dir])
        self.assertEqual(self.flagged_rows(), [])
        run(["--input", path, "--output-dir", self.out_dir, "--high-value-threshold", "50"])
        self.assertEqual([row["flag_reasons"] for row in self.flagged_rows()], ["HIGH_VALUE"])

    def test_custom_velocity_window_and_count(self):
        path = self.write_input(
            "T1,2026-10-01 09:00:00,A1,10.00,Shop,approved\n"
            "T2,2026-10-01 09:09:00,A1,10.00,Shop,approved\n")
        run(["--input", path, "--output-dir", self.out_dir])
        self.assertEqual(self.flagged_rows(), [])
        run(["--input", path, "--output-dir", self.out_dir,
             "--velocity-window-minutes", "10", "--velocity-min-count", "2"])
        self.assertEqual(len(self.flagged_rows()), 2)

    def test_custom_daily_spend_threshold_is_strict(self):
        path = self.write_input(
            "T1,2026-10-01 09:00:00,A1,150.00,Shop,approved\n"
            "T2,2026-10-01 15:00:00,A1,150.00,Shop,approved\n")
        run(["--input", path, "--output-dir", self.out_dir, "--daily-spend-threshold", "300.00"])
        self.assertEqual(self.flagged_rows(), [])                       # exactly at the threshold
        run(["--input", path, "--output-dir", self.out_dir, "--daily-spend-threshold", "299.99"])
        self.assertEqual(len(self.flagged_rows()), 2)

    def test_declined_transactions_are_not_counted_as_spending(self):
        path = self.write_input(
            "T1,2026-10-01 09:00:00,A1,100.00,Shop,approved\n"
            "T2,2026-10-01 10:00:00,A1,900.00,Shop,declined\n")
        _, out, _ = run(["--input", path, "--output-dir", self.out_dir])
        self.assertRegex(out, r"total approved value:\s+100\.00")
        self.assertRegex(out, r"declined value:\s+900\.00")

    def test_the_summary_shows_the_settings_that_were_used(self):
        path = self.write_input("T1,2026-10-01 09:00:00,A1,10.00,Shop,approved\n")
        _, out, _ = run(["--input", path, "--output-dir", self.out_dir, "--velocity-min-count", "4"])
        self.assertIn(">= 4 transactions from one account", out)
        self.assertIn("--velocity-min-count 4", out)

    def test_invalid_options_exit_with_code_2_and_write_nothing(self):
        bad_options = [
            ["--velocity-min-count", "1"],
            ["--velocity-min-count", "x"],
            ["--velocity-window-minutes", "0"],
            ["--high-value-threshold", "abc"],
            ["--high-value-threshold", "-1"],
            ["--high-value-threshold", "NaN"],
            ["--daily-spend-threshold", "-0.01"],
            ["--daily-spend-threshold", "Infinity"],
            ["--no-such-option"],
        ]
        for options in bad_options:
            with self.subTest(options=options):
                code, _, err = run_expecting_exit(["--input", SAMPLE_INPUT, "--output-dir", self.out_dir] + options)
                self.assertEqual(code, 2)
                self.assertIn("error", err)
        self.assertFalse(self.out_dir.exists())

    def test_help_describes_every_option_and_exits_cleanly(self):
        code, out, _ = run_expecting_exit(["--help"])
        self.assertEqual(code, 0)
        for option in ("--input", "--output-dir", "--high-value-threshold", "--velocity-window-minutes",
                       "--velocity-min-count", "--daily-spend-threshold"):
            self.assertIn(option, out)
        self.assertIn("NOT proof of fraud", out)


class FileProblemTests(CliTestCase):
    def test_missing_input_file_exits_1_with_a_clear_message_and_writes_nothing(self):
        code, out, err = run(["--input", self.root / "missing.csv", "--output-dir", self.out_dir])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("cannot read", err)
        self.assertFalse(self.out_dir.exists())

    def test_folder_given_as_input_exits_1(self):
        code, _, err = run(["--input", self.root, "--output-dir", self.out_dir])
        self.assertEqual(code, 1)
        self.assertIn("error:", err)

    def test_missing_columns_exit_1_and_name_the_columns(self):
        path = self.write_input("T1,2026-10-01 09:00:00,A1\n", header="transaction_id,timestamp,account_id\n")
        code, _, err = run(["--input", path, "--output-dir", self.out_dir])
        self.assertEqual(code, 1)
        for name in ("amount", "merchant", "status"):
            self.assertIn(name, err)

    def test_empty_file_exits_1(self):
        path = self.root / "empty.csv"
        path.write_bytes(b"")
        code, _, err = run(["--input", path, "--output-dir", self.out_dir])
        self.assertEqual(code, 1)
        self.assertIn("empty", err)

    def test_output_folder_that_is_really_a_file_exits_1(self):
        blocker = self.root / "blocker"
        blocker.write_text("not a folder")
        path = self.write_input("T1,2026-10-01 09:00:00,A1,10.00,Shop,approved\n")
        code, _, err = run(["--input", path, "--output-dir", blocker])
        self.assertEqual(code, 1)
        self.assertIn("cannot create output folder", err)

    def test_missing_output_folders_are_created(self):
        path = self.write_input("T1,2026-10-01 09:00:00,A1,10.00,Shop,approved\n")
        nested = self.root / "a" / "b" / "c"
        code, _, _ = run(["--input", path, "--output-dir", nested])
        self.assertEqual(code, 0)
        self.assertTrue((nested / FLAGGED_FILENAME).exists())
        self.assertTrue((nested / ERRORS_FILENAME).exists())

    def test_input_that_would_be_overwritten_by_a_report_is_refused(self):
        for report_name in (FLAGGED_FILENAME, ERRORS_FILENAME):
            with self.subTest(report=report_name):
                path = self.write_input("T1,2026-10-01 09:00:00,A1,2000.00,Shop,approved\n", name=report_name)
                before = path.read_bytes()
                code, _, err = run(["--input", path, "--output-dir", self.root])
                self.assertEqual(code, 1)
                self.assertIn("would be overwritten", err)
                self.assertEqual(path.read_bytes(), before)

    def test_overwrite_protection_sees_through_dot_dot_paths(self):
        (self.root / "sub").mkdir()
        path = self.write_input("T1,2026-10-01 09:00:00,A1,2000.00,Shop,approved\n", name=FLAGGED_FILENAME)
        sneaky = self.root / "sub" / ".." / FLAGGED_FILENAME
        code, _, err = run(["--input", sneaky, "--output-dir", self.root])
        self.assertEqual(code, 1)
        self.assertIn("would be overwritten", err)
        self.assertTrue(path.exists())


class UnusualInputTests(CliTestCase):
    def test_header_only_file_succeeds_with_empty_reports(self):
        path = self.write_input("")
        code, out, _ = run(["--input", path, "--output-dir", self.out_dir])
        self.assertEqual(code, 0)
        self.assertRegex(out, r"rows read:\s+0")
        self.assertEqual(self.flagged_rows(), [])
        self.assertEqual(read_csv(self.out_dir / ERRORS_FILENAME), [])

    def test_file_with_no_valid_rows_still_reports_every_rejection(self):
        path = self.write_input(",2026-10-01 09:00:00,A1,5,Shop,approved\nT2,bad,A1,5,Shop,approved\n")
        code, out, _ = run(["--input", path, "--output-dir", self.out_dir])
        self.assertEqual(code, 0)
        self.assertRegex(out, r"accepted:\s+0")
        rows = read_csv(self.out_dir / ERRORS_FILENAME)
        self.assertEqual([row["source_line"] for row in rows], ["2", "3"])

    def test_windows_line_endings_give_the_same_results(self):
        body = ("T1,2026-10-01 09:00:00,A1,1000.01,Shop,approved\n"
                "T2,2026-10-01 10:00:00,A2,5.00,Shop,approved\n")
        unix = self.write_input(body, name="unix.csv")
        windows = self.write_input(body, name="windows.csv", header=HEADER, newline="\r\n")
        run(["--input", unix, "--output-dir", self.root / "out_unix"])
        run(["--input", windows, "--output-dir", self.root / "out_windows"])
        self.assertEqual(read_csv(self.root / "out_unix" / FLAGGED_FILENAME),
                         read_csv(self.root / "out_windows" / FLAGGED_FILENAME))

    def test_formula_like_input_is_neutralised_in_the_report(self):
        path = self.write_input('T1,2026-10-01 09:00:00,A1,5000.00,"=HYPERLINK(""http://example.com"")",approved\n')
        run(["--input", path, "--output-dir", self.out_dir])
        self.assertTrue(self.flagged_rows()[0]["merchant"].startswith("'="))

    def test_non_ascii_text_survives_the_round_trip(self):
        path = self.write_input("T1,2026-10-01 09:00:00,A1,5000.00,Café Ünïcode ₹,approved\n")
        run(["--input", path, "--output-dir", self.out_dir])
        self.assertEqual(self.flagged_rows()[0]["merchant"], "Café Ünïcode ₹")

    def test_a_second_run_with_different_input_replaces_the_old_reports(self):
        big = self.write_input("T1,2026-10-01 09:00:00,A1,5000.00,Shop,approved\n", name="big.csv")
        small = self.write_input("T2,2026-10-01 09:00:00,A1,5.00,Shop,approved\n", name="small.csv")
        run(["--input", big, "--output-dir", self.out_dir])
        self.assertEqual(len(self.flagged_rows()), 1)
        run(["--input", small, "--output-dir", self.out_dir])
        self.assertEqual(self.flagged_rows(), [])


if __name__ == "__main__":
    unittest.main()
