# PayGuard: Payment Transaction Analyzer

PayGuard is a small command-line program written in Python (standard library only). It reads payment transaction records from a CSV file, checks the quality of every row, summarises the data, and flags transactions that match three simple, configurable rules so that a person can look at them.

> **What PayGuard is not.** It is **not** a fraud detection system, and it never decides that fraud has happened. A flagged transaction only matches a simple rule (a large amount, a burst of payments, a high daily total), and most transactions like that are perfectly normal. PayGuard works on **synthetic data only**, processes one file at a time offline, and is **not** a production payment-processing system. It uses **no machine learning**, no real-time processing and no real customer data.

## Contents

1. [Features (implemented and tested)](#features-implemented-and-tested)
2. [What is not included](#what-is-not-included)
3. [Architecture and data flow](#architecture-and-data-flow)
4. [Requirements and setup](#requirements-and-setup)
5. [Example command](#example-command)
6. [Input CSV schema and sample rows](#input-csv-schema-and-sample-rows)
7. [Configuration options](#configuration-options)
8. [Output files](#output-files)
9. [Example output](#example-output)
10. [Rule definitions and assumptions](#rule-definitions-and-assumptions)
11. [Running the tests](#running-the-tests)
12. [Regenerating the sample data](#regenerating-the-sample-data)
13. [Known limitations](#known-limitations)
14. [Future improvements (not implemented)](#future-improvements-not-implemented)
15. [Project layout](#project-layout)

## Features (implemented and tested)

Every feature in this table exists in the code and has automated tests in `tests/`. Nothing outside this table is implemented.

| Feature | Module | Main tests |
|---|---|---|
| Read a CSV file, check the header, report problems with the file (missing, unreadable, empty, wrong columns, repeated column names, not UTF-8, NUL characters), and remember the real line number of every row | `payguard/loader.py` | `test_loader.py`, `test_cli.py` |
| Validate each row: missing fields, empty IDs, invalid timestamps, non-numeric / negative / non-finite / oversized amounts, unsupported status, surplus fields, duplicate transaction IDs. Every problem is reported; nothing is silently dropped | `payguard/validation.py` | `test_validation.py`, `test_dataset_answer_key.py` |
| Statistics: accepted count, total and average value, counts by status, daily totals, top-spending accounts (approved transactions only count as spending) | `payguard/analytics.py` | `test_analytics.py` |
| Three review rules, `HIGH_VALUE`, `VELOCITY` and `HIGH_DAILY_SPEND`, merged so each transaction appears once with all its reasons | `payguard/rules.py` | `test_rules.py`, `test_dataset_answer_key.py` |
| Reports: terminal summary, `flagged_transactions.csv`, `validation_errors.csv` (output folder is created if missing; spreadsheet formula characters are neutralised) | `payguard/reporting.py` | `test_reporting.py`, `test_cli.py` |
| Command-line options, exit codes, and protection against overwriting the input file | `main.py` | `test_cli.py` |
| Reproducible synthetic dataset with a hand-written answer key | `scripts/generate_data.py`, `data/` | `test_generator.py`, `test_dataset_answer_key.py` |

"Tested" means the repository contains automated tests for it and they pass when you run `python -m unittest`. See [Known limitations](#known-limitations) for what the tests do not cover.

## What is not included

PayGuard does **not** contain, and does not claim to contain: fraud detection or fraud scoring of any kind, machine learning, real-time or streaming processing, a database, a web or graphical interface, network access, real customer or card data, currency handling, or time-zone handling. Ideas that could be added later are listed under [Future improvements](#future-improvements-not-implemented).

## Architecture and data flow

```
input CSV
   |  loader.py       reads rows as text and remembers each row's line number
   v
raw rows
   |  validation.py   accepts or rejects each row (with every reason)
   v
accepted transactions ------------------------> rejected rows + reasons
   |-- analytics.py  -> totals, averages, daily totals, top accounts
   |-- rules.py      -> flagged transactions (one row each, all reasons)
   v                                                   |
reporting.py -> terminal summary, flagged_transactions.csv, validation_errors.csv
```

The design keeps file access at the edges: only `loader.py`, `reporting.py` (its two writer functions) and `main.py` touch files. `validation.py`, `analytics.py` and `rules.py` are pure functions (data in, data out), which is why they can be tested with small hand-written lists. `models.py` defines the CSV schema and the small data containers shared by all modules, and `main.py` wires the steps together and sets the exit code.

## Requirements and setup

* Python 3.10 or newer. **No third-party packages**; `requirements.txt` is intentionally empty of packages.
* Developed and tested with **Python 3.12.3**. The code avoids features newer than Python 3.10, but it has **not** been run on 3.10 or 3.11.
* No setup step: download or clone the project, open a terminal in the project folder, and run the commands below. (Use `python3` instead of `python` if that is how Python is started on your system.)

## Example command

Run from the project folder (the default paths are relative to it):

```bash
python main.py --input data/transactions.csv --output-dir output
```

This reads `data/transactions.csv`, prints a summary, and writes `output/flagged_transactions.csv` and `output/validation_errors.csv`. Running it again overwrites those two files. The input file is never modified. `python main.py` with no options does the same thing.

## Input CSV schema and sample rows

The file must be UTF-8 text with a header row containing these columns (extra columns are ignored; the column order does not matter; names must match exactly):

| Column | Meaning | Rules |
|---|---|---|
| `transaction_id` | Unique ID of the record | Required, not blank, unique among accepted rows |
| `timestamp` | When the transaction happened | Exactly `YYYY-MM-DD HH:MM:SS` (zero-padded, no time zone) |
| `account_id` | Account that made the payment | Required, not blank |
| `amount` | Transaction amount | A finite number from 0 up to 1,000,000,000,000; negative amounts are rejected; zero is allowed |
| `merchant` | Merchant name | Required, not blank |
| `status` | Outcome | `approved` or `declined` (any letter case) |

Sample rows from `data/transactions.csv`:

```csv
transaction_id,timestamp,account_id,amount,merchant,status
TX0001,2026-10-01 08:25:02,AC027,129.60,Metro Ticket,approved
TX0002,2026-10-01 08:45:10,AC047,351.82,Grocery Store,declined
```

Leading and trailing spaces in fields are ignored. All amounts, accounts and merchants in the bundled data are fictional.

## Configuration options

| Option | Default | Meaning |
|---|---|---|
| `--input` | `data/transactions.csv` | Input CSV file |
| `--output-dir` | `output` | Folder for the two report files (created if missing) |
| `--high-value-threshold` | `1000.00` | `HIGH_VALUE`: flag amounts **strictly greater** than this (0 or more) |
| `--velocity-window-minutes` | `5` | `VELOCITY`: window length in minutes (at least 1); the window is inclusive |
| `--velocity-min-count` | `3` | `VELOCITY`: minimum transactions from one account in one window (at least 2) |
| `--daily-spend-threshold` | `3000.00` | `HIGH_DAILY_SPEND`: flag approved account-day totals **strictly greater** than this (0 or more) |

`python main.py --help` lists the same options. The terminal summary prints the settings that were used, including a ready-to-copy command line that repeats the run.

**Exit codes:** `0` success (flagged rows are normal results, not errors); `1` a file problem (unreadable input, bad header, input that would be overwritten by a report, output folder that cannot be created or written); `2` invalid command-line options (for example `--velocity-min-count 1` or a negative threshold).

## Output files

**`flagged_transactions.csv`**: one row per flagged transaction. Columns: `source_line` (line number in the input file, header = line 1), `transaction_id`, `timestamp`, `account_id`, `amount`, `merchant`, `status`, `flag_reasons` (every matching rule joined by `;`, always in the order `HIGH_VALUE;VELOCITY;HIGH_DAILY_SPEND`), and `review_note` (the same "review flag only, not proof of fraud" sentence on every row).

**`validation_errors.csv`**: one row per rejected input row. Columns: `source_line`, `transaction_id` (blank if the row had none) and `reasons` (every problem found, joined by ` | `).

Both files are UTF-8 with `\n` line endings, and running PayGuard twice on the same input produces byte-identical files. Text that starts with `=`, `+`, `-` or `@` is written with a leading `'` so that a spreadsheet shows it as text instead of running it as a formula.

## Example output

This is the real output of `python main.py` on the bundled data (the test suite checks that this block matches what the program prints):

```text
PAYGUARD REPORT
===============
Educational prototype using synthetic data. Flagged rows are transactions
selected for human review by simple rules. They are NOT proof of fraud.

Configuration
  input file:           data/transactions.csv
  output folder:        output
  HIGH_VALUE:           amount > 1000.00
  VELOCITY:             >= 3 transactions from one account within 5 minutes (inclusive)
  HIGH_DAILY_SPEND:     approved total per account per day > 3000.00
  spending counts:      approved transactions only
  reproduce with:       python main.py --input data/transactions.csv --output-dir output --high-value-threshold 1000.00 --velocity-window-minutes 5 --velocity-min-count 3 --daily-spend-threshold 3000.00

Data quality
  rows read:            478
  accepted:             462
  rejected:             16

Accepted transactions
  status counts:        approved 422, declined 40
  total approved value: 95,641.79
  average approved:     226.64
  declined value:       9,968.73 (not counted as spending)

Top accounts by approved spending
  1. AC923  4,000.00
  2. AC924  3,600.00
  3. AC921  3,000.01
  4. AC920  3,000.00
  5. AC922  2,700.00

Daily approved totals
  2026-10-01  5,075.05
  2026-10-02  8,315.69
  2026-10-03  3,738.71
  2026-10-04  7,391.60
  2026-10-05  5,934.56
  2026-10-06  5,244.27
  2026-10-07  4,498.97
  2026-10-08  15,965.39
  2026-10-09  6,590.80
  2026-10-10  10,107.83
  2026-10-11  6,205.12
  2026-10-12  5,673.96
  2026-10-13  5,370.56
  2026-10-14  5,529.28

Review flags
  transactions flagged for review: 28
    HIGH_VALUE: 6
    VELOCITY: 23
    HIGH_DAILY_SPEND: 6
  (one transaction can match several rules, so these counts can add up to more)

Reports written
  output/flagged_transactions.csv  (28 rows)
  output/validation_errors.csv  (16 rows)
```

First lines of `output/flagged_transactions.csv` (the last row matches all three rules and is still one row):

```csv
source_line,transaction_id,timestamp,account_id,amount,merchant,status,flag_reasons,review_note
43,TX0039,2026-10-02 12:00:00,AC903,1000.01,Test Merchant,approved,HIGH_VALUE,Review flag only - not proof of fraud
44,TX0040,2026-10-02 13:00:00,AC904,2500.00,Test Merchant,declined,HIGH_VALUE,Review flag only - not proof of fraud
330,TX0313,2026-10-10 15:00:00,AC924,1200.00,Test Merchant,approved,HIGH_VALUE;VELOCITY;HIGH_DAILY_SPEND,Review flag only - not proof of fraud
```

First lines of `output/validation_errors.csv`:

```csv
source_line,transaction_id,reasons
12,,missing required field: transaction_id
25,TX9002,missing required field: account_id
38,TX9003,invalid timestamp '2026-13-45 25:61:00'; expected YYYY-MM-DD HH:MM:SS
```

## Rule definitions and assumptions

A rule match is a **review flag**: a prompt for a human to look, never a conclusion that fraud occurred.

| Rule | Flags a transaction when... | Boundary conditions |
|---|---|---|
| `HIGH_VALUE` | its amount is greater than the threshold | Strictly greater: `999.99` and `1000.00` are not flagged, `1000.01` is. Applies to approved **and** declined transactions. |
| `VELOCITY` | it belongs to a group of at least `min_count` transactions from the **same account** inside a window of `window_minutes` | Inclusive window: 09:00:00, 09:02:30 and 09:05:00 are flagged; 09:00:00, 09:02:30 and 09:05:01 are not. Every row in any qualifying window is flagged (a rolling chain at 12:00, 12:02, 12:04, 12:06, 12:08 flags all five). Rows with identical timestamps count. The window ignores midnight. Applies to approved **and** declined transactions. |
| `HIGH_DAILY_SPEND` | it is an **approved** transaction of an account whose approved total for that calendar day is greater than the threshold | Strictly greater: a total of exactly `3000.00` is not flagged, `3000.01` is. Declined transactions are neither added to the total nor flagged by this rule. Days are the calendar date of the timestamp; accounts and days are never combined. |

When one transaction matches several rules it appears **once**, with all its reasons. The rules are independent functions in `payguard/rules.py`; `apply_rules` combines them.

Assumptions worth knowing:

* **Spending means approved transactions only.** Total value, average, daily totals, top accounts and `HIGH_DAILY_SPEND` ignore declined transactions. Declined transactions still appear in the status counts, and their total is printed separately as "declined value". `HIGH_VALUE` and `VELOCITY` also look at declined transactions because they describe attempts, not money spent.
* **Duplicate IDs: the first accepted row wins.** A later row with an ID that was already accepted is rejected (and the reason names the line of the first one). A rejected row never claims an ID, so a valid row that follows it is still accepted. IDs are case-sensitive (`TX1` is not `tx1`) after trimming spaces.
* **Rejected rows are never counted.** They appear only in the validation report.
* **Money uses Python's `Decimal`**, so sums are exact (0.10 + 0.20 is 0.30). Totals are not rounded; the average is rounded half-up to two decimal places.
* **Every required field must be non-blank**, and a row with more fields than the header is rejected.
* **Timestamps carry no time zone.** Values are used exactly as written.

## Running the tests

```bash
python -m unittest            # run everything
python -m unittest -v         # list every test
python -m unittest tests.test_rules   # one file
```

The tests need no network access, no installed packages and no particular working directory; they use small hand-written fixtures and temporary folders, and are deterministic. They cover, among other things: valid rows, missing columns, invalid timestamps and amounts, negative amounts, `NaN`/`Infinity`, duplicate IDs, empty datasets, exact threshold boundaries, velocity windows including boundary timestamps, daily totals, multiple reasons on one transaction, report file contents, missing files and invalid paths, exit codes, and overwrite protection. `tests/test_dataset_answer_key.py` also checks PayGuard's results on the full sample dataset against a hand-written answer key (`data/planted_cases.csv`).

## Regenerating the sample data

```bash
python scripts/generate_data.py            # rewrites data/transactions.csv and data/planted_cases.csv
python scripts/generate_data.py --seed 7   # a different ordinary background; the planted cases stay the same
```

The dataset has ordinary background activity that cannot trigger any rule, a few dozen hand-placed cases at the rule boundaries and for duplicate IDs, and 16 deliberately invalid rows. `data/planted_cases.csv` is the answer key: for each planted row it states whether it must be accepted or rejected and which rules must flag it. The generator is deliberately independent of the `payguard` package and uses only `random.random()`, whose output for a given seed Python guarantees across versions; a test checks that regenerating gives exactly the committed files.

## Known limitations

* **Simple, arbitrary rules.** The thresholds are fixed numbers, not learned from data. The rules will flag normal behaviour and cannot recognise real fraud.
* **Synthetic data only.** The bundled dataset is generated and is not realistic. No real or public dataset has been used.
* **The whole input file is read into memory.** Around 200,000 rows took a few seconds in a development check, but very large files may not fit in memory.
* **No time zones and no currency.** Timestamps are taken as written and amounts are plain numbers.
* **Amount parsing is lenient.** It uses Python's `Decimal`, which also accepts forms such as `+5`, `-0.00`, `1_000.00`, `1e3` and non-ASCII digits. They are read as the numbers they represent. There is no limit on decimal places.
* **The header must match exactly** (letter case and spaces matter). A file with a missing or repeated required column name, or a NUL character, is rejected as a whole.
* **Duplicate detection works within one file only.**
* **Report files:** UTF-8 without a byte-order mark, so Excel may show non-ASCII text incorrectly unless the file is imported as UTF-8. Values starting with `= + - @` get a leading `'`. Reports are overwritten on every run and are not written atomically.
* **The terminal summary prints at most 14 daily totals.**
* **Not covered by automated tests:** Python versions other than 3.12.3, running on Windows or macOS (Windows paths and line endings are only simulated in tests), performance on large files, and how a spreadsheet application displays the reports.
* **Default paths are relative to the working directory**, so run the program from the project folder or pass `--input` and `--output-dir`.

## Future improvements (not implemented)

None of these exist in the code today.

* Add an optional adapter for a public simulated-transaction dataset, only after checking its license and removing personal-looking fields.
* Process files row by row instead of loading everything into memory.
* More rules and per-account baselines instead of one fixed threshold for everyone.
* A configuration file, additional output formats (for example JSON), and a report of rejection reasons grouped by type.
* Time-zone and currency support.
* Automated checks on more Python versions, static type checking, and packaging as an installable command.

## Project layout

```text
payguard/
  __init__.py        package description
  models.py          CSV schema constants and data containers
  loader.py          read the CSV and check the header
  validation.py      accept or reject each row
  analytics.py       totals, averages, daily totals, top accounts
  rules.py           HIGH_VALUE, VELOCITY, HIGH_DAILY_SPEND and the merge step
  reporting.py       CSV reports and the terminal summary
main.py              command-line entry point
scripts/generate_data.py   synthetic dataset generator
data/transactions.csv      sample input (generated)
data/planted_cases.csv     answer key for the sample input (generated)
tests/               automated tests (unittest)
requirements.txt     no third-party packages
.gitignore           files Git should not track (generated output, caches)
.gitattributes       keeps LF line endings on every operating system
```
