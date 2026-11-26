"""Tags on receipts and transactions: events and projects.

A tag names something that costs money across categories: a holiday
("seaside-trip") or a project ("workbench").  Receipts get them while
they are labelled; the journal carries them as hledger tags without a
value ("; workbench:, seaside-trip:"), so ``hledger bal tag:workbench`` shows
what a project cost, and the dashboard shows the cost of every tag.

Two words are reserved: "traceable" and "untraceable" say whether others
(a bank, a card issuer, an insurer that asks for the statements) can see
a receipt's payments.  In the journal they become the tag traceable:yes
or traceable:no.

The finance root may describe its tags in tags.yaml (all keys optional):

    seaside-trip:
      description: A week by the sea
      from: 2022-05-15        # the labeller offers the tag first for
      to: 2022-05-23          # receipts of these days
      rules:                  # the dashboard also tags transactions that
        - account: assets:sam:examplebank   # match a rule (all keys given)
          from: 2022-05-15
          to: 2022-05-23
    workbench:
      description: Wood and screws for the workbench
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml
from typeguard import typechecked

TAGS_FILENAME = "tags.yaml"
TRACEABLE = "traceable"
UNTRACEABLE = "untraceable"
# The journal tag that carries a transaction's own traceability.
TRACEABILITY_TAG = "traceable"
RESERVED = (TRACEABLE, UNTRACEABLE)

_NOT_IN_A_TAG = re.compile(r"[^\w-]+")


@typechecked
def normalize_tag(*, text: str) -> str:
    """The tag *text* stands for: lower case, words joined by "-", only
    letters, digits, "-" and "_" (a comma or colon would end an hledger
    tag)."""
    words = _NOT_IN_A_TAG.split(text.strip().lower())
    return "-".join(word for word in words if word).strip("-")


@typechecked
def parse_tags(*, text: str) -> List[str]:
    """The tags in *text* ("workbench, Seaside trip"), normalized, each
    once, in the order given."""
    tags: List[str] = []
    for part in text.split(","):
        tag = normalize_tag(text=part)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


@typechecked
def user_tags(*, tags: Iterable[str]) -> List[str]:
    """*tags* without the reserved traceability words."""
    return [tag for tag in tags if tag not in RESERVED]


@typechecked
def stated_traceability(*, tags: Iterable[str]) -> Optional[bool]:
    """True or False when *tags* say "traceable" or "untraceable" (the last
    one said wins), else None."""
    stated: Optional[bool] = None
    for tag in tags:
        if tag == TRACEABLE:
            stated = True
        elif tag == UNTRACEABLE:
            stated = False
    return stated


@typechecked
def journal_comment(*, tags: Iterable[str], traceable: Optional[bool]) -> str:
    """The comment that carries *tags* (and *traceable*) into the journal:
    "workbench:, seaside-trip:, traceable:yes"."""
    parts = [f"{tag}:" for tag in user_tags(tags=tags)]
    if traceable is not None:
        parts.append(f"{TRACEABILITY_TAG}:{'yes' if traceable else 'no'}")
    return ", ".join(parts)


@typechecked
@dataclass(frozen=True)
class TagDefinition:
    """One tag of tags.yaml."""

    name: str
    description: str = ""
    start: Optional[date] = None
    end: Optional[date] = None
    # Raw rules for the dashboard (hledger_plot.views); kept as written.
    rules: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)

    def covers(self, *, day: date) -> bool:
        """Whether *day* lies in the tag's period (a tag without a period
        covers no day)."""
        if self.start is None and self.end is None:
            return False
        if self.start is not None and day < self.start:
            return False
        if self.end is not None and day > self.end:
            return False
        return True

    def period_text(self) -> str:
        if self.start is None and self.end is None:
            return ""
        start = self.start.isoformat() if self.start else "..."
        end = self.end.isoformat() if self.end else "..."
        return f"{start} to {end}"


@typechecked
def as_date(*, value: Any, what: str) -> Optional[date]:
    """A date from tags.yaml (YAML reads 2022-05-15 as a date already)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as error:
        raise ValueError(f"{what}: not a date (YYYY-MM-DD): {value}") from error


@typechecked
def tags_file_path(*, root_finance_path: str) -> str:
    return os.path.join(root_finance_path, TAGS_FILENAME)


@typechecked
def load_tag_definitions(*, path: str) -> List[TagDefinition]:
    """The tags described in *path*; none when the file does not exist."""
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as handle:
        content = yaml.safe_load(handle) or {}
    if not isinstance(content, dict):
        raise ValueError(f"{path}: expected tag names with their details")
    definitions: List[TagDefinition] = []
    for raw_name, details in content.items():
        name = normalize_tag(text=str(raw_name))
        if not name or name in RESERVED:
            raise ValueError(f"{path}: {raw_name!r} cannot be a tag name")
        details = details or {}
        if not isinstance(details, dict):
            raise ValueError(f"{path}: {raw_name}: expected its details")
        rules = details.get("rules") or []
        if not isinstance(rules, list) or not all(
            isinstance(rule, dict) for rule in rules
        ):
            raise ValueError(f"{path}: {raw_name}: rules must be a list")
        definitions.append(
            TagDefinition(
                name=name,
                description=str(details.get("description") or ""),
                start=as_date(
                    value=details.get("from"), what=f"{path}: {raw_name}"
                ),
                end=as_date(
                    value=details.get("to"), what=f"{path}: {raw_name}"
                ),
                rules=tuple(rules),
            )
        )
    return definitions
