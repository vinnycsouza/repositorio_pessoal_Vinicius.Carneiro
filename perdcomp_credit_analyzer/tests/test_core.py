import unittest
from datetime import date
from decimal import Decimal

from src.analyzer import competence_summary, organize_records
from src.models import PerdcompRecord
from src.parsers import money


def sample(number, competence, transmitted, used, balance, **kwargs):
    return PerdcompRecord(
        "teste.pdf", number, transmitted, competence,
        Decimal("100"), Decimal("100"), Decimal(used), Decimal(balance), **kwargs
    )


class PerdcompTests(unittest.TestCase):
    def test_brazilian_money(self):
        self.assertEqual(money("18.245,95"), Decimal("18245.95"))

    def test_competences_are_sorted_by_period(self):
        june = sample("00002.00000.000000.0.0.00-0001", "Junho de 2025", date(2025, 8, 1), "10", "90")
        march = sample("00001.00000.000000.0.0.00-0001", "Março de 2025", date(2026, 8, 1), "20", "80")
        rows = competence_summary([june, march])
        self.assertEqual([row["competence"] for row in rows], ["Março de 2025", "Junho de 2025"])

    def test_retified_document_does_not_define_balance(self):
        old = sample("00001.00000.000000.0.0.00-0001", "Maio de 2025", date(2026, 1, 20), "10", "90")
        replacement = sample(
            "00001.00000.000000.0.0.00-0002", "Maio de 2025",
            date(2026, 1, 22), "40", "60",
            is_amending=True, amended_number=old.number,
        )
        organize_records([old, replacement])
        self.assertFalse(old.effective)
        self.assertEqual(competence_summary([old, replacement])[0]["current_balance"], Decimal("60"))


if __name__ == "__main__":
    unittest.main()
