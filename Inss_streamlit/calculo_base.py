import json

def carregar_regras():
    with open("regras.json", "r", encoding="utf-8") as f:
        return json.load(f)

def _norm(s: str) -> str:
    s = (s or "").lower()
    # normalização simples sem lib extra
    return (
        s.replace("á","a").replace("à","a").replace("ã","a").replace("â","a")
         .replace("é","e").replace("ê","e")
         .replace("í","i")
         .replace("ó","o").replace("ô","o").replace("õ","o")
         .replace("ú","u")
         .replace("ç","c")
    )

def classificar_rubrica(rubrica: str, tipo: str, regras: dict) -> str:
    r = _norm(rubrica)

    # Só proventos entram em base; descontos aqui são “coluna de desconto” do relatório,
    # não necessariamente eventos negativos tributáveis.
    if tipo != "PROVENTO":
        return "FORA"

    if any(_norm(p) in r for p in regras["NAO_ENTRA_BASE"]):
        return "FORA"

    if any(_norm(p) in r for p in regras["ENTRA_BASE"]):
        return "ENTRA"

    return "NEUTRA"

def calcular_base_por_grupo(df):
    """
    df precisa ter colunas:
      rubrica, tipo, ativos, desligados, total
    Retorna:
      base_calc (dict por grupo), df_com_classificacao
    """
    regras = carregar_regras()

    df = df.copy()
    df["classificacao"] = df.apply(lambda x: classificar_rubrica(x["rubrica"], x["tipo"], regras), axis=1)

    entra = df[df["classificacao"] == "ENTRA"]

    base_calc = {
        "ativos": float(entra["ativos"].fillna(0).sum()),
        "desligados": float(entra["desligados"].fillna(0).sum()),
        "total": float(entra["total"].fillna(0).sum())
    }

    return base_calc, df
