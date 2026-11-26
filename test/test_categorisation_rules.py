"""The rule store: matching, one-hot audit, probing a draft, YAML round
trip.  Every payee, description and category here is invented."""

from datetime import datetime
from pathlib import Path

import pytest

from hledger_core.categorisation.rules import (
    Condition,
    RowView,
    Rule,
    RuleStore,
    RuleStoreError,
    audit,
    condition_holds,
    narrowed_for,
    probe,
    rule_matches,
    verdict,
)
from hledger_core.Currency import Currency
from hledger_core.generics.GenericTransactionWithCsv import (
    GenericCsvTransaction,
)
from hledger_core.TransactionObjects.Account import Account
from hledger_core.TransactionObjects.Posting import TransactionCode


def row(
    *,
    row_id: str = "r1",
    direction: str = "debit",
    payee: str = "Voorbeeld Supermarkt",
    description: str = "Pas 123 Transactie 42",
    counter_account: str = "NL00VBLD0000000001",
    own_account: str = "alex:examplebank:checking",
    amount: float = 12.5,
    date: str = "2026-03-04-10-00-00",
) -> RowView:
    return RowView(
        row_id=row_id,
        direction=direction,
        payee=payee,
        description=description,
        counter_account=counter_account,
        own_account=own_account,
        amount=amount,
        date=date,
    )


def rule(
    rule_id: int = 1,
    *,
    direction: str = "debit",
    conditions=(("text", "contains", "voorbeeld"),),
    target: str = "groceries:voorbeeld",
    unless=(),
) -> Rule:
    return Rule(
        id=rule_id,
        direction=direction,
        match=tuple(
            Condition(field=f, op=o, value=v) for f, o, v in conditions
        ),
        target=target,
        unless=tuple(
            tuple(Condition(field=f, op=o, value=v) for f, o, v in group)
            for group in unless
        ),
    )


# ------------------------------------------------------------ conditions
class TestConditions:
    def test_contains_is_case_insensitive_by_default(self):
        c = Condition(field="payee", op="contains", value="VOORBEELD")
        assert condition_holds(condition=c, row=row())

    def test_contains_can_be_case_sensitive(self):
        c = Condition(
            field="payee",
            op="contains",
            value="VOORBEELD",
            case_sensitive=True,
        )
        assert not condition_holds(condition=c, row=row())

    def test_text_looks_at_payee_description_and_counter_account(self):
        c = Condition(field="text", op="contains", value="nl00vbld")
        assert condition_holds(condition=c, row=row())
        c = Condition(field="payee", op="contains", value="nl00vbld")
        assert not condition_holds(condition=c, row=row())

    def test_starts_with_and_equals(self):
        assert condition_holds(
            condition=Condition(
                field="description", op="starts_with", value="pas 1"
            ),
            row=row(),
        )
        assert not condition_holds(
            condition=Condition(
                field="description", op="starts_with", value="123"
            ),
            row=row(),
        )
        assert condition_holds(
            condition=Condition(
                field="own_account",
                op="equals",
                value="alex:examplebank:checking",
            ),
            row=row(),
        )

    def test_amount_and_date_fields(self):
        assert condition_holds(
            condition=Condition(field="amount", op="equals", value="12.5"),
            row=row(),
        )
        assert condition_holds(
            condition=Condition(field="amount", op="contains", value="2.5"),
            row=row(amount=42.5),
        )
        assert condition_holds(
            condition=Condition(
                field="date", op="starts_with", value="2026-03"
            ),
            row=row(),
        )
        assert not condition_holds(
            condition=Condition(field="text", op="contains", value="12.5"),
            row=row(),
        )

    def test_any_of(self):
        c = Condition(
            field="text", op="any_of", value=("nothing", "transactie 42")
        )
        assert condition_holds(condition=c, row=row())
        c = Condition(field="text", op="any_of", value=("nothing", "nope"))
        assert not condition_holds(condition=c, row=row())

    def test_invalid_conditions_are_refused(self):
        with pytest.raises(ValueError):
            Condition(field="balance", op="contains", value="1")
        with pytest.raises(ValueError):
            Condition(field="payee", op="matches", value="x")
        with pytest.raises(ValueError):
            Condition(field="payee", op="contains", value="")
        with pytest.raises(ValueError):
            Condition(field="payee", op="any_of", value=())


# ------------------------------------------------------------------ rules
class TestRuleMatching:
    def test_direction_must_match(self):
        assert rule_matches(rule=rule(), row=row())
        assert not rule_matches(rule=rule(), row=row(direction="credit"))

    def test_every_condition_must_hold(self):
        r = rule(
            conditions=(
                ("payee", "contains", "voorbeeld"),
                ("description", "contains", "pas"),
            )
        )
        assert rule_matches(rule=r, row=row())
        assert not rule_matches(rule=r, row=row(description="iets anders"))

    def test_unless_group_blocks_only_when_complete(self):
        r = rule(
            unless=(
                (
                    ("description", "contains", "pas"),
                    ("description", "contains", "transactie"),
                ),
            )
        )
        assert not rule_matches(rule=r, row=row())
        assert rule_matches(rule=r, row=row(description="Pas 123 only"))

    def test_account_target_result(self):
        r = rule(target="account:alex:examplebank:savings")
        assert r.is_account_target
        assert r.result() == "alex:examplebank:savings"
        assert rule().result() == "groceries:voorbeeld"

    def test_rule_needs_direction_conditions_and_target(self):
        with pytest.raises(ValueError):
            rule(direction="both")
        with pytest.raises(ValueError):
            Rule(id=1, direction="debit", match=(), target="x")
        with pytest.raises(ValueError):
            rule(target="")


# ------------------------------------------------------------ row views
class TestRowView:
    def test_from_generic_csv_transaction(self):
        txn = GenericCsvTransaction(
            account=Account(
                base_currency=Currency.EUR,
                account_holder="alex",
                bank="examplebank",
                account_type="checking",
            ),
            the_date=datetime(2026, 3, 4, 10, 0),
            tendered_amount_out=12.5,
            change_returned=0.0,
            description="Pas 123",
            other_party_name="Voorbeeld Supermarkt",
            other_party_account_name="NL00VBLD0000000001",
            transaction_code=TransactionCode.DEBIT,
            extra={"nr_in_batch": 7},
        )
        view = RowView.from_transaction(txn)
        assert view.row_id == "alex:examplebank:checking#7"
        assert view.direction == "debit"
        assert view.payee == "Voorbeeld Supermarkt"
        assert view.counter_account == "NL00VBLD0000000001"
        assert view.date == "2026-03-04-10-00-00"
        assert view.day == "2026-03-04"
        assert view.amount_text == "12.5"
        assert view.amount == 12.5

    def test_direction_from_amount_sign_without_code(self):
        txn = GenericCsvTransaction(
            account=Account(
                base_currency=Currency.EUR,
                account_holder="alex",
                bank="examplebank",
                account_type="checking",
            ),
            the_date=datetime(2026, 3, 4),
            tendered_amount_out=-30.0,
            change_returned=0.0,
            description="salaris",
        )
        assert RowView.from_transaction(txn).direction == "credit"

    def test_one_line_is_bounded(self):
        line = row(description="x" * 200).one_line(width=60)
        assert len(line) <= 60
        assert line.startswith("2026-03-04")


# --------------------------------------------------------- audit & probe
class TestAudit:
    def test_exactly_one_rule_per_row(self):
        store = RuleStore(
            rules=[
                rule(1),
                rule(
                    2,
                    conditions=(("payee", "contains", "bakker"),),
                    target="food:bakery",
                ),
            ]
        )
        rows = [
            row(row_id="a"),
            row(row_id="b", payee="Bakker Jansen", description="brood"),
            row(row_id="c", payee="Onbekend", description="?"),
        ]
        report = audit(store=store, rows=rows)
        assert report.categorised == 2
        assert [r.row_id for r in report.uncategorised] == ["c"]
        assert report.conflicts == []
        assert not report.is_one_hot

    def test_two_matching_rules_is_a_conflict_even_with_the_same_target(self):
        store = RuleStore(
            rules=[
                rule(1),
                rule(2, conditions=(("description", "contains", "pas"),)),
            ]
        )
        report = audit(store=store, rows=[row()])
        assert len(report.conflicts) == 1
        assert [r.id for r in report.conflicts[0].matches] == [1, 2]
        with pytest.raises(ValueError):
            report.conflicts[0].result

    def test_order_of_rules_does_not_matter(self):
        a, b = rule(1), rule(
            2,
            conditions=(("payee", "contains", "bakker"),),
            target="food:bakery",
        )
        rows = [row(row_id="a"), row(row_id="b", payee="Bakker Jansen")]
        first = [
            verdict(store=RuleStore(rules=[a, b]), row=r).result for r in rows
        ]
        second = [
            verdict(store=RuleStore(rules=[b, a]), row=r).result for r in rows
        ]
        assert first == second == ["groceries:voorbeeld", "food:bakery"]

    def test_probe_reports_gains_and_conflicts(self):
        store = RuleStore(
            rules=[
                rule(
                    1,
                    conditions=(("payee", "contains", "bakker"),),
                    target="food:bakery",
                )
            ]
        )
        rows = [
            row(row_id="a"),
            row(
                row_id="b",
                payee="Bakker Jansen",
                description="voorbeeld brood",
            ),
        ]
        draft = rule(0, conditions=(("text", "contains", "voorbeeld"),))
        report = probe(store=store, draft=draft, rows=rows)
        assert [r.row_id for r in report.matched] == ["a", "b"]
        assert [r.row_id for r in report.gained] == ["a"]
        assert [
            (r.row_id, [x.id for x in rules]) for r, rules in report.conflicts
        ] == [("b", [1])]
        assert not report.is_one_hot
        assert [r.id for r in report.conflicting_rules()] == [1]

    def test_narrowing_the_conflicting_rules_makes_the_draft_win(self):
        broad = rule(
            1,
            conditions=(("payee", "contains", "bakker"),),
            target="food:bakery",
        )
        store = RuleStore(rules=[broad])
        rows = [
            row(
                row_id="b",
                payee="Bakker Jansen",
                description="voorbeeld brood",
            ),
            row(row_id="c", payee="Bakker Jansen", description="taart"),
        ]
        draft = rule(
            0,
            conditions=(("description", "contains", "voorbeeld"),),
            target="groceries:voorbeeld",
        )
        for narrowed in narrowed_for(
            draft=draft,
            rules=probe(
                store=store, draft=draft, rows=rows
            ).conflicting_rules(),
        ):
            store.replace(rule=narrowed)
        store.add(rule=draft)
        report = audit(store=store, rows=rows)
        assert report.is_one_hot
        assert (
            verdict(store=store, row=rows[0]).result == "groceries:voorbeeld"
        )
        assert verdict(store=store, row=rows[1]).result == "food:bakery"

    def test_probe_ignores_the_rule_the_draft_replaces(self):
        store = RuleStore(rules=[rule(1)])
        edited = rule(1, conditions=(("payee", "contains", "voorbeeld"),))
        assert probe(store=store, draft=edited, rows=[row()]).is_one_hot


# ---------------------------------------------------------------- store
class TestStore:
    def test_round_trip_through_yaml(self, tmp_path: Path):
        path = str(tmp_path / "categorisation_rules.yaml")
        store = RuleStore(path=path)
        stored = store.add(
            rule=rule(0, unless=((("description", "contains", "pas"),),))
        )
        store.add(
            rule=Rule(
                id=0,
                direction="credit",
                match=(
                    Condition(
                        field="text",
                        op="any_of",
                        value=("loon", "salaris"),
                        case_sensitive=True,
                    ),
                ),
                target="income:salary",
                note="monthly",
            )
        )
        assert stored.id == 1
        assert stored.created
        store.save()
        loaded = RuleStore.load(path=path)
        assert loaded.rules == store.rules
        assert loaded.path == path
        text = (tmp_path / "categorisation_rules.yaml").read_text()
        assert text.startswith("# Categorisation rules")
        assert "{field: text, op: contains, value: voorbeeld}" in text

    def test_missing_file_is_an_empty_store(self, tmp_path: Path):
        store = RuleStore.load(path=str(tmp_path / "none.yaml"))
        assert len(store) == 0
        assert store.next_id() == 1

    def test_ids_are_unique_and_replace_remove_work(self):
        store = RuleStore(rules=[rule(1)])
        with pytest.raises(RuleStoreError):
            store.add(rule=rule(1))
        store.replace(rule=rule(1, target="other:thing"))
        assert store.get(rule_id=1).target == "other:thing"
        store.remove(rule_id=1)
        assert len(store) == 0
        with pytest.raises(RuleStoreError):
            store.remove(rule_id=1)

    def test_invalid_file_is_reported_with_its_rule_number(
        self, tmp_path: Path
    ):
        path = tmp_path / "rules.yaml"
        path.write_text(
            "version: 1\nrules:\n- id: 1\n  direction: sideways\n  match: []\n  target: x\n"
        )
        with pytest.raises(RuleStoreError, match="rule 1"):
            RuleStore.load(path=str(path))
