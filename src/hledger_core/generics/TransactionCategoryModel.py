from typing import Protocol

from hledger_core.categorisation.Categories import CategoryNamespace
from hledger_core.generics.Transaction import Transaction


class TransactionCategoryModel(Protocol):
    def classify(
        self, transaction: Transaction, category_namespace: CategoryNamespace
    ) -> str: ...
