"""Read the input CSV.

This module only reads text. It does not decide whether a row is valid;
that is the job of validation.py.
"""
import csv
from pathlib import Path
from typing import Any

from payguard.models import REQUIRED_COLUMNS


class InputFileError(Exception):
    """The input file is missing, unreadable, or has the wrong header.

    These problems stop the whole run. A single malformed row is different:
    it is reported in validation_errors.csv while the other rows continue.
    """


def reject_nul_characters(lines, path):
    """Pass lines through unchanged, but stop with a clear error if one holds a NUL character.

    Older Python versions refuse NUL characters inside the csv module and newer
    ones accept them. Checking here makes PayGuard behave the same on every
    supported version, and a NUL almost always means the file is not a text CSV.
    """
    for line_number, line in enumerate(lines, start=1):
        if "\x00" in line:
            raise InputFileError(f"{path} contains a NUL character on line {line_number}; "
                                 "it does not look like a text CSV file")
        yield line


def load_rows(path: Path) -> list[tuple[int, dict[str, Any]]]:
    """Return (source_line, row) pairs for every data row in the CSV.

    - A row is a dict that maps column name to text.
    - source_line is the line in the file where the row ends, so it matches
      what you see in an editor or spreadsheet (the header is line 1).
    - A row with too few fields gets "" for the missing ones.
    - A row with too many fields keeps the surplus values under the key "_extra".

    Raises InputFileError if the file is missing, unreadable, empty, lacks a
    required column, repeats a column name, or contains a NUL character.
    """
    rows = []
    try:
        # utf-8-sig quietly removes the invisible BOM that Excel adds to CSV files.
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(reject_nul_characters(f, path), restval="", restkey="_extra")
            header = reader.fieldnames
            if not header:
                raise InputFileError(f"{path} is empty: no header row found")
            missing = [name for name in REQUIRED_COLUMNS if name not in header]
            if missing:
                raise InputFileError(f"{path} is missing required columns: {', '.join(missing)}")
            repeated = sorted({name for name in header if header.count(name) > 1})
            if repeated:
                # With repeated names the reader would silently keep only the last column.
                raise InputFileError(f"{path} has repeated column names: {', '.join(repeated)}")
            for row in reader:
                # line_num counts physical lines read so far. Counting rows
                # ourselves would drift if the file had blank lines.
                rows.append((reader.line_num, row))
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise InputFileError(f"cannot read {path}: {reason}") from exc
    except UnicodeDecodeError as exc:
        raise InputFileError(f"{path} is not valid UTF-8 text") from exc
    except csv.Error as exc:
        raise InputFileError(f"{path} is not a readable CSV file: {exc}") from exc
    return rows
