from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional, Union

from typeguard import typechecked

if TYPE_CHECKING:
    from hledger_config.config.AccountConfig import AccountConfig
    from hledger_core.TransactionObjects.Receipt import Receipt

from hledger_core.csv_parsing.get_hledger_dict import get_hledger_dict
from hledger_core.generics.GenericTransactionWithCsv import (
    GenericCsvTransaction,
)
from hledger_core.generics.Transaction import Transaction

logger = logging.getLogger(__name__)

# The columns after the classifications, in the order the hledger rules
# name them (hledger_rules: fields).  Every row has all of them, empty when
# they do not apply: hledger reads the columns by position, so a column
# that is only there in some rows would shift the ones after it.
TAGS_COLUMN = "tags"
WITHDRAWAL_COLUMNS = (
    "withdrawal_source_account",
    "withdrawal_source_amount",
    "withdrawal_source_currency",
    "withdrawal_atm_fee",
    "withdrawal_dest_amount",
    "withdrawal_exchange_rate",
    "withdrawal_bank_fx_fee",
    "withdrawal_dest_account",
    "withdrawal_change_returned",
    "withdrawal_dest_currency",
)


@typechecked
@dataclass(frozen=True, unsafe_hash=True)
class ProcessedTransaction:
    transaction: Transaction
    ai_classifications: Dict[str, str]
    logic_classifications: Dict[str, str]
    parent_receipt: Optional["Receipt"] = None
    # The journal comment of the transaction: the tags of its receipt
    # ("workbench:, traceable:yes", see hledger_core.tagging).
    tags_comment: str = ""

    # ai_classifications: Dict[str, str] = field(default_factory=dict)
    # logic_classifications: Dict[str, str] = field(default_factory=dict)

    def to_hledger_dict(
        self, account_config: Optional[AccountConfig] = None
    ) -> Dict[str, Union[int, float, str, datetime, None]]:

        if isinstance(self.transaction, GenericCsvTransaction):

            hledger_tnx_dict: Dict = get_hledger_dict(
                transaction=self.transaction, account_config=account_config
            )
        else:
            hledger_tnx_dict: Dict = get_hledger_dict(
                transaction=self.transaction, account_config=account_config
            )

        # This automatically calls the correct subclass implementation
        data = hledger_tnx_dict

        # Inject enrichment data into the dictionary
        if self.parent_receipt:
            # Inject withdrawal metadata for multi-posting journal entries.
            wm = self.parent_receipt.withdrawal_metadata
            if wm is not None:
                src = wm.source_account_transaction
                data["withdrawal_source_account"] = (
                    f"{src.account.account_holder}:"
                    f"{src.account.bank}:{src.account.account_type}"
                )
                data["withdrawal_source_amount"] = str(
                    src.tendered_amount_out
                )
                data["withdrawal_source_currency"] = (
                    src.account.base_currency.value
                )
                data["withdrawal_atm_fee"] = str(wm.atm_operator_fee)
                if wm.withdrawn_amount is not None:
                    data["withdrawal_dest_amount"] = str(wm.withdrawn_amount)
                else:
                    data["withdrawal_dest_amount"] = ""
                if wm.exchange_rate is not None:
                    data["withdrawal_exchange_rate"] = str(wm.exchange_rate)
                else:
                    data["withdrawal_exchange_rate"] = ""
                data["withdrawal_bank_fx_fee"] = str(wm.bank_fx_fee)

                # Inject destination (wallet) account for bank-side
                # rules — needed so the bank CSV's withdrawal rule can
                # reference the wallet account.
                from hledger_core.TransactionObjects.AccountTransaction import (
                    AccountTransaction as AT,
                )
                from hledger_core.TransactionObjects.Receipt import (
                    Receipt as ReceiptCls,
                )

                dest_account_str = ""
                dest_change_returned = ""
                dest_currency = ""

                # Only extract dest account from real Receipt objects
                # (tests may pass mock objects without the full structure).
                if isinstance(self.parent_receipt, ReceiptCls):
                    from hledger_receipt_processing.receipt_transaction_matching.compare_transaction_to_receipt import (
                        collect_non_csv_transactions,
                    )

                    for acct_txn in collect_non_csv_transactions(
                        self.parent_receipt
                    ):
                        if isinstance(acct_txn, AT):
                            acct = acct_txn.account
                            # The dest account is the one that is NOT
                            # the source bank account.
                            if not (
                                acct.account_holder
                                == src.account.account_holder
                                and acct.bank == src.account.bank
                                and acct.account_type
                                == src.account.account_type
                            ):
                                dest_account_str = (
                                    f"{acct.account_holder}:"
                                    f"{acct.bank}:{acct.account_type}"
                                )
                                dest_change_returned = str(
                                    acct_txn.change_returned
                                )
                                dest_currency = (
                                    acct.base_currency.value
                                )
                                break

                data["withdrawal_dest_account"] = dest_account_str
                data["withdrawal_change_returned"] = dest_change_returned
                data["withdrawal_dest_currency"] = dest_currency

                # US6: Balance validation for domestic withdrawals.
                # amount_debited == change_returned + atm_fee + bank_fee
                if not wm.is_foreign and dest_change_returned:
                    source_amt = round(src.tendered_amount_out, 2)
                    change_amt = round(float(dest_change_returned), 2)
                    atm_fee = round(wm.atm_operator_fee, 2)
                    bank_fee = round(wm.bank_fx_fee, 2)
                    expected = round(change_amt + atm_fee + bank_fee, 2)
                    if source_amt != expected:
                        logger.warning(
                            "Withdrawal balance mismatch for receipt %s: "
                            "source_amount=%.2f != change_returned(%.2f) "
                            "+ atm_fee(%.2f) + bank_fee(%.2f) = %.2f",
                            self.parent_receipt.raw_img_filepath,
                            source_amt,
                            change_amt,
                            atm_fee,
                            bank_fee,
                            expected,
                        )

        # data["ai_classifications"] = self.ai_classifications
        # data["logic_classifications"] = self.logic_classifications

        # The columns in the order of the rules file: the transaction's own
        # columns, the classifications, the tags, the withdrawal columns
        # (empty when this is no withdrawal), and the receipt link last (it
        # is no rules field; hledger ignores columns after the named ones).
        ordered: Dict = {
            key: value
            for key, value in data.items()
            if key not in WITHDRAWAL_COLUMNS
        }
        ordered.update(self.logic_classifications)
        ordered.update(self.ai_classifications)
        ordered[TAGS_COLUMN] = self.tags_comment
        for column in WITHDRAWAL_COLUMNS:
            ordered[column] = data.get(column, "")
        if self.parent_receipt:
            ordered["receipt_link"] = self.parent_receipt.raw_img_filepath
        return ordered
