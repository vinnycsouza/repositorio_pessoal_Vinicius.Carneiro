import pandas as pd

def validar_abas(arquivo, modo):

    xls = pd.ExcelFile(arquivo)
    abas = xls.sheet_names

    erros = []

    if modo == "ICMS":
        if "C190" not in abas:
            erros.append("Aba C190 não encontrada.")

    if modo == "C170":
        if "C170" not in abas:
            erros.append("Aba C170 não encontrada.")

    if modo == "C175":
        if "C175" not in abas:
            erros.append("Aba C175 não encontrada.")

    if modo == "AMBOS":

        if "C170" not in abas:
            erros.append("Aba C170 não encontrada.")

        if "C175" not in abas:
            erros.append("Aba C175 não encontrada.")

    return erros
