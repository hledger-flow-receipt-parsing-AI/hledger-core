"""Bank CSV reading: delimiters, header detection, Dutch Af/Bij codes.
Invented data only."""

from pathlib import Path

import pytest

from hledger_core.csv_parsing.bank_csv import (
    load_bank_transactions,
    looks_like_header,
    read_bank_csv_rows,
)
from hledger_core.TransactionObjects.Posting import TransactionCode


@pytest.mark.parametrize(
    "row, expected",
    [
        (["Datum", "Naam / Omschrijving", "Af Bij", "Bedrag (EUR)"], True),
        (["20260104", "Voorbeeld Winkel", "Af", "12,50"], False),
        (["15-01-2025", "NL00VBLD0000000001", "-42.17", "debit"], False),
        (["date", "amount", "description"], True),
        (["", "", ""], False),
        (["2025/03/01 10:00", "x"], False),
    ],
)
def test_header_detection(row, expected):
    assert looks_like_header(row=row) is expected


def test_semicolon_rows_are_split_and_blank_lines_dropped(tmp_path: Path):
    path = tmp_path / "bank.csv"
    path.write_text(
        '"Datum";"Naam";"Af Bij";"Bedrag (EUR)"\r\n'
        '"20260104";"Voorbeeld Winkel";"Af";"12,50"\r\n'
        "\r\n",
        encoding="utf-8",
    )
    rows = read_bank_csv_rows(path=str(path), encoding="utf-8", delimiter=";")
    assert rows == [
        ["Datum", "Naam", "Af Bij", "Bedrag (EUR)"],
        ["20260104", "Voorbeeld Winkel", "Af", "12,50"],
    ]


def test_af_and_bij_are_debit_and_credit():
    assert (
        TransactionCode.normalize_transaction_code("Af")
        == TransactionCode.DEBIT
    )
    assert (
        TransactionCode.normalize_transaction_code("bij")
        == TransactionCode.CREDIT
    )
    with pytest.raises(ValueError):
        TransactionCode.normalize_transaction_code("sideways")


class _FakeAccountConfig:
    """Only what load_bank_transactions uses."""

    csv_delimiter = ";"

    def __init__(self) -> None:
        self.calls = []

    def parse_csv_rows(self, *, rows, start_index):
        self.calls.append((rows, start_index))
        return rows[start_index:]


def test_load_skips_the_header_and_uses_the_delimiter(tmp_path: Path):
    path = tmp_path / "bank.csv"
    path.write_text(
        "Datum;Naam;Af Bij;Bedrag (EUR)\n20260104;Voorbeeld Winkel;Af;12,50\n",
        encoding="utf-8",
    )
    account = _FakeAccountConfig()
    result = load_bank_transactions(
        account_config=account,
        abs_csv_filepath=str(path),
        csv_encoding="utf-8",
    )
    assert result == [["20260104", "Voorbeeld Winkel", "Af", "12,50"]]
    assert account.calls[0][1] == 1
