"""Handles file reading and writing."""

import codecs
import hashlib
import json
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Union

import chardet
from typeguard import typechecked

from hledger_core.generics.enums import EnumEncoder


def create_and_save_json(*, data, filepath) -> None:
    """
    Creates a JSON file from a Python dictionary or list.

    Args:
        data: The Python dictionary or list to be converted to JSON.
        filepath: The name of the file to save the JSON data to (default: "data.json").
            Include the.json extension.

    Returns:
        True if the JSON file was created and saved successfully, False otherwise.
        Prints informative messages to the console about success or failure.
    """

    with open(filepath, "w") as f:
        json.dump(
            data, f, indent=4, cls=EnumEncoder
        )  # Use indent for pretty printing (optional)
        print(f"JSON data successfully saved to {filepath}")
    assert_file_exists(filepath=filepath)


def load_json_from_file(
    *, json_filepath: str
) -> Union[Dict[str, Any], List[Any]]:
    """Loads JSON data from a file.

    Args:
        filepath: The path to the JSON file.

    Returns:
        A dictionary or list representing the JSON data, or None if an error occurs.
        Specifically, returns a dictionary if the JSON represents an object, and
        a list if it represents a JSON array.  If the JSON file contains neither
        a top-level object nor a top-level array, the behavior is undefined.  It
        is best practice to ensure your JSON files have a top-level object or array.

        Raises FileNotFoundError if the file does not exist.
        Raises json.JSONDecodeError if the file contains invalid JSON.
    """
    with open(json_filepath, encoding="utf-8") as f:  # Specify UTF-8 encoding
        return json.load(f)


@typechecked
def write_to_file(*, content: str, filepath: str) -> None:
    with open(filepath, mode="w", encoding="utf-8") as file:
        file.write(content)
    assert_file_exists(filepath=filepath)


@typechecked
def assert_file_exists(*, filepath: str) -> None:
    """Asserts that the given file exists.

    Args:
      filepath: The path to the file.

    Raises:
      FileNotFoundError: If the file does not exist.
    """

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File '{filepath}' does not exist.")


# Below this confidence the detector's guess is close to random: for a short
# Windows-1252 text it names Mac Roman or a Hebrew DOS code page at 2-5%.
_MIN_GUESS_CONFIDENCE = 0.5
# What a Western European export that is not UTF-8 almost always is.  latin-1
# maps every byte to a character, so it always fits.
_FALLBACK_ENCODINGS = ("cp1252", "latin-1")


@typechecked
def _decodes(*, raw_data: bytes, encoding: str) -> bool:
    try:
        raw_data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return False
    return True


@typechecked
def detect_file_encoding(*, filepath: str) -> str:
    """An encoding that decodes the whole file without errors.

    Whether the bytes are valid UTF-8 is checked first: that is far more
    reliable than the detector, which calls a large, mostly-ASCII UTF-8 file
    "ascii".  Reading with such a guess and ``errors="replace"`` silently
    turns the non-ASCII bytes into replacement characters.  The detector is
    only asked for files that are not UTF-8, and only believed when it is
    confident and its answer fits the file.
    """
    with open(filepath, "rb") as file:
        raw_data = file.read()

    # UTF-32 first: its little-endian mark starts with the UTF-16 one.
    if raw_data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return "utf-32"
    if raw_data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    if _decodes(raw_data=raw_data, encoding="utf-8"):
        if raw_data.startswith(codecs.BOM_UTF8):
            return "utf-8-sig"
        return "utf-8"

    result = chardet.detect(raw_data)
    guess: Optional[str] = result.get("encoding")
    confidence: float = float(result.get("confidence") or 0.0)
    if guess is None or str(guess) == "None":
        print(
            f"WARNING: Did not detect encoding for:\n{filepath}\n assumed"
            f" {_FALLBACK_ENCODINGS[0]}"
        )
    elif confidence >= _MIN_GUESS_CONFIDENCE and _decodes(
        raw_data=raw_data, encoding=str(guess)
    ):
        return str(guess)
    for encoding in _FALLBACK_ENCODINGS:
        if _decodes(raw_data=raw_data, encoding=encoding):
            return encoding
    return "latin-1"


@typechecked
def convert_input_csv_encoding(
    *, input_csv_filepath: str, output_encoding: str
) -> None:
    """Make sure the file is stored in *output_encoding*, without changing
    its content.

    A file that already is in *output_encoding* is not touched.  This used
    to read the file with a guessed encoding, replace what did not fit by
    replacement characters and write the result back on every run; for a
    mostly-ASCII UTF-8 file each non-ASCII byte tripled per run, until the
    CSV parser refused the file ("field larger than field limit").

    Raises ValueError, leaving the file as it was, when the content cannot
    be stored in *output_encoding*.
    """
    if input_csv_filepath is None:
        raise ValueError(f"Must have valid filepath, got:{input_csv_filepath}")
    with open(input_csv_filepath, "rb") as infile:
        raw_data = infile.read()

    to_utf8 = codecs.lookup(output_encoding).name == "utf-8"
    if to_utf8 and raw_data.startswith(codecs.BOM_UTF8):
        # Same content without the byte order mark.
        converted = raw_data[len(codecs.BOM_UTF8) :]
    else:
        try:
            raw_data.decode(output_encoding)
            return  # Already stored in the wanted encoding.
        except UnicodeDecodeError:
            pass
        source_encoding = detect_file_encoding(filepath=input_csv_filepath)
        # Strict decoding: detect_file_encoding() returned an encoding that
        # fits every byte, so nothing is replaced or dropped.
        content = raw_data.decode(source_encoding)
        try:
            converted = content.encode(output_encoding)
        except UnicodeEncodeError as error:
            raise ValueError(
                f"Cannot store {input_csv_filepath} as {output_encoding}:"
                f" {error}"
            ) from error

    # Replace the file in one step, so a failure cannot leave half a file.
    target = os.path.realpath(input_csv_filepath)
    descriptor, temp_path = tempfile.mkstemp(
        dir=os.path.dirname(target), prefix=".encoding-", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as outfile:
            outfile.write(converted)
            outfile.flush()
            os.fsync(outfile.fileno())
        shutil.copymode(target, temp_path)
        os.replace(temp_path, target)
    except BaseException:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


@typechecked
def get_image_hash(*, image_path: str) -> str:
    """Calculates the SHA256 hash of an image."""
    hasher = hashlib.sha256()
    with open(image_path, "rb") as image_file:
        while True:
            chunk = image_file.read(4096)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
