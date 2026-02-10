import pdfplumber
import re
import pandas as pd


def normalizar_valor(txt):
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except:
        return None


def extrair_base_oficial(pdf_file):
    candidatos = []

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=True)

            linhas = {}
            for w in words:
                y = round(w["top"], 1)
                linhas.setdefault(y, []).append(w)

            for itens in linhas.values():
                texto = " ".join(i["text"] for i in itens).lower()

                if any(p in texto for p in [
                    "salário contribuição",
                    "salario contribuicao",
                    "base inss",
                    "inss empresa",
                    "contribuição empresa",
                    "contribuicao empresa"
                ]):
                    for i in itens:
                        if re.match(r"\d+[\.,]\d{2}", i["text"]):
                            valor = normalizar_valor(i["text"])
                            if valor and valor > 100:
                                candidatos.append(valor)

    return max(candidatos) if candidatos else None


def extrair_rubricas(pdf_file):
    registros = []

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=True)

            linhas = {}
            for w in words:
                y = round(w["top"], 1)
                linhas.setdefault(y, []).append(w)

            for itens in linhas.values():
                itens = sorted(itens, key=lambda x: x["x0"])
                texto_linha = " ".join(i["text"] for i in itens)

                valores = []
                for i in itens:
                    if re.match(r"\d+[\.,]\d{2}", i["text"]):
                        valor = normalizar_valor(i["text"])
                        if valor and valor > 10:
                            valores.append((i["x0"], valor))

                if not valores:
                    continue

                valor_final = sorted(valores, key=lambda x: x[0])[-1][1]

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

                if any(p in texto_linha.lower() for p in lixo):
                    continue

                descricao = texto_linha.strip()
                if len(descricao) < 5:
                    continue

                tipo = "DESCONTO" if any(
                    p in descricao.lower()
                    for p in ["inss", "irrf", "vale", "plano", "adiantamento"]
                ) else "PROVENTO"

                registros.append({
                    "rubrica": descricao,
                    "valor": valor_final,
                    "tipo": tipo
                })

    return pd.DataFrame(registros)
