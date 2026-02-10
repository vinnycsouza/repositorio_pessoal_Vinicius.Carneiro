import pdfplumber
import re
import pandas as pd


def normalizar_valor(txt):
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except:
        return None


def extrair_rubricas(pdf_file):
    registros = []

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            texto = page.extract_text() or ""
            linhas = texto.split("\n")

            for linha in linhas:
                linha_limpa = linha.strip()

                # precisa ter número monetário
                valores = re.findall(r"\d+[\.,]\d{2}", linha_limpa)
                if not valores:
                    continue

                valor = normalizar_valor(valores[-1])
                if valor is None:
                    continue

                # ignora totais e resumos
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

                # remove o valor da linha para sobrar a descrição
                descricao = linha_limpa.replace(valores[-1], "").strip()

                # descrição muito curta não é rubrica
                if len(descricao) < 5:
                    continue

                registros.append({
                    "rubrica": descricao,
                    "valor": valor
                })

    return pd.DataFrame(registros)
