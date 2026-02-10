import re
from datetime import datetime

MESES = {
    "jan": "01", "fev": "02", "mar": "03", "abr": "04",
    "mai": "05", "jun": "06", "jul": "07", "ago": "08",
    "set": "09", "out": "10", "nov": "11", "dez": "12"
}


def extrair_competencia(page, competencia_anterior=None):
    texto = (page.extract_text() or "").lower()

    # MM/YYYY
    m = re.search(r"\b(\d{2})/(\d{4})\b", texto)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    # MMM/YYYY
    for mes, num in MESES.items():
        m = re.search(rf"{mes}/(\d{{4}})", texto)
        if m:
            return f"{num}/{m.group(1)}"

    # período: 01/01/2025 a 31/01/2025
    m = re.search(r"\d{2}/\d{2}/(\d{4})", texto)
    if m:
        ano = m.group(1)
        mes = re.search(r"(\d{2})/\d{2}/\d{4}", texto)
        if mes:
            return f"{mes.group(1)}/{ano}"

    # folha de continuação → herda
    return competencia_anterior
