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
MEBIBYTE = 1024 * 1024
MAX_UPLOAD_BYTES = 25 * MEBIBYTE
MAX_DIRECT_PDF_BYTES = 10 * MEBIBYTE
MAX_ZIP_UNCOMPRESSED_BYTES = 100 * MEBIBYTE
MAX_PDF_FILES = 250
MAX_PDF_PAGES = 100
MAX_COMPRESSION_RATIO = 100


class ExtractionError(ValueError):
    pass


def pdf_text(data):
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("PDF protegido por senha")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ExtractionError(
                f"PDF com {len(reader.pages)} páginas; limite de {MAX_PDF_PAGES}"
            )
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"PDF ilegível: {exc}") from exc


def iter_pdf_files(files):
    """Retorna PDFs enviados diretamente ou contidos em ZIPs, sempre em memória."""
    pdfs, warnings = [], []
    for name, data in files:
        if len(data) > MAX_UPLOAD_BYTES:
            warnings.append(f"{name}: excede o limite de 25 MB por envio")
            continue
        if name.lower().endswith(".pdf"):
            if len(data) > MAX_DIRECT_PDF_BYTES:
                warnings.append(f"{name}: PDF excede o limite de 10 MB")
                continue
            pdfs.append((name, data))
            continue
        if not name.lower().endswith(".zip"):
            warnings.append(f"{name}: formato ignorado")
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                candidates = [
                    item
                    for item in archive.infolist()
                    if not item.is_dir()
                    and PurePosixPath(item.filename).name.lower().endswith(".pdf")
                ]
                if len(candidates) > MAX_PDF_FILES:
                    warnings.append(
                        f"{name}: contém {len(candidates)} PDFs; limite de {MAX_PDF_FILES}"
                    )
                    continue
                total_uncompressed = sum(item.file_size for item in candidates)
                if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                    warnings.append(f"{name}: conteúdo descompactado excede 100 MB")
                    continue
                unsafe = False
                for item in candidates:
                    short_name = PurePosixPath(item.filename).name
                    if item.flag_bits & 1:
                        warnings.append(f"{name} / {short_name}: arquivo protegido por senha")
                        unsafe = True
                        break
                    if item.file_size > MAX_DIRECT_PDF_BYTES:
                        warnings.append(f"{name} / {short_name}: PDF excede 10 MB")
                        unsafe = True
                        break
                    ratio = item.file_size / max(item.compress_size, 1)
                    if ratio > MAX_COMPRESSION_RATIO:
                        warnings.append(
                            f"{name} / {short_name}: taxa de compressão suspeita"
                        )
                        unsafe = True
                        break
                if unsafe:
                    continue
                for item in candidates:
                    short_name = PurePosixPath(item.filename).name
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
    document_type = required(r"Tipo de Documento\s+([^\r\n]+)", text, "tipo de documento")
    used_match = first(
        rf"Total do Crédito Original Utilizado neste Documento\s+({MONEY})", text
    )
    balance_match = first(rf"Saldo do Crédito Original\s+({MONEY})", text)
    is_refund_request = document_type == "Pedido de Restituição"
    if used_match is None and not is_refund_request:
        raise ExtractionError("campo ausente: crédito original utilizado")
    if balance_match is None and not is_refund_request:
        raise ExtractionError("campo ausente: saldo do crédito")
    initial_balance = original_match or refundable
    if is_refund_request and initial_balance is None:
        raise ExtractionError("pedido de restituição sem valor de crédito identificável")

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
        document_type=document_type,
        refundable_credit=money(refundable) if refundable else None,
        original_credit_at_delivery=money(original_match) if original_match else None,
        original_credit_used=money(used_match) if used_match else Decimal("0"),
        original_credit_balance=money(balance_match or initial_balance),
        is_amending=first(r"PER/DCOMP Retificador\s+(Sim|Não)", text) == "Sim",
        amended_number=first(rf"N[°º]\s*PER/DCOMP Retificado\s+({NUMBER})", text),
        previous_number=first(rf"Nº do PER/DCOMP Inicial\s+({NUMBER})", text),
        values_inferred=is_refund_request and (used_match is None or balance_match is None),
    )
