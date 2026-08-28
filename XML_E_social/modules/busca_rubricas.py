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
    df: pd.DataFrame, texto_busca: str, modo: str = "codigo_exato"
) -> tuple[pd.DataFrame, list[str]]:
    """Busca uma lista de códigos exatos ou trechos de descrição."""
    if modo not in {"codigo_exato", "descricao"}:
        raise ValueError(f"Modo de busca desconhecido: {modo}")
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
        por_codigo = codigos.eq(termo) if modo == "codigo_exato" else pd.Series(False, index=df.index)
        por_descricao = (
            descricoes.str.contains(re.escape(termo), regex=True, na=False)
            if modo == "descricao"
            else pd.Series(False, index=df.index)
        )
        encontrado = por_codigo | por_descricao
        mascara |= encontrado
        motivos.loc[por_codigo & motivos.eq("")] = f"Código exato: {termo_original}"
        motivos.loc[por_descricao & ~por_codigo & motivos.eq("")] = (
            f"Descrição: {termo_original}"
        )
    resultado = df[mascara].copy()
    resultado["correspondencia_busca"] = motivos.loc[mascara]
    return resultado, termos


def termos_sem_correspondencia(
    df: pd.DataFrame, termos: list[str], modo: str = "codigo_exato"
) -> list[str]:
    """Retorna termos sem correspondência no modo de busca selecionado."""
    if modo not in {"codigo_exato", "descricao"}:
        raise ValueError(f"Modo de busca desconhecido: {modo}")
    if not termos:
        return []
    if df.empty:
        return list(termos)
    codigos = (
        df["cod_rubr"].fillna("").astype(str).map(normalizar_busca)
        if "cod_rubr" in df.columns else pd.Series("", index=df.index)
    )
    descricoes = (
        df["dsc_rubr"].fillna("").astype(str).map(normalizar_busca)
        if "dsc_rubr" in df.columns else pd.Series("", index=df.index)
    )
    ausentes: list[str] = []
    for original in termos:
        termo = normalizar_busca(original)
        if modo == "codigo_exato":
            encontrou = bool(codigos.eq(termo).any())
        else:
            encontrou = bool(
                descricoes.str.contains(re.escape(termo), regex=True, na=False).any()
            )
        if not encontrou:
            ausentes.append(original)
    return ausentes


def atualizar_selecao_rubricas(
    atuais: set[str] | list[str],
    resultados: set[str] | list[str],
    acao: str,
) -> list[str]:
    """Aplica uma ação explícita sem confundir busca com seleção acumulada."""
    conjunto_atual = {str(chave) for chave in atuais}
    conjunto_resultado = {str(chave) for chave in resultados}
    if acao == "substituir":
        nova = conjunto_resultado
    elif acao == "adicionar":
        nova = conjunto_atual | conjunto_resultado
    elif acao == "remover":
        nova = conjunto_atual - conjunto_resultado
    elif acao == "limpar":
        nova = set()
    else:
        raise ValueError(f"Ação de seleção desconhecida: {acao}")
    return sorted(nova)


def chave_rubrica(codigo: object, tabela: object) -> str:
    """Identificador estável usado pelos módulos sem misturar tabelas distintas."""
    return f"{str(codigo or '')}||{str(tabela or '')}"


def separar_chave_rubrica(chave: object) -> tuple[str, str]:
    codigo, separador, tabela = str(chave or "").partition("||")
    return codigo, tabela if separador else ""


def filtrar_dataframe_por_chaves(
    df: pd.DataFrame, chaves: set[str] | list[str] | None
) -> pd.DataFrame:
    """Filtra por codRubr + ideTabRubr; None mantém o relatório completo."""
    if chaves is None:
        return df.copy()
    if df.empty or "cod_rubr" not in df.columns:
        return df.iloc[0:0].copy()
    tabelas = (
        df["ide_tab_rubr"].fillna("").astype(str)
        if "ide_tab_rubr" in df.columns
        else pd.Series("", index=df.index)
    )
    chaves_df = df["cod_rubr"].fillna("").astype(str) + "||" + tabelas
    return df[chaves_df.isin({str(chave) for chave in chaves})].copy()


def filtro_sql_chaves_rubricas(
    chaves: set[str] | list[str] | None, alias: str = ""
) -> str:
    """Produz condição SQL segura a partir de chaves vindas do próprio catálogo."""
    if chaves is None:
        return ""
    prefixo = f"{alias}." if alias else ""
    if not chaves:
        return "0=1"

    def literal(valor: str) -> str:
        return "'" + valor.replace("'", "''") + "'"

    pares = sorted({separar_chave_rubrica(chave) for chave in chaves})
    return "(" + " OR ".join(
        f"({prefixo}cod_rubr={literal(codigo)} AND "
        f"COALESCE({prefixo}ide_tab_rubr,'')={literal(tabela)})"
        for codigo, tabela in pares
    ) + ")"


def combinar_filtros_sql(filtro_existente: str, condicao: str) -> str:
    """Combina um WHERE opcional com a condição de rubricas."""
    filtro = str(filtro_existente or "").strip()
    if not condicao:
        return f" {filtro}" if filtro else ""
    if filtro:
        return f" {filtro} AND {condicao}"
    return f" WHERE {condicao}"
