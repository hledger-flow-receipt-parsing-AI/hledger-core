"""Reading a bank's CSV export into transactions.

Lives here (not in the preprocessor) so that hledger-ai can read the same
rows the categoriser sees.  The account config (hledger-config) is duck
typed: it provides ``csv_delimiter``, ``parse_csv_rows`` and the account.
"""

from __future__ import annotations

import csv
import re
from typing import Any, List

from typeguard import typechecked

from hledger_core.file_reading_and_writing import (
    convert_input_csv_encoding,
    detect_file_encoding,
)

DEFAULT_DELIMITER = ","
_NUMBER = re.compile(r"^[-+]?\d[\d.,]*$")
_DATE = re.compile(r"^(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{8})(\s.*)?$")


@typechecked
def read_bank_csv_rows(
    *, path: str, encoding: str, delimiter: str = DEFAULT_DELIMITER
) -> List[List[str]]:
    """Every non-blank row of the file, as the CSV module splits it."""
    with open(path, encoding=encoding, errors="replace", newline="") as f:
        return [
            row
            for row in csv.reader(f, delimiter=delimiter)
            if any(cell.strip() for cell in row)
        ]


@typechecked
def looks_like_header(*, row: List[str]) -> bool:
    """A header names its columns: no cell is a number or a date."""
    cells = [cell.strip() for cell in row if cell.strip()]
    if not cells:
        return False
    return not any(_NUMBER.match(c) or _DATE.match(c) for c in cells)


@typechecked
def load_bank_transactions(
    *, account_config: Any, abs_csv_filepath: str, csv_encoding: str
) -> List[Any]:
    """The transactions of one account's CSV export, in file order."""
    convert_input_csv_encoding(
        input_csv_filepath=abs_csv_filepath, output_encoding=csv_encoding
    )
    rows = read_bank_csv_rows(
        path=abs_csv_filepath,
        encoding=detect_file_encoding(filepath=abs_csv_filepath),
        delimiter=getattr(account_config, "csv_delimiter", None)
        or DEFAULT_DELIMITER,
    )
    start_index = 1 if rows and looks_like_header(row=rows[0]) else 0
    return account_config.parse_csv_rows(rows=rows, start_index=start_index)
