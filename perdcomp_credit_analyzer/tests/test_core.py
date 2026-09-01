import unittest
import io
import zipfile
from unittest.mock import patch
from datetime import date
from decimal import Decimal

from src.analyzer import competence_summary, deduplicate_records, organize_records
from src.models import PerdcompRecord
from src.parsers import iter_pdf_files, money, parse_individual_pdf


def sample(number, competence, transmitted, used, balance, **kwargs):
    return PerdcompRecord(
        "teste.pdf", number, transmitted, competence, "Declaração de Compensação",
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

    def test_same_day_records_follow_financial_chain(self):
        first_record = sample(
            "03022.00990.161122.1.3.15-2498", "Janeiro de 2021",
            date(2022, 11, 16), "7240.08", "46943.96",
        )
        first_record.original_credit_at_delivery = Decimal("54184.04")
        last_record = sample(
            "09190.26652.161122.1.3.15-5558", "Janeiro de 2021",
            date(2022, 11, 16), "39161.43", "0",
        )
        last_record.original_credit_at_delivery = Decimal("39161.43")
        middle_record = sample(
            "17363.77998.161122.1.3.15-8905", "Janeiro de 2021",
            date(2022, 11, 16), "6863.17", "39161.43",
        )
        middle_record.original_credit_at_delivery = Decimal("46024.60")
        ordered = organize_records([last_record, middle_record, first_record])
        self.assertEqual(
            [record.number for record in ordered],
            [first_record.number, middle_record.number, last_record.number],
        )
        self.assertIn("Possível elo não localizado", middle_record.note)

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

    def test_duplicate_perdcomp_is_ignored(self):
        number = "00001.00000.000000.0.0.00-0001"
        first_record = sample(number, "Maio de 2025", date(2026, 1, 1), "10", "90")
        duplicate = sample(number, "Maio de 2025", date(2026, 1, 1), "10", "90")
        unique, warnings = deduplicate_records([first_record, duplicate])
        self.assertEqual(len(unique), 1)
        self.assertEqual(len(warnings), 1)

    def test_suspicious_zip_compression_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("suspeito.pdf", b"0" * (1024 * 1024))
        pdfs, warnings = iter_pdf_files([("suspeito.zip", buffer.getvalue())])
        self.assertEqual(pdfs, [])
        self.assertTrue(any("compressão suspeita" in warning for warning in warnings))

    def test_refund_request_uses_initial_credit_as_balance(self):
        text = """
        DADOS INICIAIS
        CNPJ 08.744.139/0001-51 31677.26450.200722.1.2.15-1480
        Data de Transmissão 20/07/2022
        Tipo de Documento Pedido de Restituição
        PER/DCOMP Retificador Não
        Crédito Passível de Restituição 26.739,36
        26.739,36Crédito Original na Data da Entrega
        Competência Janeiro de 2022
        """
        with patch("src.parsers.pdf_text", return_value=text):
            record = parse_individual_pdf("pedido.pdf", b"pdf")
        self.assertEqual(record.original_credit_used, Decimal("0"))
        self.assertEqual(record.original_credit_balance, Decimal("26739.36"))
        self.assertTrue(record.values_inferred)


if __name__ == "__main__":
    unittest.main()
