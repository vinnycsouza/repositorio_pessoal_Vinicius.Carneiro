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
            texto = page.extract_text() or ""
            linhas = texto.split("\n")

            for linha in linhas:
                linha_limpa = linha.strip()

                valores = re.findall(r"\d+[\.,]\d{2}", linha_limpa)
                if not valores:
                    continue

                valor = normalizar_valor(valores[-1])
                if valor is None:
                    continue

                lixo = [
                    "total",
                    "base",
                    "inss",
                    "fgts",
                    "líquido",
                    "liquido",
                    "salário contribuição",
                    "salario contribuicao"
                ]

                if any(p in linha_limpa.lower() for p in lixo):
                    continue

                descricao = linha_limpa.replace(valores[-1], "").strip()
                if len(descricao) < 5:
                    continue

                registros.append({
                    "rubrica": descricao,
                    "valor": valor
                })

    return pd.DataFrame(registros)
