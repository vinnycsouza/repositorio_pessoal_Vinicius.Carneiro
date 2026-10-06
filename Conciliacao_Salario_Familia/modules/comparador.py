from __future__ import annotations

import re
import unicodedata

import pandas as pd


def normalizar_cnpj(valor: object) -> str:
    return "".join(caractere for caractere in str(valor or "") if caractere.isdigit()).zfill(14)


def normalizar_competencia(valor: object) -> str:
    texto = str(valor or "").strip()
    encontrados = re.search(r"(\d{1,2})[/-](\d{4})", texto)
    if encontrados:
        return f"{int(encontrados.group(1)):02d}/{encontrados.group(2)}"
    encontrados = re.search(r"(\d{4})[/-](\d{1,2})", texto)
    if encontrados:
        return f"{int(encontrados.group(2)):02d}/{encontrados.group(1)}"
    return texto


def _sem_acentos(valor: object) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(valor or ""))
        if not unicodedata.combining(c)
    ).lower()


def localizar_coluna(colunas, candidatos: list[str]) -> str | None:
    mapa = {_sem_acentos(coluna): str(coluna) for coluna in colunas}
    for candidato in candidatos:
        candidato = _sem_acentos(candidato)
        if candidato in mapa:
            return mapa[candidato]
    for normalizada, original in mapa.items():
        if any(_sem_acentos(candidato) in normalizada for candidato in candidatos):
            return original
    return None


def preparar_levantamento(
    dados: pd.DataFrame,
    coluna_cnpj: str,
    coluna_competencia: str,
    coluna_valor: str,
    origem: str,
    coluna_descricao: str | None = None,
    filtro_descricao: str = "",
) -> pd.DataFrame:
    base = dados.copy()
    if coluna_descricao and filtro_descricao.strip():
        termos = [termo.strip() for termo in filtro_descricao.split(";") if termo.strip()]
        descricao = base[coluna_descricao].fillna("").map(_sem_acentos)
        mascara = pd.Series(False, index=base.index)
        for termo in termos:
            mascara |= descricao.str.contains(_sem_acentos(termo), regex=False)
        base = base.loc[mascara]

    preparado = pd.DataFrame(
        {
            "cnpj": base[coluna_cnpj].map(normalizar_cnpj),
            "competencia": base[coluna_competencia].map(normalizar_competencia),
            "valor_levantamento": pd.to_numeric(base[coluna_valor], errors="coerce"),
        }
    ).dropna(subset=["valor_levantamento"])
    preparado["origem"] = origem
    return preparado.groupby(["cnpj", "competencia", "origem"], as_index=False)[
        "valor_levantamento"
    ].sum()


def comparar(ecac: pd.DataFrame, levantamento: pd.DataFrame) -> pd.DataFrame:
    dados_ecac = ecac.copy()
    dados_ecac["cnpj"] = dados_ecac["cnpj"].map(normalizar_cnpj)
    dados_ecac["competencia"] = dados_ecac["competencia"].map(normalizar_competencia)
    dados_ecac = dados_ecac.rename(columns={"salario_familia": "valor_ecac"})
    dados_ecac = dados_ecac.groupby(["cnpj", "competencia"], as_index=False)["valor_ecac"].sum(min_count=1)

    consolidado = levantamento.groupby(["cnpj", "competencia"], as_index=False)[
        "valor_levantamento"
    ].sum()
    resultado = consolidado.merge(
        dados_ecac, on=["cnpj", "competencia"], how="outer", indicator=True
    )
    resultado["diferença_potencial"] = (
        resultado["valor_levantamento"] - resultado["valor_ecac"]
    )

    def situacao(linha) -> str:
        if linha["_merge"] == "left_only":
            return "Competência ausente no e-CAC"
        if linha["_merge"] == "right_only":
            return "Competência ausente no levantamento"
        diferenca = linha["diferença_potencial"]
        if pd.isna(diferenca):
            return "Aguardando conferência"
        if abs(float(diferenca)) < 0.01:
            return "Sem diferença"
        if diferenca > 0:
            return "Potencial valor não deduzido"
        return "DCTFWeb superior ao levantamento"

    resultado["situação"] = resultado.apply(situacao, axis=1)
    return resultado.drop(columns=["_merge"]).sort_values(["cnpj", "competencia"])

