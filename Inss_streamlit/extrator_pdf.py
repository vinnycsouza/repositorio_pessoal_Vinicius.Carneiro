import pdfplumber
import re
import pandas as pd

PADROES_BASE = [
    "salário contribuição empresa",
    "salario contribuicao empresa",
    "base inss empresa",
    "contribuição empresa",
    "contribuicao empresa"
]


def normalizar_valor(txt):
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except:
        return None


def extrair_base_oficial(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            texto = page.extract_text() or ""
            for linha in texto.split("\n"):
                l = linha.lower()
                if any(p in l for p in PADROES_BASE):
                    valores = re.findall(r"\d+[\.,]\d{2}", linha)
                    if valores:
                        return normalizar_valor(valores[-1])
    return None


def extrair_rubricas(pdf_file):
    registros = []

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tabelas = page.extract_tables()
            for tabela in tabelas:
                for linha in tabela:
                    if not linha or len(linha) < 2:
                        continue

                    texto_linha = " ".join(str(c) for c in linha if c)
                    valores = re.findall(r"\d+[\.,]\d{2}", texto_linha)

                    if not valores:
                        continue

                    valor = normalizar_valor(valores[-1])
                    if valor is None:
                        continue

                    descricao = linha[1] if len(linha) > 1 else texto_linha

                    registros.append({
                        "rubrica": str(descricao).strip(),
                        "valor": valor
                    })

    return pd.DataFrame(registros)
