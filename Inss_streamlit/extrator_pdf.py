import pdfplumber
import pandas as pd
import re


def normalizar_valor(txt):
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except:
        return None


def extrair_rubricas_page(page):
    registros = []
    largura = page.width
    eixo = largura * 0.50

    words = page.extract_words(use_text_flow=True)

    linhas = {}
    for w in words:
        y = round(w["top"], 1)
        linhas.setdefault(y, []).append(w)

    for itens in linhas.values():
        texto = " ".join(i["text"] for i in itens).lower()

        # ignora quadros que não são rubricas
        if any(p in texto for p in [
            "salario contribuicao",
            "bases de cálculo",
            "inss empresa",
            "resumo",
            "fgts",
            "fap",
            "terceiros"
        ]):
            continue

        esquerda = [i for i in itens if i["x0"] < eixo]
        direita = [i for i in itens if i["x0"] >= eixo]

        def processar(bloco, tipo):
            valores = [
                normalizar_valor(i["text"])
                for i in bloco
                if re.match(r"\d+[\.,]\d{2}", i["text"])
            ]
            valores = [v for v in valores if v and v > 0]
            if not valores:
                return None

            texto_bloco = " ".join(i["text"] for i in bloco)
            descricao = re.sub(r"\d+[\.,]\d{2}", "", texto_bloco)
            descricao = re.sub(r"^\d+\s*", "", descricao).strip()

            if len(descricao) < 3:
                return None

            return {
                "rubrica": descricao,
                "valor": max(valores),
                "tipo": tipo
            }

        r1 = processar(esquerda, "PROVENTO")
        r2 = processar(direita, "DESCONTO")

        if r1:
            registros.append(r1)
        if r2:
            registros.append(r2)

    return registros


def extrair_base_oficial_page(page):
    texto = (page.extract_text() or "").lower()

    if not any(p in texto for p in [
        "identificação geral",
        "resumo geral",
        "bases de cálculo",
        "totais da empresa"
    ]):
        return None

    words = page.extract_words(use_text_flow=True)
    candidatos = []

    for w in words:
        if re.match(r"\d+[\.,]\d{2}", w["text"]):
            valor = normalizar_valor(w["text"])
            if valor and valor > 100:
                candidatos.append(valor)

    return max(candidatos) if candidatos else None
