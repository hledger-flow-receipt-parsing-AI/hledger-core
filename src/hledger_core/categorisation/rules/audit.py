"""One-hot is a property of the data: every row must satisfy exactly one
rule.  ``verdict`` says how many rules a row satisfies, ``audit`` checks a
whole root, ``probe`` tells what a draft rule would do before it is saved,
and ``narrowed_for`` makes a draft win over the rules it conflicts with."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from typeguard import typechecked

from hledger_core.categorisation.rules.matching import RowView, rule_matches
from hledger_core.categorisation.rules.schema import Rule
from hledger_core.categorisation.rules.store import RuleStore


@typechecked
@dataclass(frozen=True)
class Verdict:
    row: RowView
    matches: Tuple[Rule, ...]

    @property
    def is_categorised(self) -> bool:
        return len(self.matches) == 1

    @property
    def is_uncategorised(self) -> bool:
        return not self.matches

    @property
    def is_conflict(self) -> bool:
        return len(self.matches) > 1

    @property
    def result(self) -> str:
        if not self.is_categorised:
            raise ValueError("Only a row with exactly one rule has a result")
        return self.matches[0].result()


@typechecked
def matching_rules(*, store: RuleStore, row: RowView) -> Tuple[Rule, ...]:
    return tuple(r for r in store.rules if rule_matches(rule=r, row=row))


@typechecked
def verdict(*, store: RuleStore, row: RowView) -> Verdict:
    return Verdict(row=row, matches=matching_rules(store=store, row=row))


@typechecked
@dataclass
class AuditReport:
    categorised: int = 0
    uncategorised: List[RowView] = field(default_factory=list)
    conflicts: List[Verdict] = field(default_factory=list)

    @property
    def is_one_hot(self) -> bool:
        return not self.uncategorised and not self.conflicts

    def summary(self) -> str:
        return (
            f"{self.categorised} categorised, {len(self.uncategorised)}"
            f" uncategorised, {len(self.conflicts)} with several rules"
        )


@typechecked
def audit(*, store: RuleStore, rows: Sequence[RowView]) -> AuditReport:
    report = AuditReport()
    for row in rows:
        result = verdict(store=store, row=row)
        if result.is_categorised:
            report.categorised += 1
        elif result.is_uncategorised:
            report.uncategorised.append(row)
        else:
            report.conflicts.append(result)
    return report


@typechecked
@dataclass(frozen=True)
class ProbeReport:
    """What a draft would do to the rows of the root."""

    draft: Rule
    matched: Tuple[RowView, ...]  # every row the draft matches
    gained: Tuple[RowView, ...]  # matched rows no rule covered before
    # matched rows another rule covers: that is a conflict
    conflicts: Tuple[Tuple[RowView, Tuple[Rule, ...]], ...]

    @property
    def is_one_hot(self) -> bool:
        return not self.conflicts

    def conflicting_rules(self) -> List[Rule]:
        seen: Dict[int, Rule] = {}
        for _row, rules in self.conflicts:
            for rule in rules:
                seen.setdefault(rule.id, rule)
        return list(seen.values())


@typechecked
def probe(
    *, store: RuleStore, draft: Rule, rows: Sequence[RowView]
) -> ProbeReport:
    """Try *draft* on *rows* against the rules already in *store*.  A rule
    in the store with the draft's id is left out (the draft replaces it)."""
    matched: List[RowView] = []
    gained: List[RowView] = []
    conflicts: List[Tuple[RowView, Tuple[Rule, ...]]] = []
    for row in rows:
        if not rule_matches(rule=draft, row=row):
            continue
        matched.append(row)
        others = tuple(
            r for r in matching_rules(store=store, row=row) if r.id != draft.id
        )
        if others:
            conflicts.append((row, others))
        else:
            gained.append(row)
    return ProbeReport(
        draft=draft,
        matched=tuple(matched),
        gained=tuple(gained),
        conflicts=tuple(conflicts),
    )


@typechecked
def narrowed_for(*, draft: Rule, rules: Sequence[Rule]) -> List[Rule]:
    """*rules* with an ``unless`` group equal to the draft's conditions: on
    rows the draft matches they no longer fire, so the draft wins there and
    nowhere else."""
    return [rule.with_unless(draft.match) for rule in rules]
