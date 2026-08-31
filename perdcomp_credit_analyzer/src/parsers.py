import io, re, zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import PurePosixPath
from pypdf import PdfReader
from .models import ConsolidatedRecord, PerdcompRecord

NUMBER = r"\d{5}\.\d{5}\.\d{6}\.\d\.\d\.\d{2}-\d{4}"
MONEY = r"\d{1,3}(?:\.\d{3})*,\d{2}"
class ExtractionError(ValueError): pass

def pdf_text(data):
    try: return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    except Exception as exc: raise ExtractionError(f"PDF ilegível: {exc}") from exc

def iter_pdf_files(files):
    pdfs, warnings = [], []
    for name, data in files:
        if name.lower().endswith(".pdf"): pdfs.append((name, data)); continue
        if not name.lower().endswith(".zip"): warnings.append(f"{name}: formato ignorado"); continue
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for item in archive.infolist():
                    short = PurePosixPath(item.filename).name
                    if not item.is_dir() and short.lower().endswith(".pdf"):
                        pdfs.append((f"{name} :: {short}", archive.read(item)))
        except zipfile.BadZipFile: warnings.append(f"{name}: ZIP inválido")
    return pdfs, warnings

def money(value): return Decimal(value.replace(".", "").replace(",", "."))
def first(pattern, text, flags=0):
    found = re.search(pattern, text, flags); return found.group(1).strip() if found else None
def required(pattern, text, label):
    value = first(pattern, text)
    if value is None: raise ExtractionError(f"campo ausente: {label}")
    return value

def parse_individual_pdf(name, data):
    text = pdf_text(data)
    if "DADOS INICIAIS" not in text: raise ExtractionError("modelo individual não reconhecido")
    refundable = first(rf"Crédito Passível de Restituição\s+({MONEY})", text)
    if not refundable: refundable = first(rf"Documento Inicial\s+({MONEY})", text)
    return PerdcompRecord(
        name, required(rf"CNPJ\s+[\d./-]+\s+({NUMBER})", text, "PER/DCOMP"),
        datetime.strptime(required(r"Data de Transmissão\s+(\d{2}/\d{2}/\d{4})", text, "transmissão"), "%d/%m/%Y").date(),
        required(r"Competência\s+([A-Za-zÀ-ÿ]+\s+de\s+\d{4})", text, "competência"),
        money(refundable) if refundable else None,
        money(first(rf"({MONEY})Crédito Original na Data da Entrega", text)) if first(rf"({MONEY})Crédito Original na Data da Entrega", text) else None,
        money(required(rf"Total do Crédito Original Utilizado neste Documento\s+({MONEY})", text, "utilizado")),
        money(required(rf"Saldo do Crédito Original\s+({MONEY})", text, "saldo")),
        first(r"PER/DCOMP Retificador\s+(Sim|Não)", text) == "Sim",
        first(rf"N[°º]\s*PER/DCOMP Retificado\s+({NUMBER})", text),
        first(rf"Nº do PER/DCOMP Inicial\s+({NUMBER})", text),
    )

def parse_consolidated_pdf(name, data):
    text = pdf_text(data); starts = list(re.finditer(NUMBER, text)); result = []
    if "Situação" not in text: raise ExtractionError("modelo consolidado não reconhecido")
    for i, match in enumerate(starts):
        block = text[match.end(): starts[i+1].start() if i+1 < len(starts) else len(text)]
        date = first(r"(\d{2}/\d{2}/\d{4})", block); values = re.findall(MONEY, block)
        if not date or len(values) < 3: continue
        status = "Homologado" if "Homologado" in block else "Retificado" if "Retificado" in block else "Análise concluída" if "Análise" in block else "Não identificado"
        result.append(ConsolidatedRecord(name, match.group(), datetime.strptime(date, "%d/%m/%Y").date(), status, *map(money, values[:3])))
    if not result: raise ExtractionError("nenhuma linha reconhecida")
    return result

