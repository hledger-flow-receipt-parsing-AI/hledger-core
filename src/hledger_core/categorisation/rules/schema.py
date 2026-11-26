"""Categorisation rules as data.

A rule says: for a bank transaction in this *direction* whose fields satisfy
every *match* condition and no *unless* group, the category (or own
account) is *target*.  Rules are evaluated all at once, never in order: a
transaction must satisfy exactly one rule (see ``audit.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Union

from typeguard import typechecked

# The parts of a bank transaction a condition can look at.  ``amount`` is
# the amount out of the account as Python prints the float ("42.17",
# "12.5"); ``date`` is "YYYY-MM-DD-HH-MM-SS".
TEXT_FIELDS: Tuple[str, ...] = ("payee", "description", "counter_account")
FIELDS: Tuple[str, ...] = TEXT_FIELDS + (
    "own_account",
    "amount",
    "date",
    "text",
)
TEXT_ANY = "text"  # any of the TEXT_FIELDS
OPS: Tuple[str, ...] = ("contains", "starts_with", "equals", "any_of")
DIRECTIONS: Tuple[str, ...] = ("debit", "credit")
ACCOUNT_PREFIX = "account:"
SOURCES: Tuple[str, ...] = ("converted", "tui", "ai-draft", "manual")


@typechecked
@dataclass(frozen=True)
class Condition:
    """One test on one field of a transaction."""

    field: str
    op: str
    value: Union[str, Tuple[str, ...]]
    case_sensitive: bool = False

    def __post_init__(self) -> None:
        if self.field not in FIELDS:
            raise ValueError(
                f"Unknown field {self.field!r}; one of {', '.join(FIELDS)}"
            )
        if self.op not in OPS:
            raise ValueError(
                f"Unknown op {self.op!r}; one of {', '.join(OPS)}"
            )
        if self.op == "any_of":
            if not isinstance(self.value, tuple) or not self.value:
                raise ValueError("any_of needs a non-empty list of values")
            if any(not v for v in self.value):
                raise ValueError("any_of values must not be empty")
        else:
            if not isinstance(self.value, str) or not self.value:
                raise ValueError(f"{self.op} needs a non-empty text value")

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "field": self.field,
            "op": self.op,
            "value": list(self.value) if self.op == "any_of" else self.value,
        }
        if self.case_sensitive:
            data["case_sensitive"] = True
        return data

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Condition":
        value = data["value"]
        if isinstance(value, list):
            value = tuple(str(v) for v in value)
        else:
            value = str(value)
        return Condition(
            field=str(data["field"]),
            op=str(data["op"]),
            value=value,
            case_sensitive=bool(data.get("case_sensitive", False)),
        )

    def describe(self) -> str:
        shown = (
            " | ".join(self.value)
            if isinstance(self.value, tuple)
            else self.value
        )
        case = " (case)" if self.case_sensitive else ""
        return f"{self.field} {self.op} {shown!r}{case}"


@typechecked
@dataclass(frozen=True)
class Rule:
    id: int
    direction: str
    match: Tuple[Condition, ...]
    target: str
    unless: Tuple[Tuple[Condition, ...], ...] = field(default_factory=tuple)
    source: str = "tui"
    note: str = ""
    created: str = ""

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise ValueError(
                f"Rule {self.id}: direction must be one of"
                f" {', '.join(DIRECTIONS)}, not {self.direction!r}"
            )
        if not self.match:
            raise ValueError(f"Rule {self.id}: needs at least one condition")
        if not self.target:
            raise ValueError(f"Rule {self.id}: needs a target")
        if any(not group for group in self.unless):
            raise ValueError(f"Rule {self.id}: an unless group is empty")

    @property
    def is_account_target(self) -> bool:
        return self.target.startswith(ACCOUNT_PREFIX)

    @property
    def account_string(self) -> str:
        """``holder:bank:type`` of an own-account target."""
        return self.target[len(ACCOUNT_PREFIX) :]

    @property
    def category_path(self) -> str:
        """The category of a category target (``a:b:c``)."""
        return self.target

    def result(self) -> str:
        """What the classifier returns: the category path or the account
        string, both as the journal rules expect them."""
        return self.account_string if self.is_account_target else self.target

    def with_unless(self, group: Tuple[Condition, ...]) -> "Rule":
        """This rule, no longer firing when *group* holds completely."""
        if group in self.unless:
            return self
        return Rule(
            id=self.id,
            direction=self.direction,
            match=self.match,
            target=self.target,
            unless=self.unless + (group,),
            source=self.source,
            note=self.note,
            created=self.created,
        )

    def with_id(self, new_id: int) -> "Rule":
        return Rule(
            id=new_id,
            direction=self.direction,
            match=self.match,
            target=self.target,
            unless=self.unless,
            source=self.source,
            note=self.note,
            created=self.created,
        )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "direction": self.direction,
            "match": [c.to_dict() for c in self.match],
        }
        if self.unless:
            data["unless"] = [[c.to_dict() for c in g] for g in self.unless]
        data["target"] = self.target
        data["source"] = self.source
        if self.note:
            data["note"] = self.note
        if self.created:
            data["created"] = self.created
        return data

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Rule":
        unless_raw: List[Any] = list(data.get("unless") or [])
        unless: List[Tuple[Condition, ...]] = []
        for group in unless_raw:
            if isinstance(group, dict):  # a single condition is a group
                group = [group]
            unless.append(tuple(Condition.from_dict(c) for c in group))
        return Rule(
            id=int(data["id"]),
            direction=str(data["direction"]),
            match=tuple(Condition.from_dict(c) for c in data["match"]),
            target=str(data["target"]),
            unless=tuple(unless),
            source=str(data.get("source", "manual")),
            note=str(data.get("note", "") or ""),
            created=str(data.get("created", "") or ""),
        )

    def describe(self) -> str:
        parts = [c.describe() for c in self.match]
        text = f"#{self.id} {self.direction}: " + " and ".join(parts)
        for group in self.unless:
            text += " unless " + " and ".join(c.describe() for c in group)
        return f"{text} -> {self.target}"
