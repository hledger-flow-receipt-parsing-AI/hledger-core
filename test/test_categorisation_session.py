"""Grouping uncategorised rows, drafting rules and the categorisation
session.  Invented data only."""

from pathlib import Path

import pytest

from hledger_core.categorisation.rules import (
    Condition,
    RowView,
    Rule,
    RuleStore,
    audit,
)
from hledger_core.categorisation.rules.drafting import (
    common_prefix,
    group_key,
    group_rows,
)
from hledger_core.categorisation.rules.session import (
    CategorisationSession,
    Draft,
)


def row(
    row_id: str,
    *,
    payee: str = "",
    description: str = "",
    counter_account: str = "",
    direction: str = "debit",
    amount: float = 10.0,
) -> RowView:
    return RowView(
        row_id=row_id,
        direction=direction,
        payee=payee,
        description=description,
        counter_account=counter_account,
        own_account="alex:examplebank:checking",
        amount=amount,
        date="2026-02-0" + row_id[-1] + "-00-00-00",
    )


ROWS = [
    row("a1", payee="Voorbeeld Supermarkt", description="pas 1"),
    row("a2", payee="VOORBEELD Supermarkt", description="pas 2"),
    row("a3", payee="Voorbeeld Supermarkt", description="pas 3"),
    row(
        "b1",
        description="SEPA Incasso Verzekering maart",
        counter_account="NL00X1",
    ),
    row(
        "b2",
        description="SEPA Incasso Verzekering april",
        counter_account="NL00X1",
    ),
    row("c1", counter_account="NL00Y2"),
    row(
        "d1",
        payee="Werkgever",
        description="salaris",
        direction="credit",
        amount=-100.0,
    ),
]


class TestGrouping:
    def test_payee_then_description_then_counter_account(self):
        assert group_key(ROWS[0]) == ("debit", "payee", "voorbeeld supermarkt")
        assert group_key(ROWS[1]) == ("debit", "payee", "voorbeeld supermarkt")
        assert group_key(ROWS[3]) == (
            "debit",
            "description",
            "sepa incasso verzekering",
        )
        assert group_key(ROWS[5]) == ("debit", "counter_account", "nl00y2")
        assert group_key(ROWS[6])[0] == "credit"

    def test_groups_are_largest_first(self):
        groups = group_rows(ROWS)
        assert [(g.field, g.n) for g in groups] == [
            ("payee", 3),
            ("description", 2),
            ("counter_account", 1),
            ("payee", 1),
        ]
        assert groups[0].label() == "Voorbeeld Supermarkt"
        assert groups[0].total == 30.0

    def test_a_payee_spelt_differently_is_its_own_group(self):
        groups = group_rows([ROWS[0], row("a9", payee="Voorbeeld  Supermarkt")])
        assert len(groups) == 2
        for group in groups:
            assert len(group_rows(group.rows)) == 1

    def test_common_prefix_keeps_whole_words(self):
        assert (
            common_prefix(
                [
                    "SEPA Incasso Verzekering maart",
                    "SEPA Incasso Verzekering april",
                ]
            )
            == "SEPA Incasso Verzekering"
        )
        assert (
            common_prefix(["Pas 12 winkel", "Pas 13 winkel"]) == ""
        )  # "Pas 1" cut back, too short
        assert common_prefix(["abc"]) == ""
        assert common_prefix(["Alleen dit", "Alleen dit"]) == "Alleen dit"

    def test_draft_conditions(self):
        groups = group_rows(ROWS)
        assert groups[0].draft_condition() == Condition(
            field="payee", op="contains", value="Voorbeeld Supermarkt"
        )
        assert groups[1].draft_condition() == Condition(
            field="description",
            op="contains",
            value="SEPA Incasso Verzekering",
        )
        assert groups[2].draft_condition() == Condition(
            field="counter_account",
            op="equals",
            value="NL00Y2",
            case_sensitive=True,
        )


class TestSession:
    def test_walks_the_groups_and_saves_rules(self, tmp_path: Path):
        store = RuleStore(path=str(tmp_path / "rules.yaml"))
        session = CategorisationSession(
            store=store,
            rows=ROWS,
            suggest=lambda g: [
                ("groceries:voorbeeld", 0.8),
                ("food:other", 0.1),
            ],
        )
        assert session.position() == (1, 4)
        assert session.remaining_rows == 7
        draft = session.draft()
        assert draft.target == "groceries:voorbeeld"
        assert draft.match[0].value == "Voorbeeld Supermarkt"
        report = session.probe(draft=draft)
        assert len(report.gained) == 3 and report.is_one_hot

        result = session.accept(draft=draft)
        assert result.ok and result.rule.id == 1 and result.rule.source == "tui"
        assert session.remaining_rows == 4
        assert session.position() == (1, 3)
        assert (tmp_path / "rules.yaml").exists()
        assert "rule(s) added" in session.summary()

    def test_skip_moves_the_group_to_the_end(self):
        session = CategorisationSession(store=RuleStore(), rows=ROWS)
        first = session.current.key
        session.skip()
        assert session.current.key != first
        assert session.groups[-1].key == first
        for _ in range(len(session.groups) - 1):
            session.next()
        assert session.current.key == first  # it comes round again

    def test_conflicting_draft_is_refused_unless_it_wins(self):
        broad = Rule(
            id=1,
            direction="debit",
            match=(Condition(field="text", op="contains", value="pas"),),
            target="shopping:misc",
        )
        store = RuleStore(rules=[broad])
        session = CategorisationSession(store=store, rows=ROWS)
        assert session.remaining_rows == 4  # the three "pas" rows are covered
        draft = Draft(
            direction="debit",
            match=[Condition(field="payee", op="contains", value="Voorbeeld")],
            target="groceries:voorbeeld",
        )
        refused = session.accept(draft=draft)
        assert not refused.ok
        assert [r.id for r in refused.probe.conflicting_rules()] == [1]
        assert len(store) == 1

        won = session.accept(draft=draft, win=True)
        assert won.ok and [r.id for r in won.narrowed] == [1]
        assert store.get(rule_id=1).unless == ((draft.match[0],),)
        report = audit(store=store, rows=ROWS)
        assert report.conflicts == [] and report.categorised == 3
        assert session.narrowed and session.summary().startswith(
            "1 rule(s) added, 1 rule(s) narrowed"
        )

    def test_a_yielding_draft_leaves_the_conflicting_rules_their_rows(self):
        specific = Rule(
            id=1,
            direction="debit",
            match=(
                Condition(
                    field="payee", op="contains", value="Voorbeeld Supermarkt"
                ),
            ),
            target="groceries:voorbeeld",
        )
        store = RuleStore(rules=[specific])
        session = CategorisationSession(
            store=store,
            rows=ROWS
            + [row("e1", payee="Voorbeeld Bakkerij", description="brood")],
        )
        broad = Draft(
            direction="debit",
            match=[Condition(field="payee", op="contains", value="Voorbeeld")],
            target="food:bakery",
        )
        assert not session.accept(draft=broad).ok
        yielding = session.yielded(draft=broad)
        assert yielding.unless == [specific.match]
        result = session.accept(draft=yielding)
        assert result.ok and result.narrowed == ()
        assert store.get(rule_id=1).unless == ()
        report = audit(store=store, rows=session.rows)
        assert report.conflicts == []
        assert session.remaining_rows == 4

    def test_draft_without_category_cannot_be_accepted(self):
        session = CategorisationSession(store=RuleStore(), rows=ROWS)
        with pytest.raises(ValueError):
            session.accept(draft=session.draft())

    def test_done_when_everything_is_covered(self):
        rules = [
            Rule(
                id=1,
                direction="debit",
                match=(
                    Condition(field="text", op="contains", value="voorbeeld"),
                ),
                target="a:b",
            ),
            Rule(
                id=2,
                direction="debit",
                match=(
                    Condition(field="text", op="contains", value="verzekering"),
                ),
                target="a:c",
            ),
            Rule(
                id=3,
                direction="debit",
                match=(
                    Condition(
                        field="counter_account", op="equals", value="NL00Y2"
                    ),
                ),
                target="a:d",
            ),
            Rule(
                id=4,
                direction="credit",
                match=(
                    Condition(field="text", op="contains", value="salaris"),
                ),
                target="i:s",
            ),
        ]
        session = CategorisationSession(store=RuleStore(rules=rules), rows=ROWS)
        assert (
            session.done
            and session.current is None
            and session.position() == (0, 0)
        )
