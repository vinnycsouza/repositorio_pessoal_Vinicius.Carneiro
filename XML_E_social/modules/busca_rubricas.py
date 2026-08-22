from __future__ import annotations

import re
import unicodedata

import pandas as pd


def normalizar_busca(valor: object) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).casefold().strip()


def extrair_termos_busca(texto: str) -> list[str]:
    """Separa listas coladas sem quebrar códigos que contenham ponto."""
    if not texto:
        return []
    termos = [t.strip() for t in re.split(r"[;,\n\r\t]+", str(texto)) if t.strip()]
    vistos: set[str] = set()
    unicos: list[str] = []
    for termo in termos:
        chave = normalizar_busca(termo)
        if chave and chave not in vistos:
            vistos.add(chave)
            unicos.append(termo)
    return unicos


def filtrar_rubricas_por_multibusca(
    df: pd.DataFrame, texto_busca: str
) -> tuple[pd.DataFrame, list[str]]:
    """Busca código exato ou trecho da descrição, ignorando caixa e acentos."""
    termos = extrair_termos_busca(texto_busca)
    if not termos or df.empty:
        return df.copy(), termos

    codigos = (
        df["cod_rubr"].fillna("").astype(str).map(normalizar_busca)
        if "cod_rubr" in df.columns else pd.Series("", index=df.index)
    )
    descricoes = (
        df["dsc_rubr"].fillna("").astype(str).map(normalizar_busca)
        if "dsc_rubr" in df.columns else pd.Series("", index=df.index)
    )
    mascara = pd.Series(False, index=df.index)
    motivos = pd.Series("", index=df.index, dtype="object")
    for termo_original in termos:
        termo = normalizar_busca(termo_original)
        por_codigo = codigos.eq(termo)
        por_descricao = descricoes.str.contains(re.escape(termo), regex=True, na=False)
        encontrado = por_codigo | por_descricao
        mascara |= encontrado
        motivos.loc[por_codigo & motivos.eq("")] = f"Código exato: {termo_original}"
        motivos.loc[por_descricao & ~por_codigo & motivos.eq("")] = (
            f"Descrição: {termo_original}"
        )
    resultado = df[mascara].copy()
    resultado["correspondencia_busca"] = motivos.loc[mascara]
    return resultado, termos
