import io
import re
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import PurePosixPath

from pypdf import PdfReader

from .models import PerdcompRecord

NUMBER = r"\d{5}\.\d{5}\.\d{6}\.\d\.\d\.\d{2}-\d{4}"
MONEY = r"\d{1,3}(?:\.\d{3})*,\d{2}"


class ExtractionError(ValueError):
    pass


def pdf_text(data):
    try:
        return "\n".join(
            page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages
        )
    except Exception as exc:
        raise ExtractionError(f"PDF ilegível: {exc}") from exc


def iter_pdf_files(files):
    """Retorna PDFs enviados diretamente ou contidos em ZIPs, sempre em memória."""
    pdfs, warnings = [], []
    for name, data in files:
        if name.lower().endswith(".pdf"):
            pdfs.append((name, data))
            continue
        if not name.lower().endswith(".zip"):
            warnings.append(f"{name}: formato ignorado")
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for item in archive.infolist():
                    short_name = PurePosixPath(item.filename).name
                    if item.is_dir() or not short_name.lower().endswith(".pdf"):
                        continue
                    if item.flag_bits & 1:
                        warnings.append(f"{name} / {short_name}: arquivo protegido por senha")
                        continue
                    pdfs.append((f"{name} :: {short_name}", archive.read(item)))
        except (zipfile.BadZipFile, RuntimeError):
            warnings.append(f"{name}: ZIP inválido ou protegido por senha")
    return pdfs, warnings


def money(value):
    return Decimal(value.replace(".", "").replace(",", "."))


def first(pattern, text, flags=0):
    found = re.search(pattern, text, flags)
    return found.group(1).strip() if found else None


def required(pattern, text, label):
    value = first(pattern, text)
    if value is None:
        raise ExtractionError(f"campo ausente: {label}")
    return value


def parse_individual_pdf(name, data):
    text = pdf_text(data)
    if "DADOS INICIAIS" not in text:
        raise ExtractionError("modelo PER/DCOMP individual não reconhecido")

    refundable = first(rf"Crédito Passível de Restituição\s+({MONEY})", text)
    if refundable is None:
        refundable = first(rf"Documento Inicial\s+({MONEY})", text)
    original_match = first(rf"({MONEY})Crédito Original na Data da Entrega", text)

    return PerdcompRecord(
        source_file=name,
        number=required(rf"CNPJ\s+[\d./-]+\s+({NUMBER})", text, "número do PER/DCOMP"),
        transmission_date=datetime.strptime(
            required(r"Data de Transmissão\s+(\d{2}/\d{2}/\d{4})", text, "data de transmissão"),
            "%d/%m/%Y",
        ).date(),
        competence=required(
            r"Competência\s+([A-Za-zÀ-ÿ]+\s+de\s+\d{4})", text, "competência"
        ),
        refundable_credit=money(refundable) if refundable else None,
        original_credit_at_delivery=money(original_match) if original_match else None,
        original_credit_used=money(
            required(
                rf"Total do Crédito Original Utilizado neste Documento\s+({MONEY})",
                text,
                "crédito original utilizado",
            )
        ),
        original_credit_balance=money(
            required(rf"Saldo do Crédito Original\s+({MONEY})", text, "saldo do crédito")
        ),
        is_amending=first(r"PER/DCOMP Retificador\s+(Sim|Não)", text) == "Sim",
        amended_number=first(rf"N[°º]\s*PER/DCOMP Retificado\s+({NUMBER})", text),
        previous_number=first(rf"Nº do PER/DCOMP Inicial\s+({NUMBER})", text),
    )

