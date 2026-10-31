"""Tests for payguard.loader: reading files, header checks, line numbers, file errors."""
import tempfile
import unittest
from pathlib import Path

from payguard.loader import InputFileError, load_rows

HEADER = "transaction_id,timestamp,account_id,amount,merchant,status\n"
GOOD_1 = "TX1,2026-10-01 09:00:00,AC1,10.00,Cafe,approved\n"
GOOD_2 = "TX2,2026-10-01 10:00:00,AC2,20.00,Shop,declined\n"


class LoaderTests(unittest.TestCase):
    def setUp(self):
        # A fresh temporary folder per test, deleted automatically afterwards.
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "input.csv"

    def write(self, text, encoding="utf-8"):
        self.path.write_bytes(text.encode(encoding))

    # ---- normal reading ----
    def test_reads_rows_with_line_numbers(self):
        self.write(HEADER + GOOD_1 + GOOD_2)
        rows = load_rows(self.path)
        self.assertEqual([line for line, _ in rows], [2, 3])
        self.assertEqual(rows[0][1]["transaction_id"], "TX1")
        self.assertEqual(rows[1][1]["status"], "declined")

    def test_header_only_file_gives_no_rows(self):
        self.write(HEADER)
        self.assertEqual(load_rows(self.path), [])

    def test_blank_line_does_not_shift_later_line_numbers(self):
        self.write(HEADER + GOOD_1 + "\n" + GOOD_2)    # blank line 3, TX2 is on line 4
        rows = load_rows(self.path)
        self.assertEqual([line for line, _ in rows], [2, 4])

    def test_comma_inside_quotes_stays_in_one_field(self):
        self.write(HEADER + 'TX1,2026-10-01 09:00:00,AC1,10.00,"Corner Store, Main St",approved\n')
        rows = load_rows(self.path)
        self.assertEqual(rows[0][1]["merchant"], "Corner Store, Main St")

    def test_quoted_field_spanning_two_lines_keeps_later_line_numbers_right(self):
        # Line 1 header; TX1 occupies lines 2-3 (a quoted newline); TX2 is on line 4.
        multi = 'TX1,2026-10-01 09:00:00,AC1,10.00,"Line one\nLine two",approved\n'
        self.write(HEADER + multi + GOOD_2)
        rows = load_rows(self.path)
        self.assertEqual([line for line, _ in rows], [3, 4])   # a row is numbered by the line it ends on

    def test_excel_byte_order_mark_is_ignored(self):
        self.write(HEADER + GOOD_1, encoding="utf-8-sig")
        rows = load_rows(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["transaction_id"], "TX1")

    def test_column_order_does_not_matter(self):
        self.write("status,amount,merchant,account_id,timestamp,transaction_id\n"
                   "approved,10.00,Cafe,AC1,2026-10-01 09:00:00,TX1\n")
        row = load_rows(self.path)[0][1]
        self.assertEqual(row["transaction_id"], "TX1")
        self.assertEqual(row["amount"], "10.00")
        self.assertEqual(row["status"], "approved")

    def test_column_names_must_match_exactly(self):
        for header in ("TRANSACTION_ID,TIMESTAMP,ACCOUNT_ID,AMOUNT,MERCHANT,STATUS\n",
                       "transaction_id, timestamp, account_id, amount, merchant, status\n"):
            with self.subTest(header=header):
                self.write(header)
                with self.assertRaises(InputFileError):
                    load_rows(self.path)

    def test_extra_columns_in_header_are_allowed(self):
        self.write("transaction_id,timestamp,account_id,amount,merchant,status,notes\n"
                   "TX1,2026-10-01 09:00:00,AC1,10.00,Cafe,approved,hello\n")
        self.assertEqual(len(load_rows(self.path)), 1)

    # ---- ragged rows are passed on, not judged ----
    def test_short_row_gets_empty_strings(self):
        self.write(HEADER + "TX1,2026-10-01 09:00:00,AC1,10.00,Cafe\n")
        row = load_rows(self.path)[0][1]
        self.assertEqual(row["status"], "")

    def test_surplus_fields_are_kept_under_extra_key(self):
        self.write(HEADER + "TX1,2026-10-01 09:00:00,AC1,10.00,Cafe,approved,surplus\n")
        row = load_rows(self.path)[0][1]
        self.assertEqual(row["_extra"], ["surplus"])

    # ---- problems that stop the run ----
    def test_missing_file_raises_clear_error(self):
        with self.assertRaises(InputFileError) as ctx:
            load_rows(Path(self.folder.name) / "does_not_exist.csv")
        self.assertIn("cannot read", str(ctx.exception))

    def test_directory_instead_of_file_raises_error(self):
        with self.assertRaises(InputFileError):
            load_rows(Path(self.folder.name))

    def test_empty_file_raises_error(self):
        self.write("")
        with self.assertRaises(InputFileError) as ctx:
            load_rows(self.path)
        self.assertIn("empty", str(ctx.exception))

    def test_missing_columns_are_named_in_the_error(self):
        self.write("transaction_id,timestamp,account_id\nTX1,2026-10-01 09:00:00,AC1\n")
        with self.assertRaises(InputFileError) as ctx:
            load_rows(self.path)
        message = str(ctx.exception)
        for name in ("amount", "merchant", "status"):
            self.assertIn(name, message)

    def test_repeated_column_names_raise_error(self):
        self.write("transaction_id,timestamp,account_id,amount,merchant,status,amount\n"
                   "TX1,2026-10-01 09:00:00,AC1,10.00,Cafe,approved,99.00\n")
        with self.assertRaises(InputFileError) as ctx:
            load_rows(self.path)
        self.assertIn("repeated column names: amount", str(ctx.exception))

    def test_nul_character_raises_error_with_its_line_number(self):
        self.write(HEADER + GOOD_1 + "TX2,2026-10-01 10:00:00,AC2,20.00,Sh\x00op,declined\n")
        with self.assertRaises(InputFileError) as ctx:
            load_rows(self.path)
        self.assertIn("NUL character on line 3", str(ctx.exception))

    def test_file_that_is_not_utf8_raises_error(self):
        self.path.write_bytes(HEADER.encode("utf-8") + b"TX1,\xff\xfe,AC1,10.00,Cafe,approved\n")
        with self.assertRaises(InputFileError) as ctx:
            load_rows(self.path)
        self.assertIn("UTF-8", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
