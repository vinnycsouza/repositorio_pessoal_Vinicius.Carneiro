from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(slots=True)
class PerdcompRecord:
    source_file: str
    number: str
    transmission_date: date
    competence: str
    refundable_credit: Decimal | None
    original_credit_at_delivery: Decimal | None
    original_credit_used: Decimal
    original_credit_balance: Decimal
    is_amending: bool = False
    amended_number: str | None = None
    previous_number: str | None = None
    effective: bool = True
    note: str = ""

