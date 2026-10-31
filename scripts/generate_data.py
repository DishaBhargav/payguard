"""Generate the synthetic PayGuard dataset and its answer key.

Run from the project root:
    python scripts/generate_data.py
    python scripts/generate_data.py --seed 7

Everything is fictional. Two files are written:
    data/transactions.csv    the input for PayGuard
    data/planted_cases.csv   the answer key: what PayGuard should do with each planted row

Planted cases assume PayGuard's default settings:
    HIGH_VALUE        amount strictly greater than 1000.00
    VELOCITY          at least 3 transactions within 5 minutes (5:00 apart still counts)
    HIGH_DAILY_SPEND  approved total per account per day strictly greater than 3000.00

This script does not import the payguard package on purpose: the data
generator should not share code (or bugs) with the code it is meant to test.

Reproducibility: Python only promises that random.random() gives the same
numbers for the same seed in every version. randint() and choice() carry no such
promise, so every random choice below is built from random() alone.
"""
import argparse
import csv
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_SEED = 42
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HEADER = ["transaction_id", "timestamp", "account_id", "amount", "merchant", "status"]
ANSWER_KEY_HEADER = ["case", "source_line", "transaction_id", "expected_result", "expected_flags", "note"]
MERCHANTS = [
    "Coffee Shop", "Grocery Store", "Metro Ticket", "Book Store", "Pharmacy", "Fuel Station",
    "Electronics Shop", "Online Market", "Restaurant", "Cinema", "Gym", "Bakery",
]


def whole_number(rng, low, high):
    """A random whole number from low to high, both included, built only on rng.random()."""
    return min(low + int(rng.random() * (high - low + 1)), high)


def pick(rng, options):
    """A random item from a list, built only on rng.random()."""
    return options[int(rng.random() * len(options))]


def new_row(case, flags, note, timestamp, account, amount, merchant, status):
    """Build one valid row. `flags` is the answer key: which rules should flag it."""
    return {
        "case": case,
        "expected_result": "accepted",
        "expected_flags": flags,
        "note": note,
        "timestamp": timestamp,
        "account_id": account,
        "amount": amount,
        "merchant": merchant,
        "status": status,
    }


def make_background(rng):
    """Ordinary activity: at most one small transaction per account per day.

    Amounts stay at or below 400.00 and nobody transacts twice in a day, so
    none of the three rules can fire on this part of the data.
    """
    rows = []
    first_day = datetime(2026, 10, 1)
    for day in range(14):
        for account_number in range(1, 61):
            if rng.random() < 0.5:
                seconds = whole_number(rng, 8 * 3600, 21 * 3600)  # between 08:00 and 21:00
                cents = whole_number(rng, 500, 40000)               # 5.00 to 400.00
                status = "approved" if rng.random() < 0.92 else "declined"
                rows.append(new_row(
                    "background", "", "ordinary transaction",
                    first_day + timedelta(days=day, seconds=seconds),
                    f"AC{account_number:03d}",
                    f"{cents // 100}.{cents % 100:02d}",
                    pick(rng, MERCHANTS),
                    status,
                ))
    return rows


def make_planted():
    """Hand-written rows whose correct outcome we know in advance.

    Each case uses its own account (AC9xx) so the cases cannot interfere.
    """
    rows = []

    def add(case, flags, note, when, account, amount, status="approved", merchant="Test Merchant"):
        timestamp = datetime.strptime(when, TIMESTAMP_FORMAT)
        rows.append(new_row(case, flags, note, timestamp, account, amount, merchant, status))

    def burst(case, flags, note, account, moments, amount="20.00", status="approved"):
        for when in moments:
            add(case, flags, note, when, account, amount, status)

    # --- HIGH_VALUE: threshold 1000.00, strictly greater than ---
    add("hv_below_threshold", "", "999.99 is not above 1000.00", "2026-10-02 10:00:00", "AC901", "999.99")
    add("hv_exact_threshold", "", "exactly 1000.00 is not above 1000.00", "2026-10-02 11:00:00", "AC902", "1000.00")
    add("hv_above_threshold", "HIGH_VALUE", "1000.01 is above 1000.00", "2026-10-02 12:00:00", "AC903", "1000.01")
    add("hv_declined_attempt", "HIGH_VALUE", "declined attempts are checked by this rule",
        "2026-10-02 13:00:00", "AC904", "2500.00", status="declined")

    # --- VELOCITY: at least 3 transactions within 5 minutes, window is inclusive ---
    burst("vel_exactly_5_minutes", "VELOCITY", "3 transactions spanning exactly 5:00 fit the window", "AC910",
          ["2026-10-05 09:00:00", "2026-10-05 09:02:30", "2026-10-05 09:05:00"])
    burst("vel_one_second_outside", "", "3 transactions spanning 5:01 do not fit one window", "AC911",
          ["2026-10-05 09:00:00", "2026-10-05 09:02:30", "2026-10-05 09:05:01"])
    for when, flags in [("10:00:00", "VELOCITY"), ("10:01:00", "VELOCITY"), ("10:02:00", "VELOCITY"), ("10:09:00", "")]:
        add("vel_burst_then_stray", flags, "burst of 3, then a stray transaction 7 minutes later",
            f"2026-10-05 {when}", "AC912", "20.00")
    burst("vel_rolling_chain", "VELOCITY", "overlapping windows: no single window holds all five", "AC913",
          [f"2026-10-05 12:0{minute}:00" for minute in (0, 2, 4, 6, 8)])
    burst("vel_declined_burst", "VELOCITY", "declined attempts count towards velocity", "AC914",
          ["2026-10-05 13:00:00", "2026-10-05 13:00:40", "2026-10-05 13:01:20"], amount="1.00", status="declined")
    burst("vel_same_second", "VELOCITY", "identical timestamps still count", "AC915",
          ["2026-10-05 14:00:00"] * 3)
    burst("vel_across_midnight", "VELOCITY", "the window ignores calendar days", "AC916",
          ["2026-10-06 23:58:00", "2026-10-06 23:59:30", "2026-10-07 00:01:00"])
    burst("vel_only_two", "", "2 transactions are below the minimum count of 3", "AC917",
          ["2026-10-05 15:00:00", "2026-10-05 15:01:00"])

    # --- HIGH_DAILY_SPEND: approved total per account per day, threshold 3000.00 ---
    burst("daily_exactly_threshold", "", "total is exactly 3000.00, not above it", "AC920",
          ["2026-10-08 09:00:00", "2026-10-08 13:00:00", "2026-10-08 17:00:00"], amount="1000.00")
    for when, amount, flags in [("09:00:00", "1000.00", "HIGH_DAILY_SPEND"),
                                ("13:00:00", "1000.00", "HIGH_DAILY_SPEND"),
                                ("17:00:00", "1000.01", "HIGH_VALUE;HIGH_DAILY_SPEND")]:
        add("daily_just_over", flags, "total is 3000.01; the 1000.01 row is also above the high-value threshold",
            f"2026-10-08 {when}", "AC921", amount)
    burst("daily_declined_excluded", "", "approved total is 2700.00; the declined row is not counted", "AC922",
          ["2026-10-08 09:00:00", "2026-10-08 13:00:00", "2026-10-08 17:00:00"], amount="900.00")
    add("daily_declined_excluded", "", "approved total is 2700.00; the declined row is not counted",
        "2026-10-08 20:00:00", "AC922", "900.00", status="declined")
    burst("daily_split_across_days", "", "2000.00 on each day; days are never combined", "AC923",
          ["2026-10-08 09:00:00", "2026-10-08 15:00:00", "2026-10-09 09:00:00", "2026-10-09 15:00:00"],
          amount="1000.00")

    # --- One transaction that matches all three rules ---
    burst("multi_reason", "HIGH_VALUE;VELOCITY;HIGH_DAILY_SPEND", "one transaction, three reasons, one report row",
          "AC924", ["2026-10-10 15:00:00", "2026-10-10 15:01:00", "2026-10-10 15:02:00"], amount="1200.00")

    # --- Valid rows that are easy to get wrong ---
    add("status_uppercase", "", "status APPROVED is accepted and normalised to lower case",
        "2026-10-11 10:00:00", "AC930", "50.00", status="APPROVED")
    add("merchant_with_comma", "", "a comma inside quotes must not split the field",
        "2026-10-11 11:00:00", "AC931", "75.25", merchant="Corner Store, Main St")
    add("zero_amount", "", "zero is allowed; only negative amounts are rejected",
        "2026-10-11 12:00:00", "AC932", "0.00")
    return rows


def bad_row(case, note, values):
    """A deliberately broken row. `values` are the raw CSV fields."""
    return {"case": case, "expected_result": "rejected", "expected_flags": "", "note": note, "values": values}


def make_bad_rows(valid):
    """Return (position, row) pairs; each row is inserted before valid[position]."""
    background = [i for i, row in enumerate(valid) if row["case"] == "background"]
    assert len(background) > 100, "not enough background rows to place the bad rows"
    bad = []

    # One broken field per row. Each uses its own ID (TX9xxx) so that only one thing is wrong.
    broken = [
        ("bad_empty_transaction_id", "transaction_id is empty", 0, ""),
        ("bad_empty_account_id", "account_id is empty", 2, ""),
        ("bad_timestamp_impossible", "timestamp has impossible month, day and hour values", 1, "2026-13-45 25:61:00"),
        ("bad_timestamp_format", "timestamp is not in YYYY-MM-DD HH:MM:SS format", 1, "03/10/2026 10:00"),
        ("bad_amount_text", "amount is not a number", 3, "abc"),
        ("bad_amount_negative", "amount is negative", 3, "-25.00"),
        ("bad_amount_nan", "amount is NaN, which is not a finite number", 3, "NaN"),
        ("bad_amount_infinity", "amount is Infinity, which is not a finite number", 3, "Infinity"),
        ("bad_amount_inf_short", "amount is inf, which is not a finite number", 3, "inf"),
        ("bad_amount_empty", "amount is missing", 3, ""),
        ("bad_status_unsupported", "status refunded is not an allowed status", 5, "refunded"),
        ("bad_merchant_empty", "merchant is missing", 4, ""),
    ]
    position = 10
    for number, (case, note, field, value) in enumerate(broken, start=1):
        values = [f"TX{9000 + number}", "2026-10-03 10:00:00", "AC005", "25.00", "Grocery Store", "approved"]
        values[field] = value
        bad.append((position, bad_row(case, note, values)))
        position += 12

    short = ["TX9013", "2026-10-03 10:00:00", "AC005", "25.00", "Grocery Store"]
    bad.append((position, bad_row("bad_row_too_short", "row has 5 of 6 fields; status is missing", short)))

    # Duplicate IDs: the first accepted row keeps the ID, later copies are rejected.
    original = valid[background[20]]
    copy = list(original["values"])
    copy[3] = "5000.00"
    bad.append((background[20] + 25, bad_row(
        "duplicate_changed_amount",
        "ID already used by an accepted row; 5000.00 must not be counted or flagged", copy)))
    original["case"] = "duplicate_first_occurrence"
    original["note"] = "first use of this ID is accepted; later rows reusing it are rejected"

    original = valid[background[50]]
    bad.append((background[50] + 15, bad_row(
        "duplicate_exact_copy", "exact copy of an accepted row; rejected so it is not counted twice",
        list(original["values"]))))
    original["case"] = "duplicate_first_occurrence"
    original["note"] = "first use of this ID is accepted; later rows reusing it are rejected"

    # A rejected row does not "claim" its ID: the valid row that follows it is accepted.
    later = valid[background[90]]
    copy = list(later["values"])
    copy[3] = "abc"
    bad.append((background[90], bad_row(
        "bad_row_then_valid_same_id", "amount is not a number; rejecting it leaves the ID unclaimed", copy)))
    later["case"] = "valid_row_after_rejected_same_id"
    later["note"] = "accepted: the earlier row with this ID was rejected, so it never claimed the ID"
    return bad


def assemble(valid, bad):
    """Merge the bad rows into the valid rows at their chosen positions."""
    before = defaultdict(list)
    for position, row in bad:
        before[position].append(row)
    ordered = []
    for index, row in enumerate(valid):
        ordered.extend(before[index])
        ordered.append(row)
    ordered.extend(before[len(valid)])
    return ordered


def by_time(row):
    """Sort key: sort rows by timestamp (the sort is stable, so ties keep their order)."""
    return row["timestamp"]


def write_files(ordered, output_path, answer_key_path):
    """Write the dataset and the answer key. lineterminator keeps the bytes identical on every OS."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    answer_key_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(HEADER)
        for row in ordered:
            writer.writerow(row["values"])

    with open(answer_key_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(ANSWER_KEY_HEADER)
        for index, row in enumerate(ordered):
            if row["case"] != "background":
                line_number = index + 2                            # line 1 is the header
                writer.writerow([row["case"], line_number, row["values"][0],
                                 row["expected_result"], row["expected_flags"], row["note"]])


def main():
    parser = argparse.ArgumentParser(description="Generate the synthetic PayGuard dataset.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed (default: 42)")
    parser.add_argument("--output", type=Path, default=Path("data/transactions.csv"))
    parser.add_argument("--answer-key", type=Path, default=Path("data/planted_cases.csv"))
    args = parser.parse_args()

    rng = random.Random(args.seed)
    valid = sorted(make_background(rng) + make_planted(), key=by_time)
    for number, row in enumerate(valid, start=1):
        row["values"] = [f"TX{number:04d}", row["timestamp"].strftime(TIMESTAMP_FORMAT),
                         row["account_id"], row["amount"], row["merchant"], row["status"]]

    ordered = assemble(valid, make_bad_rows(valid))
    write_files(ordered, args.output, args.answer_key)

    planted = sum(1 for row in ordered if row["case"] != "background")
    rejected = sum(1 for row in ordered if row["expected_result"] == "rejected")
    print(f"Seed {args.seed}: wrote {len(ordered)} data rows to {args.output}")
    print(f"  valid rows: {len(ordered) - rejected}, deliberately bad rows: {rejected}")
    print(f"  answer key: {planted} planted rows listed in {args.answer_key}")


if __name__ == "__main__":
    main()
