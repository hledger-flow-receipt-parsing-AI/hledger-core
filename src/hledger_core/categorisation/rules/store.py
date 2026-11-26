"""The rules file: ``categorisation_rules.yaml`` in the finance root."""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import yaml
from typeguard import typechecked

from hledger_core.categorisation.rules.schema import Rule

FORMAT_VERSION = 1
HEADER = (
    "# Categorisation rules of this finance root.  Every bank transaction\n"
    "# must satisfy exactly one rule; the order of the rules never matters.\n"
    "# Add rules with: hledger_preprocessor --categorise-transactions\n"
)


class RuleStoreError(ValueError):
    """The rules file cannot be used as it is."""


@typechecked
class RuleStore:
    def __init__(
        self, *, rules: Sequence[Rule] = (), path: Optional[str] = None
    ) -> None:
        self.path = path
        self._rules: List[Rule] = []
        for rule in rules:
            self._append(rule)

    # ----------------------------------------------------------- reading
    @staticmethod
    def load(*, path: str) -> "RuleStore":
        """The store at *path*; a missing file is an empty store."""
        if not os.path.isfile(path):
            return RuleStore(path=path)
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise RuleStoreError(f"{path}: expected a mapping at the top")
        version = data.get("version", FORMAT_VERSION)
        if version != FORMAT_VERSION:
            raise RuleStoreError(f"{path}: unknown format version {version}")
        rules: List[Rule] = []
        for index, raw in enumerate(data.get("rules") or []):
            try:
                rules.append(Rule.from_dict(raw))
            except (KeyError, ValueError, TypeError) as error:
                raise RuleStoreError(
                    f"{path}: rule {index + 1} is invalid: {error}"
                ) from error
        return RuleStore(rules=rules, path=path)

    @property
    def rules(self) -> Tuple[Rule, ...]:
        return tuple(self._rules)

    def __len__(self) -> int:
        return len(self._rules)

    def get(self, *, rule_id: int) -> Optional[Rule]:
        for rule in self._rules:
            if rule.id == rule_id:
                return rule
        return None

    def next_id(self) -> int:
        return max((r.id for r in self._rules), default=0) + 1

    def targets(self) -> Set[str]:
        return {rule.target for rule in self._rules}

    # ----------------------------------------------------------- writing
    def _append(self, rule: Rule) -> None:
        if self.get(rule_id=rule.id) is not None:
            raise RuleStoreError(f"Duplicate rule id {rule.id}")
        self._rules.append(rule)

    def add(self, *, rule: Rule) -> Rule:
        """Add *rule*; an id of 0 means "the next free one".  Returns the
        rule as stored."""
        stored = rule
        if rule.id <= 0:
            stored = rule.with_id(self.next_id())
        if not stored.created:
            stored = Rule(
                id=stored.id,
                direction=stored.direction,
                match=stored.match,
                target=stored.target,
                unless=stored.unless,
                source=stored.source,
                note=stored.note,
                created=date.today().isoformat(),
            )
        self._append(stored)
        return stored

    def replace(self, *, rule: Rule) -> None:
        for index, existing in enumerate(self._rules):
            if existing.id == rule.id:
                self._rules[index] = rule
                return
        raise RuleStoreError(f"No rule with id {rule.id} to replace")

    def remove(self, *, rule_id: int) -> None:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.id != rule_id]
        if len(self._rules) == before:
            raise RuleStoreError(f"No rule with id {rule_id} to remove")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "rules": [rule.to_dict() for rule in self._rules],
        }

    def dumps(self) -> str:
        return HEADER + yaml.safe_dump(
            self.to_dict(),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=None,
            width=100,
        )

    def save(self, *, path: Optional[str] = None) -> str:
        """Write the file (atomically) and return its path."""
        target = path or self.path
        if target is None:
            raise RuleStoreError("The store has no path to save to")
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        tmp = f"{target}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(self.dumps())
        os.replace(tmp, target)
        self.path = target
        return target
