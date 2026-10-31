"""Turn results into output: two CSV reports and the terminal summary.

write_flagged_report() and write_validation_report() write files.
format_summary(), money() and safe_cell() are pure: text in, text out.

Every output says that flags are for human review and are not proof of fraud.
"""
import csv
import shlex
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from payguard.analytics import CENT, Summary
from payguard.models import TIMESTAMP_FORMAT, FlaggedTransaction, RuleConfig, ValidationIssue
from payguard.rules import RULE_ORDER

FLAGGED_FILENAME = "flagged_transactions.csv"
ERRORS_FILENAME = "validation_errors.csv"

FLAGGED_COLUMNS = [
    "source_line", "transaction_id", "timestamp", "account_id",
    "amount", "merchant", "status", "flag_reasons", "review_note",
]
ERRORS_COLUMNS = ["source_line", "transaction_id", "reasons"]

REVIEW_NOTE = "Review flag only - not proof of fraud"
MAX_DAYS_SHOWN = 14

# A spreadsheet treats text that starts with one of these as a formula.
FORMULA_STARTERS = ("=", "+", "-", "@", "\t", "\r")


class ReportError(Exception):
    """A report file or its folder could not be written."""


@dataclass(frozen=True)
class RunResult:
    """Everything the terminal summary needs, gathered in one place."""

    input_path: Path
    output_dir: Path
    config: RuleConfig
    rows_read: int
    summary: Summary
    top_accounts: list[tuple[str, Decimal]]
    daily_totals: dict[date, Decimal]
    rejected: list[ValidationIssue]
    flagged: list[FlaggedTransaction]


# ---- small pure helpers ------------------------------------------------------

def money(value: Decimal) -> str:
    """Format money as 1,234.56, rounding half-up (the same rule the average uses)."""
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):,.2f}"


def plain(value: Decimal) -> str:
    """Write a Decimal without scientific notation (1000, not 1E+3)."""
    return f"{value:f}"


def safe_cell(text: str) -> str:
    """Stop spreadsheets from running text such as =CMD(...) as a formula.

    Text that starts with a formula character gets a ' in front, which Excel and
    Google Sheets show as plain text. Report cells copy values from the input
    file, and the input is not trusted.
    """
    if text.startswith(FORMULA_STARTERS):
        return "'" + text
    return text


def report_paths(output_dir: Path) -> tuple[Path, Path]:
    """Where the flagged report and the validation report are written."""
    return output_dir / FLAGGED_FILENAME, output_dir / ERRORS_FILENAME


# ---- CSV reports (file I/O) --------------------------------------------------

def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    """Write a CSV file, creating its folder first. Raises ReportError on any file problem."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise ReportError(f"cannot create output folder {path.parent}: {reason}") from exc

    try:
        # lineterminator="\n" keeps the file bytes identical on every operating system.
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise ReportError(f"cannot write {path}: {reason}") from exc


def write_flagged_report(path: Path, flagged: list[FlaggedTransaction]) -> None:
    """One row per flagged transaction; flag_reasons lists every matching rule, joined by ';'."""
    rows = []
    for item in flagged:
        t = item.transaction
        rows.append([
            t.source_line,
            safe_cell(t.transaction_id),
            t.timestamp.strftime(TIMESTAMP_FORMAT),
            safe_cell(t.account_id),
            plain(t.amount),            # exactly the digits that were read, never rounded
            safe_cell(t.merchant),
            t.status,
            ";".join(item.reasons),
            REVIEW_NOTE,
        ])
    write_csv(path, FLAGGED_COLUMNS, rows)


def write_validation_report(path: Path, issues: list[ValidationIssue]) -> None:
    """One row per rejected input row; reasons lists every problem, joined by ' | '."""
    rows = []
    for issue in issues:
        rows.append([
            issue.source_line,
            safe_cell(issue.transaction_id),
            safe_cell(" | ".join(issue.reasons)),
        ])
    write_csv(path, ERRORS_COLUMNS, rows)


# ---- terminal summary --------------------------------------------------------

def reproduce_command(result: RunResult) -> str:
    """The exact command line that repeats this run."""
    config = result.config
    parts = [
        "python", "main.py",
        "--input", result.input_path.as_posix(),
        "--output-dir", result.output_dir.as_posix(),
        "--high-value-threshold", plain(config.high_value_threshold),
        "--velocity-window-minutes", str(config.velocity_window_minutes),
        "--velocity-min-count", str(config.velocity_min_count),
        "--daily-spend-threshold", plain(config.daily_spend_threshold),
    ]
    return " ".join(shlex.quote(part) for part in parts)


def format_summary(result: RunResult) -> str:
    """Build the terminal summary as one string.

    Paths are shown with forward slashes (as_posix) on every operating system, so
    the output looks the same on Windows, macOS and Linux.
    """
    config = result.config
    summary = result.summary
    flagged_path, errors_path = report_paths(result.output_dir)

    if summary.status_counts:
        status_text = ", ".join(f"{name} {count}" for name, count in summary.status_counts.items())
    else:
        status_text = "none"

    rule_counts = {name: 0 for name in RULE_ORDER}
    for item in result.flagged:
        for reason in item.reasons:
            rule_counts[reason] += 1

    lines = [
        "PAYGUARD REPORT",
        "===============",
        "Educational prototype using synthetic data. Flagged rows are transactions",
        "selected for human review by simple rules. They are NOT proof of fraud.",
        "",
        "Configuration",
        f"  input file:           {result.input_path.as_posix()}",
        f"  output folder:        {result.output_dir.as_posix()}",
        f"  HIGH_VALUE:           amount > {plain(config.high_value_threshold)}",
        f"  VELOCITY:             >= {config.velocity_min_count} transactions from one account "
        f"within {config.velocity_window_minutes} minutes (inclusive)",
        f"  HIGH_DAILY_SPEND:     approved total per account per day > {plain(config.daily_spend_threshold)}",
        "  spending counts:      approved transactions only",
        f"  reproduce with:       {reproduce_command(result)}",
        "",
        "Data quality",
        f"  rows read:            {result.rows_read}",
        f"  accepted:             {summary.accepted_count}",
        f"  rejected:             {len(result.rejected)}",
        "",
        "Accepted transactions",
        f"  status counts:        {status_text}",
        f"  total approved value: {money(summary.total_value)}",
        f"  average approved:     {money(summary.average_value)}",
        f"  declined value:       {money(summary.declined_value)} (not counted as spending)",
        "",
        "Top accounts by approved spending",
    ]
    if result.top_accounts:
        for rank, (account_id, total) in enumerate(result.top_accounts, start=1):
            lines.append(f"  {rank}. {account_id}  {money(total)}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Daily approved totals")
    if result.daily_totals:
        days = list(result.daily_totals.items())
        for day, total in days[:MAX_DAYS_SHOWN]:
            lines.append(f"  {day}  {money(total)}")
        if len(days) > MAX_DAYS_SHOWN:
            lines.append(f"  ... and {len(days) - MAX_DAYS_SHOWN} more days (not printed)")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Review flags")
    lines.append(f"  transactions flagged for review: {len(result.flagged)}")
    for name in RULE_ORDER:
        lines.append(f"    {name}: {rule_counts[name]}")
    lines.append("  (one transaction can match several rules, so these counts can add up to more)")

    lines.append("")
    lines.append("Reports written")
    lines.append(f"  {flagged_path.as_posix()}  ({len(result.flagged)} rows)")
    lines.append(f"  {errors_path.as_posix()}  ({len(result.rejected)} rows)")
    return "\n".join(lines)
