"""Making sure a bank CSV is stored in the configured encoding must never
change its content.

It used to: the file was read with a guessed encoding and bad bytes replaced
by "�", then written back as UTF-8.  For a mostly-ASCII file the guess
was "ascii", so every non-ASCII byte became a 3-byte replacement character,
and on the next run each of those bytes became one again: the field tripled
on every run until the CSV parser refused the file.
"""

import codecs
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from hledger_core import file_reading_and_writing
from hledger_core.file_reading_and_writing import (
    convert_input_csv_encoding,
    detect_file_encoding,
)

REPLACEMENT = "�".encode("utf-8")
ROW = b'"01-02-2025","NL00BANK0123456789","12,34","debit","Shop","x"\n'
# A non-breaking space that was once decoded as Latin-1 and saved as UTF-8:
# four non-ASCII bytes that are perfectly valid UTF-8.
ODD = b"\xc3\x82\xc2\xa0"


def _mostly_ascii(tmp_path: Path) -> Path:
    path = tmp_path / "bank.csv"
    path.write_bytes(ROW * 3000 + b'"x","Caf' + ODD + b'","1,00"\n' + ROW * 500)
    return path


def _guess_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the detector guess what it guesses for a large, mostly-ASCII
    file: plain ASCII."""

    def detect(_raw: bytes) -> Dict[str, Any]:
        return {"encoding": "ascii", "confidence": 1.0}

    monkeypatch.setattr(file_reading_and_writing.chardet, "detect", detect)


def _convert(path: Path, encoding: str = "utf-8") -> None:
    convert_input_csv_encoding(
        input_csv_filepath=str(path), output_encoding=encoding
    )


# ------------------------------------------------------------- regression


def test_repeated_runs_do_not_change_a_utf8_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _mostly_ascii(tmp_path)
    original = path.read_bytes()
    _guess_ascii(monkeypatch)

    for _ in range(10):
        _convert(path)
        assert path.read_bytes() == original

    assert REPLACEMENT not in path.read_bytes()


def test_same_with_the_real_detector(tmp_path: Path) -> None:
    path = _mostly_ascii(tmp_path)
    original = path.read_bytes()
    for _ in range(3):
        _convert(path)
    assert path.read_bytes() == original


def test_file_already_in_the_target_encoding_is_not_rewritten(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes("café,€5\n".encode("utf-8"))
    before = os.stat(path)
    _convert(path)
    after = os.stat(path)
    assert (after.st_ino, after.st_mtime_ns) == (
        before.st_ino,
        before.st_mtime_ns,
    )


def test_detected_encoding_always_decodes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _mostly_ascii(tmp_path)
    _guess_ascii(monkeypatch)
    encoding = detect_file_encoding(filepath=str(path))
    assert encoding.lower() != "ascii"
    text = path.read_bytes().decode(encoding)  # strict: must not raise
    assert "�" not in text


# ------------------------------------------------------------- conversion


def test_other_encoding_is_converted_once_without_loss(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes("naam,café,€5\r\n".encode("cp1252") * 50)

    _convert(path)
    converted = path.read_bytes()
    assert converted == "naam,café,€5\r\n".encode("utf-8") * 50
    assert REPLACEMENT not in converted

    _convert(path)
    assert path.read_bytes() == converted


def test_wrong_guess_falls_back_to_an_encoding_that_fits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes("café\n".encode("latin-1"))
    _guess_ascii(monkeypatch)

    _convert(path)

    assert path.read_bytes() == "café\n".encode("utf-8")


def test_line_endings_are_kept(tmp_path: Path) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes("a,é\r\nb,ü\r\n".encode("latin-1"))
    _convert(path)
    assert path.read_bytes() == "a,é\r\nb,ü\r\n".encode("utf-8")


def test_utf8_byte_order_mark_is_dropped_once(tmp_path: Path) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes(codecs.BOM_UTF8 + "a,é\n".encode("utf-8"))
    _convert(path)
    assert path.read_bytes() == "a,é\n".encode("utf-8")
    _convert(path)
    assert path.read_bytes() == "a,é\n".encode("utf-8")


def test_plain_ascii_file_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes(ROW * 10)
    before = os.stat(path).st_mtime_ns
    _convert(path)
    assert path.read_bytes() == ROW * 10
    assert os.stat(path).st_mtime_ns == before


def test_content_that_does_not_fit_the_target_is_refused(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bank.csv"
    original = "café\n".encode("utf-8")
    path.write_bytes(original)
    with pytest.raises(ValueError, match="ascii"):
        _convert(path, encoding="ascii")
    assert path.read_bytes() == original


def test_failed_write_leaves_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bank.csv"
    original = "café\n".encode("latin-1")
    path.write_bytes(original)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(file_reading_and_writing.os, "replace", refuse)
    with pytest.raises(OSError):
        _convert(path)
    monkeypatch.undo()

    assert path.read_bytes() == original
    assert os.listdir(tmp_path) == ["bank.csv"]


# -------------------------------------------------------------- detection


def test_empty_file_is_utf8(tmp_path: Path) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes(b"")
    assert detect_file_encoding(filepath=str(path)).lower() == "utf-8"
    _convert(path)
    assert path.read_bytes() == b""


def _guess(
    monkeypatch: pytest.MonkeyPatch, *, encoding: str, confidence: float
) -> None:
    def detect(_raw: bytes) -> Dict[str, Any]:
        return {"encoding": encoding, "confidence": confidence}

    monkeypatch.setattr(file_reading_and_writing.chardet, "detect", detect)


def test_low_confidence_guess_is_not_believed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For a short Windows-1252 text the detector names a Hebrew DOS code
    page at 5%; converting with that would store the wrong characters for
    good."""
    path = tmp_path / "bank.csv"
    path.write_bytes("café €5\n".encode("cp1252"))
    _guess(monkeypatch, encoding="cp862", confidence=0.05)

    assert detect_file_encoding(filepath=str(path)) == "cp1252"
    _convert(path)
    assert path.read_bytes() == "café €5\n".encode("utf-8")


def test_confident_guess_that_fits_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes("Łódź\n".encode("iso8859-2"))
    _guess(monkeypatch, encoding="iso8859-2", confidence=0.9)

    assert detect_file_encoding(filepath=str(path)) == "iso8859-2"
    _convert(path)
    assert path.read_bytes() == "Łódź\n".encode("utf-8")


def test_utf8_is_recognised_without_asking_the_detector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes("café\n".encode("utf-8"))

    def never(_raw: bytes) -> Dict[str, Any]:
        raise AssertionError("the detector should not be needed")

    monkeypatch.setattr(file_reading_and_writing.chardet, "detect", never)
    assert detect_file_encoding(filepath=str(path)) == "utf-8"


def test_byte_order_marks_are_recognised(tmp_path: Path) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes(codecs.BOM_UTF8 + b"a\n")
    assert detect_file_encoding(filepath=str(path)) == "utf-8-sig"

    path.write_bytes("a,é\n".encode("utf-16"))
    assert detect_file_encoding(filepath=str(path)) == "utf-16"
    _convert(path)
    assert path.read_bytes() == "a,é\n".encode("utf-8")


def test_unknown_guess_is_replaced_by_one_that_fits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bank.csv"
    path.write_bytes("café\n".encode("utf-8"))

    def detect(_raw: bytes) -> Dict[str, Any]:
        return {"encoding": "no-such-encoding", "confidence": 0.1}

    monkeypatch.setattr(file_reading_and_writing.chardet, "detect", detect)
    assert detect_file_encoding(filepath=str(path)) == "utf-8"
