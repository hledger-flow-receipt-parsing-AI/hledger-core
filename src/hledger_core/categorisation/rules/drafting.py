"""From uncategorised rows to draft rules.

Rows are grouped by what they have in common (the payee, else the start of
the description, else the counter account): one rule per group covers many
rows.  A group's draft condition is the group key as a ``contains``; the
category comes from the user or from a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from typeguard import typechecked

from hledger_core.categorisation.rules.matching import RowView
from hledger_core.categorisation.rules.schema import Condition

MIN_PREFIX = 4
HEAD_WORDS = 3


@typechecked
def normalise(text: str) -> str:
    """The grouping key of a text: its exact spelling, without case and
    outer whitespace, so a ``contains`` on the spelling covers the group."""
    return text.strip().lower()


@typechecked
def head(text: str, *, words: int = HEAD_WORDS) -> str:
    """The first *words* words of *text*, spacing kept as it is."""
    found = list(re.finditer(r"\S+", text))
    if not found:
        return ""
    return text[found[0].start() : found[min(words, len(found)) - 1].end()]


@typechecked
def common_prefix(texts: Sequence[str]) -> str:
    """The longest start all *texts* share (compared without case), cut
    back to a word boundary; '' when shorter than MIN_PREFIX."""
    cleaned = [t.strip() for t in texts if t.strip()]
    if not cleaned:
        return ""
    first = cleaned[0]
    length = len(first)
    for other in cleaned[1:]:
        length = min(length, len(other))
        for index in range(length):
            if first[index].lower() != other[index].lower():
                length = index
                break
    prefix = first[:length]
    if length < len(first) and length > 0 and not prefix[-1].isspace():
        # Do not cut a word in two: keep whole words only.
        if " " in prefix:
            prefix = prefix[: prefix.rfind(" ")]
        else:
            prefix = ""
    prefix = prefix.strip()
    return prefix if len(prefix) >= MIN_PREFIX else ""


@typechecked
def group_key(row: RowView) -> Tuple[str, str, str]:
    """(direction, field, key) of the group a row belongs to."""
    if normalise(row.payee):
        return (row.direction, "payee", normalise(row.payee))
    if normalise(row.description):
        return (row.direction, "description", normalise(head(row.description)))
    if normalise(row.counter_account):
        return (
            row.direction,
            "counter_account",
            normalise(row.counter_account),
        )
    return (row.direction, "amount", row.amount_text)


@typechecked
@dataclass(frozen=True)
class Group:
    direction: str
    field: str
    key: str
    rows: Tuple[RowView, ...]

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def total(self) -> float:
        return sum(row.amount for row in self.rows)

    def label(self) -> str:
        """The key as the rows spell it."""
        first = self.rows[0]
        if self.field == "payee":
            return first.payee.strip()
        if self.field == "description":
            return head(first.description)
        if self.field == "counter_account":
            return first.counter_account.strip()
        return first.amount_text

    def draft_condition(self) -> Condition:
        """The condition that covers this group (and perhaps more)."""
        if self.field == "payee":
            return Condition(field="payee", op="contains", value=self.label())
        if self.field == "description":
            prefix = common_prefix([row.description for row in self.rows])
            return Condition(
                field="description",
                op="contains",
                value=prefix or self.label(),
            )
        if self.field == "counter_account":
            return Condition(
                field="counter_account",
                op="equals",
                value=self.label(),
                case_sensitive=True,
            )
        return Condition(field="amount", op="equals", value=self.label())


@typechecked
def group_rows(rows: Sequence[RowView]) -> List[Group]:
    """Groups of *rows*, largest first."""
    buckets: Dict[Tuple[str, str, str], List[RowView]] = {}
    for row in rows:
        buckets.setdefault(group_key(row), []).append(row)
    groups = [
        Group(direction=d, field=f, key=k, rows=tuple(members))
        for (d, f, k), members in buckets.items()
    ]
    # Largest first; expenses (debit) before income at equal size.
    return sorted(
        groups,
        key=lambda g: (-g.n, g.direction != "debit", g.field, g.key),
    )
