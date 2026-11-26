"""Does a rule match a transaction?  The transaction is seen through a
``RowView``: the few text fields a condition can look at, plus what the
screen needs to show the row."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from typeguard import typechecked

from hledger_core.categorisation.rules.schema import (
    TEXT_ANY,
    TEXT_FIELDS,
    Condition,
    Rule,
)
from hledger_core.TransactionObjects.Posting import TransactionCode


@typechecked
@dataclass(frozen=True)
class RowView:
    """One bank transaction as the rules see it."""

    row_id: str
    direction: str  # debit | credit
    payee: str
    description: str
    counter_account: str
    own_account: str  # holder:bank:type
    amount: float  # the amount out of the account (negative: in)
    date: str  # YYYY-MM-DD-HH-MM-SS

    @property
    def amount_text(self) -> str:
        """The amount as a condition sees it: Python's float text."""
        return str(float(self.amount))

    @property
    def day(self) -> str:
        return self.date[:10]

    def field_values(self, *, field: str) -> Tuple[str, ...]:
        if field == TEXT_ANY:
            return tuple(getattr(self, name) for name in TEXT_FIELDS)
        if field == "amount":
            return (self.amount_text,)
        return (getattr(self, field),)

    def one_line(self, *, width: Optional[int] = None) -> str:
        """``date  amount  payee | description`` for screens and errors;
        cut to *width* characters when one is given."""
        text = " | ".join(p for p in (self.payee, self.description) if p)
        head = f"{self.day}  {self.amount:>10.2f}  "
        if width is not None:
            room = max(width - len(head), 10)
            if len(text) > room:
                text = text[: room - 1] + "…"
        return head + text

    @staticmethod
    def from_transaction(transaction: Any) -> "RowView":
        """From a ``GenericCsvTransaction`` (duck typed: any transaction with
        the same attributes works)."""
        extra = getattr(transaction, "extra", None) or {}
        own_account = transaction.account.to_string()
        nr = extra.get("nr_in_batch")
        row_id = (
            f"{own_account}#{nr}"
            if nr is not None
            else f"{own_account}#{transaction.get_hash()}"
        )
        return RowView(
            row_id=row_id,
            direction=direction_of(transaction),
            payee=_text(getattr(transaction, "other_party_name", None)),
            description=_text(getattr(transaction, "description", None)),
            counter_account=_text(
                getattr(transaction, "other_party_account_name", None)
            ),
            own_account=own_account,
            amount=float(transaction.tendered_amount_out),
            date=transaction.the_date.strftime("%Y-%m-%d-%H-%M-%S"),
        )


def _text(value: Optional[Any]) -> str:
    return "" if value is None else str(value)


@typechecked
def direction_of(transaction: Any) -> str:
    """``debit`` or ``credit``: the explicit transaction code when the CSV
    has one, else the sign of the amount."""
    code = getattr(transaction, "transaction_code", None)
    if code is not None:
        code = TransactionCode.normalize_transaction_code(transaction_code=code)
    else:
        code = transaction.get_transaction_code()
    return "debit" if code == TransactionCode.DEBIT else "credit"


@typechecked
def condition_holds(*, condition: Condition, row: RowView) -> bool:
    values = row.field_values(field=condition.field)
    if not condition.case_sensitive:
        values = tuple(v.lower() for v in values)
    if condition.op == "any_of":
        needles = (
            condition.value
            if condition.case_sensitive
            else tuple(v.lower() for v in condition.value)
        )
        return any(n in v for v in values for n in needles)
    needle = (
        condition.value
        if condition.case_sensitive
        else str(condition.value).lower()
    )
    if condition.op == "contains":
        return any(needle in v for v in values)
    if condition.op == "starts_with":
        return any(v.startswith(needle) for v in values)
    if condition.op == "equals":
        return any(v == needle for v in values)
    raise ValueError(f"Unknown op: {condition.op}")  # pragma: no cover


@typechecked
def rule_matches(*, rule: Rule, row: RowView) -> bool:
    if rule.direction != row.direction:
        return False
    if not all(condition_holds(condition=c, row=row) for c in rule.match):
        return False
    for group in rule.unless:
        if all(condition_holds(condition=c, row=row) for c in group):
            return False
    return True
