"""One sitting of categorising: the groups still uncategorised, the draft
for the current group, probing a draft and saving it as a rule.  The screen
(tui-image-labeller) only renders this and forwards keys."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from typeguard import typechecked

from hledger_core.categorisation.rules.audit import (
    ProbeReport,
    Verdict,
    audit,
    narrowed_for,
    probe,
)
from hledger_core.categorisation.rules.drafting import Group, group_rows
from hledger_core.categorisation.rules.matching import RowView
from hledger_core.categorisation.rules.schema import Condition, Rule
from hledger_core.categorisation.rules.store import RuleStore

Suggestion = Tuple[str, float]  # category path, confidence 0..1
Suggester = Callable[[Group], List[Suggestion]]
PROBE_TARGET = "?"  # a draft is probed before it has a category


@typechecked
@dataclass
class Draft:
    direction: str
    match: List[Condition]
    unless: List[Tuple[Condition, ...]] = field(default_factory=list)
    target: str = ""

    def rule(self, *, rule_id: int = 0, source: str = "tui") -> Rule:
        return Rule(
            id=rule_id,
            direction=self.direction,
            match=tuple(self.match),
            unless=tuple(self.unless),
            target=self.target or PROBE_TARGET,
            source=source,
        )


@typechecked
@dataclass(frozen=True)
class AcceptResult:
    rule: Optional[Rule]  # the stored rule, None when refused
    probe: ProbeReport
    narrowed: Tuple[Rule, ...] = ()  # rules narrowed so the draft wins

    @property
    def ok(self) -> bool:
        return self.rule is not None


@typechecked
class CategorisationSession:
    def __init__(
        self,
        *,
        store: RuleStore,
        rows: Sequence[RowView],
        suggest: Optional[Suggester] = None,
        on_save: Optional[Callable[[RuleStore], None]] = None,
    ) -> None:
        self.store = store
        self.rows: Tuple[RowView, ...] = tuple(rows)
        self._suggest = suggest
        self._on_save = on_save
        self._suggestions: Dict[Tuple[str, str, str], List[Suggestion]] = {}
        self.skipped: Set[Tuple[str, str, str]] = set()
        self.added: List[Rule] = []
        self.narrowed: List[Rule] = []
        self.uncategorised: List[RowView] = []
        self.conflicts: List[Verdict] = []
        self.groups: List[Group] = []
        self.index: int = 0
        self._rebuild()

    # ------------------------------------------------------------ state
    def _rebuild(self) -> None:
        report = audit(store=self.store, rows=self.rows)
        self.uncategorised = report.uncategorised
        self.conflicts = report.conflicts
        groups = group_rows(self.uncategorised)
        fresh = [g for g in groups if self._key(g) not in self.skipped]
        self.groups = fresh + [
            g for g in groups if self._key(g) in self.skipped
        ]
        self.index = min(self.index, max(len(self.groups) - 1, 0))

    @staticmethod
    def _key(group: Group) -> Tuple[str, str, str]:
        return (group.direction, group.field, group.key)

    @property
    def current(self) -> Optional[Group]:
        if not self.groups:
            return None
        return self.groups[self.index]

    @property
    def remaining_rows(self) -> int:
        return len(self.uncategorised)

    @property
    def done(self) -> bool:
        return not self.groups

    def position(self) -> Tuple[int, int]:
        """(1-based index of the current group, number of groups)."""
        return (self.index + 1 if self.groups else 0, len(self.groups))

    # ------------------------------------------------------- navigation
    def skip(self) -> None:
        group = self.current
        if group is None:
            return
        self.skipped.add(self._key(group))
        self._rebuild()  # the group moves to the end; the next one is up

    def next(self) -> None:
        if self.groups:
            self.index = (self.index + 1) % len(self.groups)

    def previous(self) -> None:
        if self.groups:
            self.index = (self.index - 1) % len(self.groups)

    # ----------------------------------------------------------- drafts
    def suggestions(self, *, group: Group) -> List[Suggestion]:
        key = self._key(group)
        if key not in self._suggestions:
            self._suggestions[key] = (
                list(self._suggest(group)) if self._suggest is not None else []
            )
        return self._suggestions[key]

    def draft(self, *, group: Optional[Group] = None) -> Draft:
        """The draft for *group* (default: the current one): its condition
        and the best suggestion as the category."""
        group = group or self.current
        if group is None:
            raise ValueError("Nothing left to categorise")
        suggestions = self.suggestions(group=group)
        return Draft(
            direction=group.direction,
            match=[group.draft_condition()],
            target=suggestions[0][0] if suggestions else "",
        )

    def probe(self, *, draft: Draft) -> ProbeReport:
        return probe(store=self.store, draft=draft.rule(), rows=self.rows)

    def yielded(self, *, draft: Draft) -> Draft:
        """*draft* with an ``unless`` group per rule it conflicts with, so
        those rules keep their rows and the draft takes the rest (the
        opposite of making the draft win)."""
        report = self.probe(draft=draft)
        unless = list(draft.unless)
        for rule in report.conflicting_rules():
            if rule.match not in unless:
                unless.append(rule.match)
        return Draft(
            direction=draft.direction,
            match=list(draft.match),
            unless=unless,
            target=draft.target,
        )

    def accept(
        self, *, draft: Draft, win: bool = False, source: str = "tui"
    ) -> AcceptResult:
        """Save *draft* as a rule unless it conflicts with a rule on some
        row.  With *win*, the conflicting rules are narrowed first (an
        ``unless`` group equal to the draft's conditions), so the draft is
        the only rule on those rows."""
        if not draft.target or draft.target == PROBE_TARGET:
            raise ValueError("The draft has no category")
        report = self.probe(draft=draft)
        narrowed: Tuple[Rule, ...] = ()
        if report.conflicts:
            if not win:
                return AcceptResult(rule=None, probe=report)
            narrowed = tuple(
                narrowed_for(
                    draft=draft.rule(), rules=report.conflicting_rules()
                )
            )
            for rule in narrowed:
                self.store.replace(rule=rule)
        stored = self.store.add(rule=draft.rule(source=source))
        self._save()
        self.added.append(stored)
        self.narrowed += list(narrowed)
        self._rebuild()
        return AcceptResult(rule=stored, probe=report, narrowed=narrowed)

    def _save(self) -> None:
        if self._on_save is not None:
            self._on_save(self.store)
        elif self.store.path is not None:
            self.store.save()

    def summary(self) -> str:
        return (
            f"{len(self.added)} rule(s) added, {len(self.narrowed)} rule(s)"
            f" narrowed, {self.remaining_rows} transaction(s) still"
            f" uncategorised in {len(self.groups)} group(s)"
        )
