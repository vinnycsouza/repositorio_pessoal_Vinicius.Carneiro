import io
from typing import Tuple

import pandas as pd


def classificar_natureza(nat_rubr: object, cod_inc_cp: object) -> str:
    nat = str(nat_rubr or "").strip()
    cod = str(cod_inc_cp or "").strip()
    if cod == "00":
        return "Nao incidente CP"
    if cod in {"11", "12", "13", "14", "15", "16", "21", "22", "23", "24", "25", "26"}:
        return "Incidente CP"
    if not nat:
        return "Nao classificada"
    if nat.startswith("9"):
        return "Provavel indenizatoria"
    if nat.startswith(("1", "2", "3")):
        return "Provavel remuneratoria"
    return "Revisar natureza"


def _garantir_colunas(df: pd.DataFrame, colunas: list[str], texto: bool = True) -> pd.DataFrame:
    base = df.copy()
    for col in colunas:
        if col not in base.columns:
            base[col] = "" if texto else 0.0
        if texto:
            base[col] = base[col].fillna("").astype(str)
    return base


def preparar_rubricas_sem_cadastro(df_remun: pd.DataFrame) -> pd.DataFrame:
    if df_remun.empty:
        return pd.DataFrame()

    base = _garantir_colunas(
        df_remun,
        ["cod_rubr", "ide_tab_rubr", "dsc_rubr", "nat_rubr", "cod_inc_cp", "per_apur", "cpf", "matricula"],
    )

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
        .agg(valor_rubrica=("vr_rubr", "sum"), qtd_lancamentos=("vr_rubr", "size"))
        .sort_values(["per_apur", "valor_rubrica"], ascending=[True, False])
    )
    saida["observacao"] = "Rubrica encontrada no S-1200 sem correspondencia no S-1010 utilizado no cruzamento."
    return saida


def gerar_composicao_teorica_base(df_remun: pd.DataFrame) -> pd.DataFrame:
    if df_remun.empty:
        return pd.DataFrame()

    base = _garantir_colunas(
        df_remun,
        [
            "cpf", "matricula", "per_apur", "cod_categ", "tp_insc_estab", "nr_insc_estab", "cod_lotacao",
            "cod_rubr", "ide_tab_rubr", "dsc_rubr", "nat_rubr", "cod_inc_cp",
        ],
    )
    base["vr_rubr"] = pd.to_numeric(base.get("vr_rubr", 0.0), errors="coerce").fillna(0.0)
    base["classificacao_rubrica"] = base.apply(lambda r: classificar_natureza(r["nat_rubr"], r["cod_inc_cp"]), axis=1)
    base["entra_base_teorica_cp"] = base["cod_inc_cp"].isin({"11", "12", "13", "14", "15", "16", "21", "22", "23", "24", "25", "26"})
    base["rubrica_nao_incidente_cp"] = base["cod_inc_cp"].eq("00")
    return base


def gerar_resumo_s5001(df_bases_trabalhador: pd.DataFrame) -> pd.DataFrame:
    if df_bases_trabalhador.empty:
        return pd.DataFrame()
    base = _garantir_colunas(
        df_bases_trabalhador,
        ["cpf", "matricula", "per_apur", "per_ref", "cod_categ", "tp_insc_estab", "nr_insc_estab", "cod_lotacao", "tp_valor", "origem_valor"],
    )
    base["valor"] = pd.to_numeric(base.get("valor", 0.0), errors="coerce").fillna(0.0)
    return (
        base[base["origem_valor"].eq("infoBaseCS")]
        .groupby(["cpf", "matricula", "per_apur", "cod_categ", "tp_insc_estab", "nr_insc_estab", "cod_lotacao", "tp_valor"], dropna=False, as_index=False)
        .agg(valor_s5001=("valor", "sum"), qtd_linhas_s5001=("valor", "size"))
        .sort_values(["per_apur", "cpf", "matricula", "tp_valor"])
    )


def gerar_conciliacao_s1200_s5001(df_remun: pd.DataFrame, df_bases_trabalhador: pd.DataFrame) -> pd.DataFrame:
    if df_remun.empty and df_bases_trabalhador.empty:
        return pd.DataFrame()

    comp = gerar_composicao_teorica_base(df_remun)
    if comp.empty:
        teorica = pd.DataFrame(columns=["cpf", "matricula", "per_apur", "cod_categ", "tp_insc_estab", "nr_insc_estab", "cod_lotacao", "base_teorica_cp", "rubricas_nao_incidentes", "total_s1200"])
    else:
        teorica = (
            comp.groupby(["cpf", "matricula", "per_apur", "cod_categ", "tp_insc_estab", "nr_insc_estab", "cod_lotacao"], dropna=False, as_index=False)
            .agg(
                total_s1200=("vr_rubr", "sum"),
                base_teorica_cp=("vr_rubr", lambda s: s[comp.loc[s.index, "entra_base_teorica_cp"]].sum()),
                rubricas_nao_incidentes=("vr_rubr", lambda s: s[comp.loc[s.index, "rubrica_nao_incidente_cp"]].sum()),
                qtd_rubricas=("cod_rubr", "count"),
                qtd_rubricas_sem_s1010=("cod_inc_cp", lambda s: (s.astype(str).str.strip() == "").sum()),
            )
        )

    s5001 = gerar_resumo_s5001(df_bases_trabalhador)
    if s5001.empty:
        oficial = pd.DataFrame(columns=["cpf", "matricula", "per_apur", "cod_categ", "tp_insc_estab", "nr_insc_estab", "cod_lotacao", "base_oficial_s5001"])
    else:
        # Mantemos a soma total do S-5001 por trabalhador/lotação e também as colunas por tpValor.
        idx = ["cpf", "matricula", "per_apur", "cod_categ", "tp_insc_estab", "nr_insc_estab", "cod_lotacao"]
        oficial = s5001.pivot_table(index=idx, columns="tp_valor", values="valor_s5001", aggfunc="sum", fill_value=0).reset_index()
        oficial.columns = [f"tpValor_{c}" if c not in idx else c for c in oficial.columns]
        valor_cols = [c for c in oficial.columns if c.startswith("tpValor_")]
        oficial["base_oficial_s5001"] = oficial[valor_cols].sum(axis=1) if valor_cols else 0.0

    chaves = ["cpf", "matricula", "per_apur", "cod_categ", "tp_insc_estab", "nr_insc_estab", "cod_lotacao"]
    conc = teorica.merge(oficial, on=chaves, how="outer").fillna(0)
    for col in ["total_s1200", "base_teorica_cp", "rubricas_nao_incidentes", "base_oficial_s5001"]:
        conc[col] = pd.to_numeric(conc.get(col, 0.0), errors="coerce").fillna(0.0)
    conc["diferenca_teorica_vs_s5001"] = conc["base_teorica_cp"] - conc["base_oficial_s5001"]
    conc["status_conciliacao"] = conc["diferenca_teorica_vs_s5001"].apply(lambda x: "OK" if abs(float(x)) <= 0.05 else "DIVERGENTE")
    return conc.sort_values(["status_conciliacao", "per_apur", "cpf", "matricula"])


def gerar_auditoria(
    df_rubricas: pd.DataFrame,
    df_remun: pd.DataFrame,
    df_bases_trabalhador: pd.DataFrame,
    df_bases_contribuicao: pd.DataFrame,
    aliquota_cpp_padrao: float = 20.0,
) -> pd.DataFrame:
    if df_remun.empty:
        return pd.DataFrame()

    comp = gerar_composicao_teorica_base(df_remun)
    if comp.empty:
        return pd.DataFrame()

    df_nao_inc = comp[comp["cod_inc_cp"].eq("00")].copy()
    if df_nao_inc.empty:
        return pd.DataFrame()

    chaves = ["cpf", "matricula", "per_apur", "cod_categ", "tp_insc_estab", "nr_insc_estab", "cod_lotacao"]
    s5001 = gerar_resumo_s5001(df_bases_trabalhador)
    if not s5001.empty:
        base_s5001_total = s5001.groupby(chaves, dropna=False, as_index=False).agg(base_oficial_s5001=("valor_s5001", "sum"))
    else:
        base_s5001_total = pd.DataFrame(columns=chaves + ["base_oficial_s5001"])

    agrupado = (
        df_nao_inc.groupby(
            chaves + ["cod_rubr", "ide_tab_rubr", "dsc_rubr", "nat_rubr", "cod_inc_cp", "classificacao_rubrica"],
            dropna=False,
            as_index=False,
        )
        .agg(valor_rubrica=("vr_rubr", "sum"), qtd_lancamentos=("vr_rubr", "size"))
    )

    auditoria = agrupado.merge(base_s5001_total, on=chaves, how="left")
    auditoria["base_oficial_s5001"] = pd.to_numeric(auditoria.get("base_oficial_s5001", 0.0), errors="coerce").fillna(0.0)
    auditoria["valor_sinalizado"] = auditoria.apply(lambda r: min(float(r["valor_rubrica"]), float(r["base_oficial_s5001"])) if float(r["base_oficial_s5001"]) > 0 else float(r["valor_rubrica"]), axis=1)
    auditoria["aliquota_cpp_padrao"] = float(aliquota_cpp_padrao)
    auditoria["cpp_potencial_estimada"] = auditoria["valor_sinalizado"] * (auditoria["aliquota_cpp_padrao"] / 100.0)
    auditoria["percentual_rubrica_sobre_s5001"] = auditoria.apply(lambda r: (r["valor_rubrica"] / r["base_oficial_s5001"] * 100.0) if r["base_oficial_s5001"] > 0 else 0.0, axis=1)

    def risco(row) -> str:
        if row["valor_rubrica"] <= 0:
            return "BAIXO"
        if row["base_oficial_s5001"] <= 0:
            return "MEDIO"
        if row["percentual_rubrica_sobre_s5001"] >= 20:
            return "ALTO"
        return "MEDIO"

    auditoria["grau_risco"] = auditoria.apply(risco, axis=1)
    auditoria["observacao"] = auditoria.apply(
        lambda r: "Rubrica codIncCP=00 encontrada no S-1200; confrontar se compôs indevidamente a base oficial do S-5001."
        if r["base_oficial_s5001"] > 0 else "Rubrica codIncCP=00 encontrada no S-1200, mas sem base oficial S-5001 compatível no recorte.",
        axis=1,
    )
    return auditoria.sort_values(["grau_risco", "cpp_potencial_estimada", "per_apur", "cpf"], ascending=[True, False, True, True])


def gerar_resumo_competencia(df_auditoria: pd.DataFrame) -> pd.DataFrame:
    if df_auditoria.empty:
        return pd.DataFrame()
    base = df_auditoria.copy()
    for col in ["valor_rubrica", "valor_sinalizado", "cpp_potencial_estimada"]:
        base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0.0)
    return (
        base.groupby("per_apur", as_index=False)
        .agg(qtd_linhas=("per_apur", "size"), qtd_cpfs=("cpf", "nunique"), valor_rubrica=("valor_rubrica", "sum"), valor_sinalizado=("valor_sinalizado", "sum"), cpp_potencial_estimada=("cpp_potencial_estimada", "sum"))
        .sort_values("per_apur")
    )


def gerar_ranking_cpf(df_auditoria: pd.DataFrame, top_n: int = 50) -> pd.DataFrame:
    if df_auditoria.empty:
        return pd.DataFrame()
    base = df_auditoria.copy()
    for col in ["valor_rubrica", "valor_sinalizado", "cpp_potencial_estimada"]:
        base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0.0)
    return (
        base.groupby(["cpf", "matricula"], as_index=False)
        .agg(qtd_competencias=("per_apur", "nunique"), valor_rubrica=("valor_rubrica", "sum"), valor_sinalizado=("valor_sinalizado", "sum"), cpp_potencial_estimada=("cpp_potencial_estimada", "sum"))
        .sort_values(["cpp_potencial_estimada", "valor_sinalizado"], ascending=[False, False])
        .head(top_n)
    )


def gerar_resumo_execucao(df_rubricas: pd.DataFrame, df_remun: pd.DataFrame, df_auditoria: pd.DataFrame, df_sem_cadastro: pd.DataFrame, df_bases_trabalhador: pd.DataFrame | None = None) -> pd.DataFrame:
    linhas = [
        {"indicador": "Rubricas S-1010", "valor": int(len(df_rubricas))},
        {"indicador": "Lancamentos S-1200", "valor": int(len(df_remun))},
        {"indicador": "Linhas S-5001 detalhadas", "valor": int(len(df_bases_trabalhador)) if df_bases_trabalhador is not None else 0},
        {"indicador": "Linhas auditoria", "valor": int(len(df_auditoria))},
        {"indicador": "Rubricas sem S-1010", "valor": int(len(df_sem_cadastro))},
    ]
    if not df_auditoria.empty:
        linhas.extend([
            {"indicador": "Risco ALTO", "valor": int((df_auditoria["grau_risco"] == "ALTO").sum())},
            {"indicador": "Risco MEDIO", "valor": int((df_auditoria["grau_risco"] == "MEDIO").sum())},
            {"indicador": "CPP potencial estimada", "valor": float(pd.to_numeric(df_auditoria["cpp_potencial_estimada"], errors="coerce").fillna(0.0).sum())},
        ])
    return pd.DataFrame(linhas)


def preparar_pacote_analitico(df_rubricas: pd.DataFrame, df_remun: pd.DataFrame, df_bases_trabalhador: pd.DataFrame, df_bases_contribuicao: pd.DataFrame, aliquota_cpp_padrao: float = 20.0):
    df_auditoria = gerar_auditoria(df_rubricas, df_remun, df_bases_trabalhador, df_bases_contribuicao, aliquota_cpp_padrao)
    df_sem_cadastro = preparar_rubricas_sem_cadastro(df_remun)
    df_comp = gerar_resumo_competencia(df_auditoria)
    df_ranking = gerar_ranking_cpf(df_auditoria)
    df_composicao = gerar_composicao_teorica_base(df_remun)
    df_conciliacao = gerar_conciliacao_s1200_s5001(df_remun, df_bases_trabalhador)
    df_s5001_resumo = gerar_resumo_s5001(df_bases_trabalhador)
    return df_auditoria, df_sem_cadastro, df_comp, df_ranking, df_composicao, df_conciliacao, df_s5001_resumo


def gerar_excel_saida(df_inventario: pd.DataFrame, df_rubricas: pd.DataFrame, df_exclusoes: pd.DataFrame, df_remun: pd.DataFrame, df_bases_trabalhador: pd.DataFrame, df_bases_contribuicao: pd.DataFrame, df_auditoria: pd.DataFrame, df_erros: pd.DataFrame, df_layout: pd.DataFrame, df_sem_cadastro: pd.DataFrame, df_competencia: pd.DataFrame, df_ranking_cpf: pd.DataFrame, df_resumo_execucao: pd.DataFrame, df_composicao_teorica: pd.DataFrame | None = None, df_conciliacao: pd.DataFrame | None = None, df_s5001_resumo: pd.DataFrame | None = None) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_resumo_execucao.to_excel(writer, sheet_name="resumo_execucao", index=False)
        df_competencia.to_excel(writer, sheet_name="resumo_competencia", index=False)
        df_ranking_cpf.to_excel(writer, sheet_name="ranking_cpf", index=False)
        (df_conciliacao if df_conciliacao is not None else pd.DataFrame()).to_excel(writer, sheet_name="conciliacao_s1200_s5001", index=False)
        (df_composicao_teorica if df_composicao_teorica is not None else pd.DataFrame()).to_excel(writer, sheet_name="composicao_teorica", index=False)
        (df_s5001_resumo if df_s5001_resumo is not None else pd.DataFrame()).to_excel(writer, sheet_name="resumo_s5001_tpvalor", index=False)
        df_sem_cadastro.to_excel(writer, sheet_name="rubricas_sem_s1010", index=False)
        df_inventario.to_excel(writer, sheet_name="inventario", index=False)
        df_layout.to_excel(writer, sheet_name="checagem_layout", index=False)
        df_rubricas.to_excel(writer, sheet_name="rubricas_s1010", index=False)
        df_exclusoes.to_excel(writer, sheet_name="exclusoes_s3000", index=False)
        df_remun.to_excel(writer, sheet_name="remuneracao_s1200", index=False)
        df_bases_trabalhador.to_excel(writer, sheet_name="bases_s5001_detalhe", index=False)
        df_bases_contribuicao.to_excel(writer, sheet_name="bases_s5011", index=False)
        df_auditoria.to_excel(writer, sheet_name="auditoria_cpp", index=False)
        df_erros.to_excel(writer, sheet_name="erros_xml", index=False)
    output.seek(0)
    return output.getvalue()
