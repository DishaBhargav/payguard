"""PayGuard command-line entry point.

Pipeline: load -> validate -> analyse -> apply review rules -> write reports.

Exit codes:
    0  success (flagged rows are normal results, not errors)
    1  a file problem: unreadable input, bad header, unwritable output folder
    2  invalid command-line options (argparse's standard code)
"""
import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from payguard.analytics import daily_totals, summarize, top_accounts
from payguard.loader import InputFileError, load_rows
from payguard.models import RuleConfig
from payguard.reporting import (
    ReportError,
    RunResult,
    format_summary,
    report_paths,
    write_flagged_report,
    write_validation_report,
)
from payguard.rules import apply_rules
from payguard.validation import validate_rows


def decimal_argument(text: str) -> Decimal:
    """argparse type for money options: turn text such as 1000.00 into a Decimal."""
    try:
        return Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line options. Defaults come from RuleConfig, so they live in one place."""
    defaults = RuleConfig()
    parser = argparse.ArgumentParser(
        description=(
            "PayGuard: an educational payment transaction analyzer for synthetic data. "
            "It validates a CSV file, summarises it and flags transactions for human review. "
            "A flag is NOT proof of fraud."
        ),
        epilog="Exit codes: 0 success, 1 file or data error, 2 invalid options.",
    )
    parser.add_argument("--input", type=Path, default=Path("data/transactions.csv"),
                        help="input CSV file (default: %(default)s)")
    parser.add_argument("--output-dir", type=Path, default=Path("output"),
                        help="folder for the report files, created if missing (default: %(default)s)")
    parser.add_argument("--high-value-threshold", type=decimal_argument, default=defaults.high_value_threshold,
                        help="HIGH_VALUE: flag amounts strictly greater than this (default: %(default)s)")
    parser.add_argument("--velocity-window-minutes", type=int, default=defaults.velocity_window_minutes,
                        help="VELOCITY: window length in minutes, inclusive (default: %(default)s)")
    parser.add_argument("--velocity-min-count", type=int, default=defaults.velocity_min_count,
                        help="VELOCITY: minimum transactions in one window, at least 2 (default: %(default)s)")
    parser.add_argument("--daily-spend-threshold", type=decimal_argument, default=defaults.daily_spend_threshold,
                        help="HIGH_DAILY_SPEND: flag approved account-day totals strictly greater "
                             "than this (default: %(default)s)")
    return parser


def is_same_file(first: Path, second: Path) -> bool:
    """True if two paths point at the same place (relative paths and symlinks are resolved)."""
    return first.resolve() == second.resolve()


def main(argv: list[str] | None = None) -> int:
    """Run PayGuard and return the process exit code.

    Taking argv as a parameter lets the tests call main([...]) directly.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = RuleConfig(
            high_value_threshold=args.high_value_threshold,
            velocity_window_minutes=args.velocity_window_minutes,
            velocity_min_count=args.velocity_min_count,
            daily_spend_threshold=args.daily_spend_threshold,
        )
    except ValueError as exc:
        parser.error(str(exc))      # prints the problem and exits with code 2

    flagged_path, errors_path = report_paths(args.output_dir)
    for report_path in (flagged_path, errors_path):
        if is_same_file(args.input, report_path):
            print(f"error: the input file would be overwritten by the report {report_path}; "
                  "choose a different --output-dir", file=sys.stderr)
            return 1

    try:
        raw_rows = load_rows(args.input)
    except InputFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    accepted, rejected = validate_rows(raw_rows)
    result = RunResult(
        input_path=args.input,
        output_dir=args.output_dir,
        config=config,
        rows_read=len(raw_rows),
        summary=summarize(accepted),
        top_accounts=top_accounts(accepted),
        daily_totals=daily_totals(accepted),
        rejected=rejected,
        flagged=apply_rules(accepted, config),
    )

    try:
        write_flagged_report(flagged_path, result.flagged)
        write_validation_report(errors_path, result.rejected)
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
