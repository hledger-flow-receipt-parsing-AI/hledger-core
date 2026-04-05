from typing import Protocol

from hledger_core.generics import Transaction


class ReceiptCategoryModel(Protocol):
    # TODO: change to Receipt object.
    def classify_receipt(self, transaction: Transaction) -> str: ...
