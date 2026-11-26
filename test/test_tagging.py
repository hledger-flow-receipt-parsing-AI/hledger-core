"""Tags for events and projects, and the traceability words.  All tags here
are invented."""

from datetime import date
from pathlib import Path

import pytest

from hledger_core.tagging import (
    TagDefinition,
    journal_comment,
    load_tag_definitions,
    normalize_tag,
    parse_tags,
    stated_traceability,
    user_tags,
)


@pytest.mark.parametrize(
    "text, tag",
    [
        ("workbench", "workbench"),
        ("  WORKBENCH ", "workbench"),
        ("Seaside Trip 2023", "seaside-trip-2023"),
        ("garden_shed", "garden_shed"),
        ("trip: Rome!", "trip-rome"),
        ("a,b", "a-b"),
        ("-x-", "x"),
        ("Fête", "fête"),
        ("", ""),
    ],
)
def test_normalize_tag(text: str, tag: str) -> None:
    assert normalize_tag(text=text) == tag


def test_parse_tags_keeps_order_and_drops_repeats_and_blanks() -> None:
    assert parse_tags(
        text="workbench, Garden shed,, WORKBENCH , traceable"
    ) == [
        "workbench",
        "garden-shed",
        "traceable",
    ]


def test_traceability_words_are_not_user_tags() -> None:
    tags = ["workbench", "untraceable", "garden"]

    assert user_tags(tags=tags) == ["workbench", "garden"]
    assert stated_traceability(tags=tags) is False
    assert stated_traceability(tags=["traceable"]) is True
    assert stated_traceability(tags=["workbench"]) is None


def test_journal_comment() -> None:
    assert (
        journal_comment(tags=["workbench", "garden"], traceable=True)
        == "workbench:, garden:, traceable:yes"
    )
    assert (
        journal_comment(tags=["untraceable"], traceable=False) == "traceable:no"
    )
    assert journal_comment(tags=[], traceable=None) == ""


def test_definitions_from_the_tags_file(tmp_path: Path) -> None:
    path = tmp_path / "tags.yaml"
    path.write_text(
        "Summer trip:\n"
        "  description: A week by the sea\n"
        "  from: 2023-07-01\n"
        "  to: 2023-07-08\n"
        "  rules:\n"
        "    - account: assets:bank\n"
        "workbench:\n",
        encoding="utf-8",
    )

    trip, workbench = load_tag_definitions(path=str(path))

    assert trip == TagDefinition(
        name="summer-trip",
        description="A week by the sea",
        start=date(2023, 7, 1),
        end=date(2023, 7, 8),
        rules=({"account": "assets:bank"},),
    )
    assert trip.covers(day=date(2023, 7, 8))
    assert not trip.covers(day=date(2023, 7, 9))
    assert workbench == TagDefinition(name="workbench")
    assert not workbench.covers(day=date(2023, 7, 3))


def test_no_tags_file_means_no_definitions(tmp_path: Path) -> None:
    assert load_tag_definitions(path=str(tmp_path / "tags.yaml")) == []


@pytest.mark.parametrize(
    "content",
    [
        "traceable:\n",
        "- workbench\n",
        "workbench:\n  from: someday\n",
        "workbench:\n  rules: x\n",
    ],
)
def test_a_wrong_tags_file_is_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "tags.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError):
        load_tag_definitions(path=str(path))
