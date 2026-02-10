import re

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
        m = re.search(rf"\b{mes}/(\d{{4}})\b", texto)
        if m:
            return f"{num}/{m.group(1)}"

    # período: 01/01/2025 a 31/01/2025 -> pega o primeiro mês/ano
    m = re.search(r"\b(\d{2})/\d{2}/(\d{4})\b", texto)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    return competencia_anterior
