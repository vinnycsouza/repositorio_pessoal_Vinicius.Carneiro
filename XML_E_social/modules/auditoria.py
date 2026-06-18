import io
import re

import pandas as pd

CODIGOS_INCIDENTES_CP = {"11", "12", "13", "14", "15", "16", "21", "22", "23", "24", "25", "26"}
CODIGOS_CP_EXPORTACAO_PADRAO = {"11", "12", "21", "22"}

PALAVRAS_TECNICAS = (
    "base de calculo", "base cálculo", "base inss", "base previd", "inss base", "fgts base",
    "irrf", "imposto de renda", "desconto", "deducao", "dedução", "liquido", "líquido",
    "totalizador", "informativa", "informativo", "salario contribuicao", "salário contribuição",
)

PALAVRAS_RESCISORIAS = (
    "rescis", "deslig", "aviso previo", "aviso prévio", "multa", "indeniz", "saldo salario", "saldo salário",
    "ferias venc", "férias venc", "ferias propor", "férias propor", "13 proporcional", "decimo terceiro proporcional",
)

PALAVRAS_FERIAS = ("ferias", "férias", "1/3", "terco", "terço")
PALAVRAS_13 = ("13", "decimo terceiro", "décimo terceiro", "gratificacao natalina", "gratificação natalina")
PALAVRAS_REMUNERATORIAS = (
    "salario", "salário", "remuneracao", "remuneração", "hora", "extra", "adicional", "comissao", "comissão",
    "dsr", "descanso", "noturno", "periculosidade", "insalubridade", "gratificacao", "gratificação",
    "premio", "prêmio", "produtividade", "quinquenio", "anuenio", "triênio", "trienio",
)


def _texto_limpo(valor: object) -> str:
    return str(valor or "").strip()


def _texto_busca(valor: object) -> str:
    texto = _texto_limpo(valor).lower()
    mapa = str.maketrans("áàâãéêíóôõúç", "aaaaeeiooouc")
    return texto.translate(mapa)


def _garantir_colunas(df: pd.DataFrame, colunas: list[str], texto: bool = True) -> pd.DataFrame:
    base = df.copy()
    for col in colunas:
        if col not in base.columns:
            base[col] = "" if texto else 0.0
        if texto:
            base[col] = base[col].fillna("").astype(str)
    return base


def classificar_status_cp(cod_inc_cp: object) -> str:
    cod = _texto_limpo(cod_inc_cp)
    if cod == "":
        return "Sem S-1010"
    if cod == "00":
        return "Não incide CP"
    if cod in CODIGOS_INCIDENTES_CP:
        return "Incide CP"
    return "Revisar codIncCP"


def entra_base_cp(cod_inc_cp: object) -> bool:
    return _texto_limpo(cod_inc_cp) in CODIGOS_INCIDENTES_CP


def classificar_tipo_verba(descricao: object, nat_rubr: object = "", tp_rubr: object = "") -> str:
    desc = _texto_busca(descricao)
    nat = _texto_limpo(nat_rubr)
    tp = _texto_limpo(tp_rubr)

    if any(p in desc for p in PALAVRAS_TECNICAS):
        return "Informativa/Técnica"
    if tp == "2":
        return "Desconto"
    if any(p in desc for p in PALAVRAS_RESCISORIAS):
        return "Rescisória"
    if any(p in desc for p in PALAVRAS_13):
        return "13º salário"
    if any(p in desc for p in PALAVRAS_FERIAS):
        return "Férias"
    if any(p in desc for p in PALAVRAS_REMUNERATORIAS):
        return "Remuneratória"
    if nat.startswith("6") or nat.startswith("7") or nat.startswith("9"):
        return "Informativa/Técnica"
    if nat.startswith(("1", "2", "3")):
        return "Remuneratória"
    return "Não classificada"


def classificar_carater(descricao: object, nat_rubr: object = "", tp_rubr: object = "") -> str:
    tipo = classificar_tipo_verba(descricao, nat_rubr, tp_rubr)
    if tipo in {"Remuneratória", "Férias", "13º salário"}:
        return "Remuneratório"
    if tipo == "Rescisória":
        return "Rescisório"
    if tipo == "Desconto":
        return "Desconto"
    if tipo == "Informativa/Técnica":
        return "Informativo/Técnico"
    return "Revisar"


def preparar_movimentos_cp(df_remun: pd.DataFrame) -> pd.DataFrame:
    if df_remun.empty:
        return pd.DataFrame()

    base = _garantir_colunas(
        df_remun,
        [
            "per_apur", "cpf", "matricula", "cod_categ", "tp_insc_estab", "nr_insc_estab", "cod_lotacao",
            "cod_rubr", "ide_tab_rubr", "dsc_rubr", "nat_rubr", "cod_inc_cp", "tp_rubr", "arquivo",
        ],
    )
    base["vr_rubr"] = pd.to_numeric(base.get("vr_rubr", 0.0), errors="coerce").fillna(0.0)
    base["status_cp"] = base["cod_inc_cp"].apply(classificar_status_cp)
    base["considerado_cp"] = base["cod_inc_cp"].apply(lambda x: "Sim" if entra_base_cp(x) else "Não")
    base["tipo_verba"] = base.apply(lambda r: classificar_tipo_verba(r["dsc_rubr"], r["nat_rubr"], r["tp_rubr"]), axis=1)
    base["carater_verba"] = base.apply(lambda r: classificar_carater(r["dsc_rubr"], r["nat_rubr"], r["tp_rubr"]), axis=1)
    base["observacao"] = base.apply(_observacao_movimento, axis=1)

    ordem = [
        "per_apur", "cpf", "matricula", "cod_categ", "cod_lotacao", "cod_rubr", "ide_tab_rubr",
        "dsc_rubr", "nat_rubr", "tp_rubr", "cod_inc_cp", "status_cp", "considerado_cp",
        "tipo_verba", "carater_verba", "vr_rubr", "tp_insc_estab", "nr_insc_estab", "observacao", "arquivo",
    ]
    return base[[c for c in ordem if c in base.columns]].sort_values(["per_apur", "cpf", "matricula", "considerado_cp", "dsc_rubr"])


def _observacao_movimento(row: pd.Series) -> str:
    status = row.get("status_cp", "")
    tipo = row.get("tipo_verba", "")
    if status == "Sem S-1010":
        return "Rubrica lançada no S-1200 sem correspondência na tabela S-1010 carregada."
    if status == "Incide CP" and tipo == "Informativa/Técnica":
        return "Verificar: descrição sugere rubrica técnica/informativa, mas codIncCP indica incidência."
    if status == "Não incide CP" and tipo in {"Remuneratória", "Férias", "13º salário"}:
        return "Verificar: descrição sugere verba remuneratória, mas codIncCP está sem incidência."
    if status == "Revisar codIncCP":
        return "Código de incidência CP fora da regra simples; revisar no leiaute/tabela do eSocial."
    return ""


def gerar_relatorio_rubricas_cp(df_remun: pd.DataFrame) -> pd.DataFrame:
    mov = preparar_movimentos_cp(df_remun)
    if mov.empty:
        return pd.DataFrame()

    agrupado = (
        mov.groupby(
            ["cod_rubr", "ide_tab_rubr", "dsc_rubr", "nat_rubr", "tp_rubr", "cod_inc_cp", "status_cp", "considerado_cp", "tipo_verba", "carater_verba"],
            dropna=False,
            as_index=False,
        )
        .agg(
            valor_total=("vr_rubr", "sum"),
            qtd_lancamentos=("vr_rubr", "size"),
            qtd_cpfs=("cpf", "nunique"),
            primeira_competencia=("per_apur", "min"),
            ultima_competencia=("per_apur", "max"),
        )
    )
    agrupado["prioridade_revisao"] = agrupado.apply(_prioridade_rubrica, axis=1)
    agrupado["observacao"] = agrupado.apply(_observacao_rubrica, axis=1)
    ordem = [
        "status_cp", "considerado_cp", "carater_verba", "tipo_verba", "cod_rubr", "ide_tab_rubr", "dsc_rubr", "nat_rubr", "tp_rubr", "cod_inc_cp",
        "valor_total", "qtd_lancamentos", "qtd_cpfs", "primeira_competencia", "ultima_competencia", "prioridade_revisao", "observacao",
    ]
    return agrupado[ordem].sort_values(["status_cp", "carater_verba", "valor_total"], ascending=[True, True, False])


def _prioridade_rubrica(row: pd.Series) -> str:
    status = row.get("status_cp", "")
    tipo = row.get("tipo_verba", "")
    valor = float(row.get("valor_total", 0) or 0)
    if status == "Sem S-1010":
        return "Alta"
    if status == "Incide CP" and tipo == "Informativa/Técnica":
        return "Alta"
    if status == "Não incide CP" and tipo in {"Remuneratória", "Férias", "13º salário"}:
        return "Média"
    if status == "Revisar codIncCP":
        return "Média"
    if valor == 0:
        return "Baixa"
    return "Normal"


def _observacao_rubrica(row: pd.Series) -> str:
    status = row.get("status_cp", "")
    tipo = row.get("tipo_verba", "")
    if status == "Incide CP":
        return "Rubrica considerada na incidência de CP conforme codIncCP."
    if status == "Não incide CP":
        return "Rubrica não considerada na incidência de CP conforme codIncCP."
    if status == "Sem S-1010":
        return "Necessário carregar o S-1010 correspondente ou revisar código/tabela da rubrica."
    return "Revisar código de incidência CP."


def gerar_base_trabalhador_cp(df_remun: pd.DataFrame, df_bases_trabalhador: pd.DataFrame) -> pd.DataFrame:
    mov = preparar_movimentos_cp(df_remun)
    chaves = ["per_apur", "cpf", "matricula", "cod_categ", "cod_lotacao"]

    if mov.empty:
        teorica = pd.DataFrame(columns=chaves + ["total_s1200", "total_incide_cp", "total_nao_incide_cp", "qtd_rubricas_sem_s1010"])
    else:
        teorica = (
            mov.groupby(chaves, dropna=False, as_index=False)
            .agg(
                total_s1200=("vr_rubr", "sum"),
                total_incide_cp=("vr_rubr", lambda s: s[mov.loc[s.index, "considerado_cp"].eq("Sim")].sum()),
                total_nao_incide_cp=("vr_rubr", lambda s: s[mov.loc[s.index, "status_cp"].eq("Não incide CP")].sum()),
                qtd_rubricas=("cod_rubr", "count"),
                qtd_rubricas_sem_s1010=("status_cp", lambda s: s.eq("Sem S-1010").sum()),
            )
        )

    s5001 = gerar_resumo_s5001(df_bases_trabalhador)
    if s5001.empty:
        oficial = pd.DataFrame(columns=chaves + ["total_s5001_infoBaseCS"])
    else:
        b = s5001.copy()
        for col in chaves:
            if col not in b.columns:
                b[col] = ""
        oficial = b.groupby(chaves, dropna=False, as_index=False).agg(total_s5001_infoBaseCS=("valor_s5001", "sum"))

    saida = teorica.merge(oficial, on=chaves, how="outer").fillna(0)
    for col in ["total_s1200", "total_incide_cp", "total_nao_incide_cp", "total_s5001_infoBaseCS"]:
        saida[col] = pd.to_numeric(saida.get(col, 0.0), errors="coerce").fillna(0.0)
    saida["diferenca_incide_cp_vs_s5001"] = saida["total_incide_cp"] - saida["total_s5001_infoBaseCS"]
    saida["status_conferencia"] = saida["diferenca_incide_cp_vs_s5001"].apply(lambda x: "OK" if abs(float(x)) <= 0.05 else "Revisar")
    return saida.sort_values(["status_conferencia", "per_apur", "cpf", "matricula"])


def preparar_rubricas_sem_cadastro(df_remun: pd.DataFrame) -> pd.DataFrame:
    mov = preparar_movimentos_cp(df_remun)
    if mov.empty:
        return pd.DataFrame()
    sem = mov[mov["status_cp"].eq("Sem S-1010")].copy()
    if sem.empty:
        return pd.DataFrame()
    return (
        sem.groupby(["per_apur", "cpf", "matricula", "cod_rubr", "ide_tab_rubr"], as_index=False)
        .agg(valor_rubrica=("vr_rubr", "sum"), qtd_lancamentos=("vr_rubr", "size"))
        .sort_values(["per_apur", "valor_rubrica"], ascending=[True, False])
    )


def gerar_composicao_teorica_base(df_remun: pd.DataFrame) -> pd.DataFrame:
    mov = preparar_movimentos_cp(df_remun)
    if mov.empty:
        return pd.DataFrame()
    mov["entra_base_teorica_cp"] = mov["considerado_cp"].eq("Sim")
    mov["rubrica_nao_incidente_cp"] = mov["status_cp"].eq("Não incide CP")
    return mov


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
    return gerar_base_trabalhador_cp(df_remun, df_bases_trabalhador)


def gerar_resumo_visual(df_rubricas_cp: pd.DataFrame, df_movimentos_cp: pd.DataFrame, df_sem_cadastro: pd.DataFrame, df_bases_trabalhador: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    total_rubricas = int(len(df_rubricas_cp)) if df_rubricas_cp is not None and not df_rubricas_cp.empty else 0
    linhas.append({"indicador": "Rubricas únicas no S-1200", "valor": total_rubricas})

    if df_rubricas_cp is not None and not df_rubricas_cp.empty:
        linhas.extend([
            {"indicador": "Rubricas com incidência CP", "valor": int(df_rubricas_cp["status_cp"].eq("Incide CP").sum())},
            {"indicador": "Rubricas sem incidência CP", "valor": int(df_rubricas_cp["status_cp"].eq("Não incide CP").sum())},
            {"indicador": "Rubricas sem S-1010", "valor": int(df_rubricas_cp["status_cp"].eq("Sem S-1010").sum())},
            {"indicador": "Rubricas remuneratórias", "valor": int(df_rubricas_cp["carater_verba"].eq("Remuneratório").sum())},
            {"indicador": "Rubricas rescisórias", "valor": int(df_rubricas_cp["carater_verba"].eq("Rescisório").sum())},
            {"indicador": "Rubricas informativas/técnicas", "valor": int(df_rubricas_cp["carater_verba"].eq("Informativo/Técnico").sum())},
        ])
    if df_movimentos_cp is not None and not df_movimentos_cp.empty:
        linhas.extend([
            {"indicador": "Valor total S-1200", "valor": float(pd.to_numeric(df_movimentos_cp["vr_rubr"], errors="coerce").fillna(0).sum())},
            {"indicador": "Valor com incidência CP", "valor": float(pd.to_numeric(df_movimentos_cp.loc[df_movimentos_cp["considerado_cp"].eq("Sim"), "vr_rubr"], errors="coerce").fillna(0).sum())},
            {"indicador": "Valor sem incidência CP", "valor": float(pd.to_numeric(df_movimentos_cp.loc[df_movimentos_cp["status_cp"].eq("Não incide CP"), "vr_rubr"], errors="coerce").fillna(0).sum())},
        ])
    linhas.append({"indicador": "Linhas S-5001 detalhadas", "valor": int(len(df_bases_trabalhador)) if df_bases_trabalhador is not None else 0})
    return pd.DataFrame(linhas)


def preparar_pacote_analitico(df_rubricas: pd.DataFrame, df_remun: pd.DataFrame, df_bases_trabalhador: pd.DataFrame, df_bases_contribuicao: pd.DataFrame, aliquota_cpp_padrao: float = 20.0):
    df_movimentos_cp = preparar_movimentos_cp(df_remun)
    df_rubricas_cp = gerar_relatorio_rubricas_cp(df_remun)
    df_base_trabalhador = gerar_base_trabalhador_cp(df_remun, df_bases_trabalhador)
    df_sem_cadastro = preparar_rubricas_sem_cadastro(df_remun)
    df_s5001_resumo = gerar_resumo_s5001(df_bases_trabalhador)
    df_resumo_visual = gerar_resumo_visual(df_rubricas_cp, df_movimentos_cp, df_sem_cadastro, df_bases_trabalhador)
    return df_resumo_visual, df_rubricas_cp, df_movimentos_cp, df_base_trabalhador, df_sem_cadastro, df_s5001_resumo


def gerar_resumo_execucao(df_rubricas: pd.DataFrame, df_remun: pd.DataFrame, df_rubricas_cp: pd.DataFrame, df_sem_cadastro: pd.DataFrame, df_bases_trabalhador: pd.DataFrame | None = None) -> pd.DataFrame:
    return gerar_resumo_visual(df_rubricas_cp, preparar_movimentos_cp(df_remun), df_sem_cadastro, df_bases_trabalhador if df_bases_trabalhador is not None else pd.DataFrame())


def _nome_aba_seguro(nome: str, parte: int | None = None) -> str:
    """Garante nome de aba dentro do limite de 31 caracteres do Excel."""
    nome = str(nome)[:31]
    if parte is None:
        return nome
    sufixo = f"_{parte}"
    return f"{nome[:31 - len(sufixo)]}{sufixo}"


def _to_excel_dividido(writer, df: pd.DataFrame | None, sheet_name: str, max_linhas_excel: int = 1_048_576):
    """Exporta DataFrame para Excel respeitando o limite máximo de linhas por aba.

    O Excel suporta 1.048.576 linhas incluindo o cabeçalho; por isso cada parte
    usa no máximo 1.048.575 linhas de dados.
    """
    base = df if df is not None else pd.DataFrame()
    if base.empty:
        base.to_excel(writer, sheet_name=_nome_aba_seguro(sheet_name), index=False)
        return

    max_dados = max_linhas_excel - 1
    total = len(base)
    if total <= max_dados:
        base.to_excel(writer, sheet_name=_nome_aba_seguro(sheet_name), index=False)
        return

    parte = 1
    for inicio in range(0, total, max_dados):
        fim = min(inicio + max_dados, total)
        aba = _nome_aba_seguro(sheet_name, parte)
        base.iloc[inicio:fim].to_excel(writer, sheet_name=aba, index=False)
        parte += 1


def _filtrar_movimentos_cp_exportacao(df: pd.DataFrame | None, modo: str = "todos") -> pd.DataFrame:
    """Filtra a aba 03_movimentos_cp apenas na exportação, preservando layout/colunas.

    modo="todos": mantém todos os movimentos.
    modo="incidencia_cp_padrao": mantém apenas codIncCP 11, 12, 21 e 22.
    """
    base = df if df is not None else pd.DataFrame()
    if base.empty or modo != "incidencia_cp_padrao":
        return base
    if "cod_inc_cp" not in base.columns:
        return base
    cod = base["cod_inc_cp"].fillna("").astype(str).str.strip()
    return base[cod.isin(CODIGOS_CP_EXPORTACAO_PADRAO)].copy()


def gerar_excel_saida(
    df_inventario: pd.DataFrame,
    df_rubricas: pd.DataFrame,
    df_exclusoes: pd.DataFrame,
    df_remun: pd.DataFrame,
    df_bases_trabalhador: pd.DataFrame,
    df_bases_contribuicao: pd.DataFrame,
    df_erros: pd.DataFrame,
    df_layout: pd.DataFrame,
    df_resumo_visual: pd.DataFrame,
    df_rubricas_cp: pd.DataFrame,
    df_movimentos_cp: pd.DataFrame,
    df_base_trabalhador: pd.DataFrame,
    df_sem_cadastro: pd.DataFrame,
    df_s5001_resumo: pd.DataFrame | None = None,
    df_levantamento: pd.DataFrame | None = None,
    df_empresa: pd.DataFrame | None = None,
    modo_exportacao_movimentos_cp: str = "todos",
) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        _to_excel_dividido(writer, df_empresa if df_empresa is not None else pd.DataFrame(), "00_empresa")
        _to_excel_dividido(writer, df_resumo_visual, "01_resumo")
        _to_excel_dividido(writer, df_rubricas_cp, "02_rubricas_cp")
        df_movimentos_cp_export = _filtrar_movimentos_cp_exportacao(df_movimentos_cp, modo_exportacao_movimentos_cp)
        _to_excel_dividido(writer, df_movimentos_cp_export, "03_movimentos_cp")
        _to_excel_dividido(writer, df_base_trabalhador, "04_base_trabalhador")
        _to_excel_dividido(writer, df_sem_cadastro, "05_sem_s1010")
        _to_excel_dividido(writer, df_s5001_resumo if df_s5001_resumo is not None else pd.DataFrame(), "06_s5001_tpvalor")
        _to_excel_dividido(writer, df_levantamento if df_levantamento is not None else pd.DataFrame(), "07_levantamento")
        _to_excel_dividido(writer, df_rubricas, "apoio_s1010")
        _to_excel_dividido(writer, df_remun, "apoio_s1200")
        _to_excel_dividido(writer, df_bases_trabalhador, "apoio_s5001")
        _to_excel_dividido(writer, df_bases_contribuicao, "apoio_s5011")
        _to_excel_dividido(writer, df_exclusoes, "apoio_s3000")
        _to_excel_dividido(writer, df_layout, "checagem_layout")
        _to_excel_dividido(writer, df_inventario, "inventario")
        _to_excel_dividido(writer, df_erros, "erros_xml")
    output.seek(0)
    return output.getvalue()
