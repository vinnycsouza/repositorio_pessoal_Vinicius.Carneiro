import json


def carregar_regras():
    with open("regras.json", "r", encoding="utf-8") as f:
        return json.load(f)


def calcular_base(df):
    regras = carregar_regras()

    def classificar(rubrica, tipo):
        r = rubrica.lower()

        if tipo != "PROVENTO":
            return "FORA"

        if any(p in r for p in regras["NAO_ENTRA_BASE"]):
            return "FORA"

        if any(p in r for p in regras["ENTRA_BASE"]):
            return "ENTRA"

        return "NEUTRA"

    df["classificacao"] = df.apply(
        lambda x: classificar(x["rubrica"], x["tipo"]),
        axis=1
    )

    base_calc = df.loc[df["classificacao"] == "ENTRA", "valor"].sum()
    return base_calc, df
