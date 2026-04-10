import io
import pandas as pd



def gerar_auditoria(
    df_rubricas: pd.DataFrame,
    df_remun: pd.DataFrame,
    df_bases_trabalhador: pd.DataFrame,
    df_bases_contribuicao: pd.DataFrame,
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
    ]:
        df[col] = df[col].fillna("").astype(str)

    df_nao_inc = df[df["cod_inc_cp"] == "00"].copy()
    if df_nao_inc.empty:
        return pd.DataFrame()

    if df_bases_contribuicao.empty:
        df_base_resumo = pd.DataFrame(
            columns=["per_apur", "tp_insc_estab", "nr_insc_estab", "cod_lotacao", "cod_categ", "vr_bc_cp"]
        )
    else:
        base = df_bases_contribuicao.copy()
        for col in ["per_apur", "tp_insc_estab", "nr_insc_estab", "cod_lotacao", "cod_categ"]:
            base[col] = base[col].fillna("").astype(str)
        df_base_resumo = (
            base.groupby(["per_apur", "tp_insc_estab", "nr_insc_estab", "cod_lotacao", "cod_categ"], dropna=False, as_index=False)
            .agg(vr_bc_cp=("vr_bc_cp", "sum"))
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

    auditoria["vr_bc_cp"] = auditoria["vr_bc_cp"].fillna(0.0)
    auditoria["entrou_em_base_cp"] = auditoria["vr_bc_cp"] > 0
    auditoria["valor_sinalizado"] = auditoria.apply(
        lambda row: row["valor_rubrica"] if row["entrou_em_base_cp"] else 0.0,
        axis=1,
    )

    def classificar_risco(row):
        if row["cod_inc_cp"] == "00" and row["valor_rubrica"] > 0 and row["vr_bc_cp"] > 0:
            return "ALTO"
        if row["cod_inc_cp"] == "00" and row["valor_rubrica"] > 0:
            return "MEDIO"
        return "BAIXO"

    auditoria["grau_risco"] = auditoria.apply(classificar_risco, axis=1)
    auditoria["observacao"] = auditoria.apply(
        lambda row: (
            "Rubrica com codIncCP=00 no S-1200 e existência de base patronal no S-5011 para o mesmo período/categoria/lotação. Validar a composição exata da base."
            if row["grau_risco"] == "ALTO"
            else (
                "Rubrica com codIncCP=00 localizada no S-1200, sem base patronal compatível no cruzamento atual."
                if row["grau_risco"] == "MEDIO"
                else "Sem sinalização relevante."
            )
        ),
        axis=1,
    )

    if not df_bases_trabalhador.empty:
        base_trab = df_bases_trabalhador.copy()
        for col in ["cpf", "matricula", "per_apur", "cod_categ"]:
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
        by=["grau_risco", "per_apur", "nr_insc_estab", "cod_lotacao", "cpf", "cod_rubr"],
        ascending=[True, True, True, True, True, True],
    )
    return auditoria



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
) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
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
