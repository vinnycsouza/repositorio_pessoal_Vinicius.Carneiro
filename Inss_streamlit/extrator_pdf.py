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
            largura = page.width
            eixo = largura / 2

            words = page.extract_words(use_text_flow=True)

            linhas = {}
            for w in words:
                y = round(w["top"], 1)
                linhas.setdefault(y, []).append(w)

            for itens in linhas.values():
                texto = " ".join(i["text"] for i in itens)

                lixo = [
                    "cod", "provento", "desconto", "refer",
                    "ativos", "desligados", "total",
                    "base", "inss", "fgts", "líquido", "liquido"
                ]
                if any(p in texto.lower() for p in lixo):
                    continue

                valores_provento = []
                valores_desconto = []

                for i in itens:
                    if re.match(r"\d+[\.,]\d{2}", i["text"]):
                        valor = normalizar_valor(i["text"])
                        if not valor or valor == 0:
                            continue

                        if i["x0"] < eixo:
                            valores_provento.append(valor)
                        else:
                            valores_desconto.append(valor)

                if valores_provento:
                    valor = max(valores_provento)
                    tipo = "PROVENTO"
                elif valores_desconto:
                    valor = max(valores_desconto)
                    tipo = "DESCONTO"
                else:
                    continue

                descricao = re.sub(r"^\d+\s*", "", texto)

                for v in valores_provento + valores_desconto:
                    descricao = descricao.replace(
                        f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                        ""
                    )

                descricao = descricao.strip()
                if len(descricao) < 3:
                    continue

                registros.append({
                    "rubrica": descricao,
                    "valor": valor,
                    "tipo": tipo
                })

    return pd.DataFrame(registros)
