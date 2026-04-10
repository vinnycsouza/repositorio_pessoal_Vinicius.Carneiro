import io
from typing import Tuple

import pandas as pd


def classificar_natureza(nat_rubr: object, cod_inc_cp: object) -> str:
    nat = str(nat_rubr or "").strip()
    cod = str(cod_inc_cp or "").strip()
    if cod == "00":
        return "Nao incidente CP"
    if not nat:
        return "Nao classificada"
    if nat.startswith("9"):
        return "Provavel indenizatoria"
    if nat.startswith(("1", "2", "3")):
        return "Provavel remuneratoria"
    return "Revisar natureza"


def preparar_rubricas_sem_cadastro(df_remun: pd.DataFrame) -> pd.DataFrame:
    if df_remun.empty:
        return pd.DataFrame()

    base = df_remun.copy()
    for col in [
        "cod_rubr",
        "ide_tab_rubr",
        "dsc_rubr",
        "nat_rubr",
        "cod_inc_cp",
        "per_apur",
        "cpf",
        "matricula",
    ]:
        if col not in base.columns:
            base[col] = ""
        base[col] = base[col].fillna("").astype(str)

    sem = base[
        (base["cod_rubr"] != "")
        & (base["cod_inc_cp"] == "")
        & (base["dsc_rubr"] == "")
        & (base["nat_rubr"] == "")
    ].copy()

    if sem.empty:
        return pd.DataFrame()

    saida = (
        sem.groupby(["per_apur", "cpf", "matricula", "cod_rubr", "ide_tab_rubr"], as_index=False)
        .agg(
            valor_rubrica=("vr_rubr", "sum"),
            qtd_lancamentos=("vr_rubr", "size"),
        )
        .sort_values(["per_apur", "valor_rubrica"], ascending=[True, False])
    )
    saida["observacao"] = "Rubrica encontrada no S-1200 sem correspondencia no S-1010 utilizado no cruzamento."
    return saida


def gerar_auditoria(
    df_rubricas: pd.DataFrame,
    df_remun: pd.DataFrame,
    df_bases_trabalhador: pd.DataFrame,
    df_bases_contribuicao: pd.DataFrame,
    aliquota_cpp_padrao: float = 20.0,
) -> pd.DataFrame:
    if df_remun.empty:
        return pd.DataFrame()

    df = df_remun.copy()
    for col in [
        "cod_inc_cp",
        "dsc_rubr",
        "nat_rubr",
        "cpf",
        "matricula",
        "per_apur",
        "cod_categ",
        "tp_insc_estab",
        "nr_insc_estab",
        "cod_lotacao",
        "cod_rubr",
        "ide_tab_rubr",
    ]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)

    if "vr_rubr" not in df.columns:
        return pd.DataFrame()

    df["classificacao_rubrica"] = df.apply(
        lambda row: classificar_natureza(row.get("nat_rubr"), row.get("cod_inc_cp")), axis=1
    )

    df_nao_inc = df[df["cod_inc_cp"] == "00"].copy()
    if df_nao_inc.empty:
        return pd.DataFrame()

    if df_bases_contribuicao.empty:
        df_base_resumo = pd.DataFrame(
            columns=[
                "per_apur",
                "tp_insc_estab",
                "nr_insc_estab",
                "cod_lotacao",
                "cod_categ",
                "vr_bc_cp",
                "aliq_rat_ajust_media",
            ]
        )
    else:
        base = df_bases_contribuicao.copy()
        for col in ["per_apur", "tp_insc_estab", "nr_insc_estab", "cod_lotacao", "cod_categ"]:
            if col not in base.columns:
                base[col] = ""
            base[col] = base[col].fillna("").astype(str)
        for col in ["vr_bc_cp", "aliq_rat_ajust"]:
            if col not in base.columns:
                base[col] = 0.0
            base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0.0)
        df_base_resumo = (
            base.groupby(["per_apur", "tp_insc_estab", "nr_insc_estab", "cod_lotacao", "cod_categ"], dropna=False, as_index=False)
            .agg(
                vr_bc_cp=("vr_bc_cp", "sum"),
                aliq_rat_ajust_media=("aliq_rat_ajust", "mean"),
            )
        )

    agrupado = (
        df_nao_inc.groupby(
            [
                "cpf",
                "matricula",
                "per_apur",
                "cod_categ",
                "tp_insc_estab",
                "nr_insc_estab",
                "cod_lotacao",
                "cod_rubr",
                "ide_tab_rubr",
                "dsc_rubr",
                "nat_rubr",
                "cod_inc_cp",
                "classificacao_rubrica",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(valor_rubrica=("vr_rubr", "sum"), qtd_lancamentos=("vr_rubr", "size"))
    )

    auditoria = agrupado.merge(
        df_base_resumo,
        on=["per_apur", "tp_insc_estab", "nr_insc_estab", "cod_lotacao", "cod_categ"],
        how="left",
    )

    for col in ["vr_bc_cp", "aliq_rat_ajust_media"]:
        auditoria[col] = pd.to_numeric(auditoria.get(col, 0.0), errors="coerce").fillna(0.0)

    auditoria["entrou_em_base_cp"] = auditoria["vr_bc_cp"] > 0
    auditoria["percentual_rubrica_sobre_base"] = auditoria.apply(
        lambda row: (row["valor_rubrica"] / row["vr_bc_cp"] * 100.0) if row["vr_bc_cp"] > 0 else 0.0,
        axis=1,
    )
    auditoria["valor_sinalizado"] = auditoria.apply(
        lambda row: min(row["valor_rubrica"], row["vr_bc_cp"]) if row["vr_bc_cp"] > 0 else 0.0,
        axis=1,
    )
    auditoria["aliquota_cpp_padrao"] = float(aliquota_cpp_padrao)
    auditoria["cpp_potencial_estimada"] = auditoria["valor_sinalizado"] * (auditoria["aliquota_cpp_padrao"] / 100.0)

    def classificar_risco(row) -> str:
        if row["cod_inc_cp"] != "00" or row["valor_rubrica"] <= 0:
            return "BAIXO"
        if row["vr_bc_cp"] <= 0:
            return "MEDIO"
        if row["percentual_rubrica_sobre_base"] >= 70:
            return "ALTO"
        return "MEDIO"

    auditoria["grau_risco"] = auditoria.apply(classificar_risco, axis=1)

    def observacao(row) -> str:
        if row["grau_risco"] == "ALTO":
            return (
                "Rubrica com codIncCP=00 e peso relevante sobre a base patronal do mesmo periodo/categoria/lotacao. Prioridade alta de validacao."
            )
        if row["grau_risco"] == "MEDIO":
            return (
                "Rubrica com codIncCP=00 localizada no S-1200; existe base patronal no recorte consolidado, mas a composicao exata ainda precisa ser confirmada."
                if row["vr_bc_cp"] > 0
                else "Rubrica com codIncCP=00 sem base patronal compativel no cruzamento atual."
            )
        return "Sem sinalizacao relevante."

    auditoria["observacao"] = auditoria.apply(observacao, axis=1)

    if not df_bases_trabalhador.empty:
        base_trab = df_bases_trabalhador.copy()
        for col in ["cpf", "matricula", "per_apur", "cod_categ"]:
            if col not in base_trab.columns:
                base_trab[col] = ""
            base_trab[col] = base_trab[col].fillna("").astype(str)
        resumo_trab = (
            base_trab.groupby(["cpf", "matricula", "per_apur", "cod_categ"], dropna=False, as_index=False)
            .agg(qtd_s5001=("arquivo", "count"))
        )
        auditoria = auditoria.merge(
            resumo_trab,
            on=["cpf", "matricula", "per_apur", "cod_categ"],
            how="left",
        )
        auditoria["qtd_s5001"] = auditoria["qtd_s5001"].fillna(0).astype(int)
    else:
        auditoria["qtd_s5001"] = 0

    auditoria = auditoria.sort_values(
        by=["grau_risco", "cpp_potencial_estimada", "per_apur", "nr_insc_estab", "cod_lotacao", "cpf", "cod_rubr"],
        ascending=[True, False, True, True, True, True, True],
    )
    return auditoria


def gerar_resumo_competencia(df_auditoria: pd.DataFrame) -> pd.DataFrame:
    if df_auditoria.empty:
        return pd.DataFrame()
    base = df_auditoria.copy()
    for col in ["valor_rubrica", "valor_sinalizado", "cpp_potencial_estimada"]:
        base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0.0)
    saida = (
        base.groupby("per_apur", as_index=False)
        .agg(
            qtd_linhas=("per_apur", "size"),
            qtd_cpfs=("cpf", "nunique"),
            valor_rubrica=("valor_rubrica", "sum"),
            valor_sinalizado=("valor_sinalizado", "sum"),
            cpp_potencial_estimada=("cpp_potencial_estimada", "sum"),
        )
        .sort_values("per_apur")
    )
    return saida


def gerar_ranking_cpf(df_auditoria: pd.DataFrame, top_n: int = 50) -> pd.DataFrame:
    if df_auditoria.empty:
        return pd.DataFrame()
    base = df_auditoria.copy()
    for col in ["valor_rubrica", "valor_sinalizado", "cpp_potencial_estimada"]:
        base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0.0)
    saida = (
        base.groupby(["cpf", "matricula"], as_index=False)
        .agg(
            qtd_competencias=("per_apur", "nunique"),
            valor_rubrica=("valor_rubrica", "sum"),
            valor_sinalizado=("valor_sinalizado", "sum"),
            cpp_potencial_estimada=("cpp_potencial_estimada", "sum"),
        )
        .sort_values(["cpp_potencial_estimada", "valor_sinalizado"], ascending=[False, False])
        .head(top_n)
    )
    return saida


def gerar_resumo_execucao(
    df_rubricas: pd.DataFrame,
    df_remun: pd.DataFrame,
    df_auditoria: pd.DataFrame,
    df_sem_cadastro: pd.DataFrame,
) -> pd.DataFrame:
    linhas = [
        {"indicador": "Rubricas S-1010", "valor": int(len(df_rubricas))},
        {"indicador": "Lancamentos S-1200", "valor": int(len(df_remun))},
        {"indicador": "Linhas auditoria", "valor": int(len(df_auditoria))},
        {"indicador": "Rubricas sem S-1010", "valor": int(len(df_sem_cadastro))},
    ]
    if not df_auditoria.empty:
        linhas.extend(
            [
                {"indicador": "Risco ALTO", "valor": int((df_auditoria["grau_risco"] == "ALTO").sum())},
                {"indicador": "Risco MEDIO", "valor": int((df_auditoria["grau_risco"] == "MEDIO").sum())},
                {"indicador": "CPP potencial estimada", "valor": float(pd.to_numeric(df_auditoria["cpp_potencial_estimada"], errors="coerce").fillna(0.0).sum())},
            ]
        )
    return pd.DataFrame(linhas)


def preparar_pacote_analitico(
    df_rubricas: pd.DataFrame,
    df_remun: pd.DataFrame,
    df_bases_trabalhador: pd.DataFrame,
    df_bases_contribuicao: pd.DataFrame,
    aliquota_cpp_padrao: float = 20.0,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df_auditoria = gerar_auditoria(
        df_rubricas=df_rubricas,
        df_remun=df_remun,
        df_bases_trabalhador=df_bases_trabalhador,
        df_bases_contribuicao=df_bases_contribuicao,
        aliquota_cpp_padrao=aliquota_cpp_padrao,
    )
    df_sem_cadastro = preparar_rubricas_sem_cadastro(df_remun)
    df_comp = gerar_resumo_competencia(df_auditoria)
    df_ranking = gerar_ranking_cpf(df_auditoria)
    return df_auditoria, df_sem_cadastro, df_comp, df_ranking


def gerar_excel_saida(
    df_inventario: pd.DataFrame,
    df_rubricas: pd.DataFrame,
    df_exclusoes: pd.DataFrame,
    df_remun: pd.DataFrame,
    df_bases_trabalhador: pd.DataFrame,
    df_bases_contribuicao: pd.DataFrame,
    df_auditoria: pd.DataFrame,
    df_erros: pd.DataFrame,
    df_layout: pd.DataFrame,
    df_sem_cadastro: pd.DataFrame,
    df_competencia: pd.DataFrame,
    df_ranking_cpf: pd.DataFrame,
    df_resumo_execucao: pd.DataFrame,
) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_resumo_execucao.to_excel(writer, sheet_name="resumo_execucao", index=False)
        df_competencia.to_excel(writer, sheet_name="resumo_competencia", index=False)
        df_ranking_cpf.to_excel(writer, sheet_name="ranking_cpf", index=False)
        df_sem_cadastro.to_excel(writer, sheet_name="rubricas_sem_s1010", index=False)
        df_inventario.to_excel(writer, sheet_name="inventario", index=False)
        df_layout.to_excel(writer, sheet_name="checagem_layout", index=False)
        df_rubricas.to_excel(writer, sheet_name="rubricas_s1010", index=False)
        df_exclusoes.to_excel(writer, sheet_name="exclusoes_s3000", index=False)
        df_remun.to_excel(writer, sheet_name="remuneracao_s1200", index=False)
        df_bases_trabalhador.to_excel(writer, sheet_name="bases_s5001", index=False)
        df_bases_contribuicao.to_excel(writer, sheet_name="bases_s5011", index=False)
        df_auditoria.to_excel(writer, sheet_name="auditoria_cpp", index=False)
        df_erros.to_excel(writer, sheet_name="erros_xml", index=False)
    output.seek(0)
    return output.getvalue()
