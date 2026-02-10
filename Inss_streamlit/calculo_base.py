import json

with open("regras.json", encoding="utf-8") as f:
    REGRAS = json.load(f)


def classificar_rubrica(nome):
    nome = nome.lower()

    if any(p in nome for p in REGRAS["ignorar"]):
        return "IGNORAR"

    if any(p in nome for p in REGRAS["reduz_base"]):
        return "REDUZ"

    if any(p in nome for p in REGRAS["entra_base"]):
        return "ENTRA"

    return "FORA"


def calcular_base(df, base_oficial):
    base_calc = 0
    classificacoes = []

    for _, row in df.iterrows():
        tipo = classificar_rubrica(row["rubrica"])
        valor = row["valor"]

        if tipo == "ENTRA":
            base_calc += valor
        elif tipo == "REDUZ":
            base_calc -= valor

        classificacoes.append(tipo)

    df["classificacao"] = classificacoes

    diferenca = None
    if base_oficial is not None:
        diferenca = base_calc - base_oficial

    return base_calc, diferenca, df
