"""
Shared contract every bank parser returns: a list of Transaction dicts.

Amount sign convention: positive = charge, negative = payment/refund.

Some banks attach extra keys beyond this base shape (Liverpool's
"needs_review", Banamex's "card"/"source", Invex's "is_installment") -
build_report.py reads those per-bank when it builds the Review column.
"""
from typing import TypedDict


class Transaction(TypedDict):
    date: str
    description: str
    amount: float
    type: str  # "charge" | "payment"
