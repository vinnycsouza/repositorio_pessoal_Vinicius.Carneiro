import io
import pandas as pd



def gerar_auditoria(df_rubricas: pd.DataFrame, df_remun: pd.DataFrame, df_bases: pd.DataFrame) -> pd.DataFrame:
    if df_remun.empty:
        return pd.DataFrame()

    df_remun = df_remun.copy()
    df_remun["cod_inc_cp"] = df_remun["cod_inc_cp"].fillna("").astype(str)
    df_remun["dsc_rubr"] = df_remun["dsc_rubr"].fillna("")
    df_remun["nat_rubr"] = df_remun["nat_rubr"].fillna("")
    df_remun["cpf"] = df_remun["cpf"].fillna("")
    df_remun["matricula"] = df_remun["matricula"].fillna("")
    df_remun["per_apur"] = df_remun["per_apur"].fillna("")

    df_nao_inc = df_remun[df_remun["cod_inc_cp"] == "00"].copy()
    if df_nao_inc.empty:
        return pd.DataFrame()

    if df_bases.empty:
        df_base_resumo = pd.DataFrame(columns=["cpf", "matricula", "per_apur", "base_cp", "base_seg", "vr_desc_seg"])
    else:
        df_base_resumo = (
            df_bases.groupby(["cpf", "matricula", "per_apur"], dropna=False, as_index=False)
            .agg(
                base_cp=("base_cp", "sum"),
                base_seg=("base_seg", "sum"),
                vr_desc_seg=("vr_desc_seg", "sum"),
            )
        )

    agrupado = (
        df_nao_inc.groupby(
            ["cpf", "matricula", "per_apur", "cod_rubr", "ide_tab_rubr", "dsc_rubr", "nat_rubr", "cod_inc_cp"],
            dropna=False,
            as_index=False,
        )
        .agg(
            valor_rubrica=("vr_rubr", "sum"),
            qtd_lancamentos=("vr_rubr", "size"),
        )
    )

    auditoria = agrupado.merge(
        df_base_resumo,
        on=["cpf", "matricula", "per_apur"],
        how="left",
    )

    auditoria["base_cp"] = auditoria["base_cp"].fillna(0.0)
    auditoria["base_seg"] = auditoria["base_seg"].fillna(0.0)
    auditoria["vr_desc_seg"] = auditoria["vr_desc_seg"].fillna(0.0)

    auditoria["entrou_em_base_cp"] = auditoria["base_cp"] > 0
    auditoria["valor_sinalizado"] = auditoria.apply(
        lambda row: row["valor_rubrica"] if row["entrou_em_base_cp"] else 0.0,
        axis=1,
    )

    auditoria["grau_risco"] = auditoria.apply(
        lambda row: "ALTO" if row["cod_inc_cp"] == "00" and row["base_cp"] > 0 and row["valor_rubrica"] > 0 else "BAIXO",
        axis=1,
    )

    auditoria["observacao"] = auditoria.apply(
        lambda row: (
            "Rubrica com codIncCP=00 e existência de base previdenciária no S-5001 para o mesmo CPF/matrícula/período. Exige validação final da composição da base."
            if row["grau_risco"] == "ALTO"
            else "Sem sinalização automática relevante no cruzamento inicial."
        ),
        axis=1,
    )

    return auditoria.sort_values(
        by=["grau_risco", "per_apur", "cpf", "cod_rubr"],
        ascending=[True, True, True, True],
    )



def gerar_excel_saida(
    df_inventario: pd.DataFrame,
    df_rubricas: pd.DataFrame,
    df_exclusoes: pd.DataFrame,
    df_remun: pd.DataFrame,
    df_bases: pd.DataFrame,
    df_auditoria: pd.DataFrame,
    df_erros: pd.DataFrame,
) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_inventario.to_excel(writer, sheet_name="inventario", index=False)
        df_rubricas.to_excel(writer, sheet_name="rubricas_s1010", index=False)
        df_exclusoes.to_excel(writer, sheet_name="exclusoes_s3000", index=False)
        df_remun.to_excel(writer, sheet_name="remuneracao_s1200", index=False)
        df_bases.to_excel(writer, sheet_name="bases_s5001", index=False)
        df_auditoria.to_excel(writer, sheet_name="auditoria_cpp", index=False)
        df_erros.to_excel(writer, sheet_name="erros_xml", index=False)
    output.seek(0)
    return output.getvalue()
