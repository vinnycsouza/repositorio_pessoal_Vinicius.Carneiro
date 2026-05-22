from pathlib import Path
from datetime import date
import re
import unicodedata
import pandas as pd


TABELA_ALIQUOTAS = Path(__file__).parent / "tabelas" / "aliquotas_icms_uf_2021_2026.csv"


# ---------------------------------------------------------------------
# Utilitários internos
# ---------------------------------------------------------------------

def _norm_col(valor) -> str:
    texto = "" if valor is None else str(valor).strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9]+", "_", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")
    return texto


def _normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [_norm_col(c) for c in out.columns]
    return out


def _achar_coluna(df: pd.DataFrame, possibilidades: list[str], obrigatoria: bool = False) -> str | None:
    cols = list(df.columns)
    cols_norm = {_norm_col(c): c for c in cols}

    # match exato normalizado
    for nome in possibilidades:
        nome_norm = _norm_col(nome)
        if nome_norm in cols_norm:
            return cols_norm[nome_norm]

    # match parcial
    for nome in possibilidades:
        nome_norm = _norm_col(nome)
        for col in cols:
            col_norm = _norm_col(col)
            if nome_norm and (nome_norm in col_norm or col_norm in nome_norm):
                return col

    if obrigatoria:
        raise KeyError(
            "Coluna obrigatória não localizada. Procurado: "
            + ", ".join(possibilidades)
            + ". Colunas disponíveis: "
            + ", ".join(map(str, cols[:50]))
        )

    return None


def _serie_texto(df: pd.DataFrame, coluna: str | None, padrao: str = "") -> pd.Series:
    if coluna and coluna in df.columns:
        return df[coluna].fillna(padrao).astype(str).str.strip()
    return pd.Series([padrao] * len(df), index=df.index, dtype="object")


def _converter_numero(valor):
    if pd.isna(valor):
        return 0.0

    texto = str(valor).strip()
    if texto == "":
        return 0.0

    texto = (
        texto.replace("R$", "")
        .replace("%", "")
        .replace(" ", "")
        .replace("\u00a0", "")
    )

    # Formato BR: 1.234,56
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        return float(texto)
    except Exception:
        return 0.0


def _serie_numero(df: pd.DataFrame, coluna: str | None) -> pd.Series:
    if coluna and coluna in df.columns:
        return df[coluna].apply(_converter_numero).astype(float)
    return pd.Series([0.0] * len(df), index=df.index, dtype="float64")


def _lista_contem_codigo(valor, codigo: str) -> bool:
    if pd.isna(valor):
        return False

    partes = [
        str(p).strip().zfill(len(codigo))
        for p in str(valor).replace(";", ",").replace("/", ",").split(",")
        if str(p).strip() != ""
    ]
    return codigo in partes


def _limpar_documento(valor) -> str:
    if pd.isna(valor):
        return ""
    texto = str(valor).strip()
    # Excel pode transformar número NF em 123.0
    if re.fullmatch(r"\d+\.0", texto):
        texto = texto[:-2]
    return texto


def _competencia_para_data(valor):
    """
    Tenta converter Mês/Competência para Timestamp do primeiro dia do mês.
    Aceita:
    - datas Excel/pandas
    - 2021-01
    - 01/2021
    - jan/21, jan/2021
    - janeiro/2021
    """
    if pd.isna(valor):
        return pd.NaT

    if isinstance(valor, (pd.Timestamp,)):
        return pd.Timestamp(valor.year, valor.month, 1)

    texto = str(valor).strip().lower()
    if texto == "":
        return pd.NaT

    # Remove acento
    texto_norm = unicodedata.normalize("NFKD", texto)
    texto_norm = "".join(c for c in texto_norm if not unicodedata.combining(c))
    texto_norm = texto_norm.replace(".", "").replace("-", "/").strip()

    # yyyy/mm
    m = re.search(r"(\d{4})/(\d{1,2})", texto_norm)
    if m:
        ano = int(m.group(1))
        mes = int(m.group(2))
        if 1 <= mes <= 12:
            return pd.Timestamp(ano, mes, 1)

    # mm/yyyy ou mm/yy
    m = re.search(r"(\d{1,2})/(\d{2,4})", texto_norm)
    if m:
        mes = int(m.group(1))
        ano = int(m.group(2))
        if ano < 100:
            ano += 2000
        if 1 <= mes <= 12:
            return pd.Timestamp(ano, mes, 1)

    meses = {
        "jan": 1, "janeiro": 1,
        "fev": 2, "fevereiro": 2,
        "mar": 3, "marco": 3, "março": 3,
        "abr": 4, "abril": 4,
        "mai": 5, "maio": 5,
        "jun": 6, "junho": 6,
        "jul": 7, "julho": 7,
        "ago": 8, "agosto": 8,
        "set": 9, "setembro": 9,
        "out": 10, "outubro": 10,
        "nov": 11, "novembro": 11,
        "dez": 12, "dezembro": 12,
    }

    # jan/21, janeiro/2021
    for nome_mes, num_mes in meses.items():
        if texto_norm.startswith(nome_mes):
            anos = re.findall(r"\d{2,4}", texto_norm)
            if anos:
                ano = int(anos[-1])
                if ano < 100:
                    ano += 2000
                return pd.Timestamp(ano, num_mes, 1)

    # tentativa geral
    data = pd.to_datetime(valor, errors="coerce", dayfirst=True)
    if not pd.isna(data):
        return pd.Timestamp(data.year, data.month, 1)

    return pd.NaT


def _competencia_texto(valor) -> str:
    data = _competencia_para_data(valor)
    if pd.isna(data):
        return "SEM_DATA"
    return data.strftime("%Y-%m")



def _competencia_mes_ano(mes_valor, ano_valor) -> str:
    """
    Monta competência usando colunas separadas do C175: Mês + Ano.
    Exemplo: Março + 2021 => 2021-03
    """
    if pd.isna(mes_valor) or pd.isna(ano_valor):
        return "SEM_DATA"

    mes_txt = str(mes_valor).strip()
    ano_txt = str(ano_valor).strip()

    if mes_txt == "" or ano_txt == "":
        return "SEM_DATA"

    try:
        mes_num = int(float(mes_txt))
        ano_num = int(float(ano_txt))
        if ano_num < 100:
            ano_num += 2000
        if 1 <= mes_num <= 12:
            return f"{ano_num:04d}-{mes_num:02d}"
    except Exception:
        pass

    return _competencia_texto(f"{mes_txt}/{ano_txt}")


# ---------------------------------------------------------------------
# Alíquotas
# ---------------------------------------------------------------------

def carregar_tabela_aliquotas() -> pd.DataFrame:
    df = pd.read_csv(TABELA_ALIQUOTAS, dtype=str, sep=";")
    df["INICIO_VIGENCIA"] = pd.to_datetime(df["INICIO_VIGENCIA"], errors="coerce")
    df["FIM_VIGENCIA"] = pd.to_datetime(df["FIM_VIGENCIA"], errors="coerce")
    df["ALIQUOTA_ICMS"] = df["ALIQUOTA_ICMS"].apply(_converter_numero) / 100
    df["UF"] = df["UF"].astype(str).str.upper().str.strip()
    return df


def listar_ufs_aliquotas() -> list[str]:
    try:
        df = carregar_tabela_aliquotas()
        return sorted(df["UF"].dropna().unique().tolist())
    except Exception:
        return [
            "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
            "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
            "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
        ]


def _buscar_aliquota_por_uf_competencia(uf: str, competencia: str, tabela: pd.DataFrame) -> tuple[float, str, str]:
    data_comp = pd.to_datetime(str(competencia) + "-01", errors="coerce")

    if pd.isna(data_comp):
        return 0.0, "NÃO LOCALIZADO", "Competência inválida"

    base = tabela[
        (tabela["UF"].astype(str).str.upper() == str(uf).upper())
        & (tabela["INICIO_VIGENCIA"] <= data_comp)
        & (tabela["FIM_VIGENCIA"] >= data_comp)
    ].copy()

    if base.empty:
        return 0.0, "NÃO LOCALIZADO", "Alíquota não localizada para UF/competência"

    linha = base.iloc[0]
    return float(linha["ALIQUOTA_ICMS"]), str(linha.get("FONTE", "")), str(linha.get("OBSERVACAO", ""))


# ---------------------------------------------------------------------
# Preparação do C170/C175 no padrão manual
# ---------------------------------------------------------------------

def _preparar_contribuicoes_st(df_original: pd.DataFrame, registro: str) -> pd.DataFrame:
    """
    Transforma C170/C175 em uma base documental compatível com a planilha manual
    'Calculo ICMS ST'.

    O foco é o C175 com cabeçalho:
    Mês | Número NF | CFOP | Valor da Operação | Valor de Desconto |
    CST - PIS | Valor BC PIS | CST COFINS | Valor BC COFINS
    """
    df = _normalizar_colunas(df_original)

    col_mes = _achar_coluna(df, ["Mês", "MES", "COMPETENCIA", "PERIODO", "DT_DOC", "DATA"])
    col_ano = _achar_coluna(df, ["Ano", "ANO", "EXERCICIO", "EXERCÍCIO"])
    col_chave = _achar_coluna(df, ["Chave(C100)", "CHAVE(C100)", "CHAVE C100", "CHAVE", "CHV_NFE", "CHAVE_NFE", "CHAVE NF", "CHAVE DE ACESSO"])
    col_nf = _achar_coluna(df, ["Número da Nota(C100)", "NUMERO DA NOTA(C100)", "NÚMERO DA NOTA(C100)", "Número NF", "NUMERO NF", "NÚMERO NF", "NUM_DOC", "NUMERO", "NR_DOC", "N_DOC"])
    col_cfop = _achar_coluna(df, ["CFOP"], obrigatoria=True)

    col_valor_op = _achar_coluna(
        df,
        [
            "Valor da Operação",
            "VALOR DA OPERACAO",
            "VALOR DE OPERACAO",
            "Valor Operação",
            "VL_OPR",
            "VL_ITEM",
            "VALOR_ITEM",
            "VALOR DA OPERAÇÃO",
        ],
        obrigatoria=True,
    )

    col_desconto = _achar_coluna(
        df,
        [
            "Valor de Desconto",
            "VALOR DE DESCONTO",
            "Valor do Desconto",
            "VALOR DO DESCONTO",
            "VL_DESC",
            "DESCONTO",
        ],
    )

    col_cst_pis = _achar_coluna(
        df,
        [
            "CST - PIS",
            "CST PIS",
            "CST_PIS",
            "CST DE PIS",
            "CST",
        ],
    )

    col_bc_pis = _achar_coluna(
        df,
        [
            "Valor BC PIS",
            "VALOR BC PIS",
            "VL_BC_PIS",
            "BC PIS",
            "BASE PIS",
            "BASE DE PIS",
        ],
        obrigatoria=True,
    )

    col_aliq_pis = _achar_coluna(df, ["Alíquota PIS", "ALIQUOTA PIS", "ALIQ_PIS"])
    col_valor_pis = _achar_coluna(df, ["Valor PIS", "VALOR PIS", "VL_PIS"])

    col_cst_cofins = _achar_coluna(
        df,
        [
            "CST COFINS",
            "CST - COFINS",
            "CST_COFINS",
            "CST DE COFINS",
        ],
    )

    col_bc_cofins = _achar_coluna(
        df,
        [
            "Valor BC COFINS",
            "VALOR BC COFINS",
            "VL_BC_COFINS",
            "BC COFINS",
            "BASE COFINS",
            "BASE DE COFINS",
        ],
    )

    col_aliq_cofins = _achar_coluna(df, ["Alíquota COFINS", "ALIQUOTA COFINS", "ALIQ_COFINS"])
    col_valor_cofins = _achar_coluna(df, ["Valor COFINS", "VALOR COFINS", "VL_COFINS"])

    out = pd.DataFrame(index=df.index)
    out["REGISTRO"] = registro

    if col_mes and col_ano:
        out["COMPETENCIA_ORIGINAL"] = (
            _serie_texto(df, col_mes) + "/" + _serie_texto(df, col_ano)
        )
        out["COMPETENCIA"] = [
            _competencia_mes_ano(mes, ano)
            for mes, ano in zip(df[col_mes], df[col_ano])
        ]
    elif col_mes:
        out["COMPETENCIA_ORIGINAL"] = _serie_texto(df, col_mes)
        out["COMPETENCIA"] = df[col_mes].apply(_competencia_texto)
    else:
        out["COMPETENCIA_ORIGINAL"] = "SEM_DATA"
        out["COMPETENCIA"] = "SEM_DATA"

    out["CHAVE"] = _serie_texto(df, col_chave)
    out["NUMERO_NF"] = _serie_texto(df, col_nf)
    out["DOCUMENTO"] = out["CHAVE"].where(out["CHAVE"].astype(str).str.strip() != "", out["NUMERO_NF"])
    out["DOCUMENTO"] = out["DOCUMENTO"].apply(_limpar_documento)

    out["CFOP"] = _serie_texto(df, col_cfop)
    out["CST_PIS"] = _serie_texto(df, col_cst_pis)
    out["CST_COFINS"] = _serie_texto(df, col_cst_cofins) if col_cst_cofins else out["CST_PIS"]

    out["VL_OPERACAO"] = _serie_numero(df, col_valor_op)
    out["VL_DESCONTO"] = _serie_numero(df, col_desconto)
    out["VL_BC_PIS"] = _serie_numero(df, col_bc_pis)
    out["VL_BC_COFINS"] = _serie_numero(df, col_bc_cofins)

    out["ALIQ_PIS_ORIGINAL"] = _serie_numero(df, col_aliq_pis)
    out["VL_PIS_ORIGINAL"] = _serie_numero(df, col_valor_pis)
    out["ALIQ_COFINS_ORIGINAL"] = _serie_numero(df, col_aliq_cofins)
    out["VL_COFINS_ORIGINAL"] = _serie_numero(df, col_valor_cofins)

    # Rastreabilidade das colunas localizadas
    out["COLUNA_ORIGEM_MES"] = col_mes or "NÃO LOCALIZADA"
    out["COLUNA_ORIGEM_OPERACAO"] = col_valor_op or "NÃO LOCALIZADA"
    out["COLUNA_ORIGEM_DESCONTO"] = col_desconto or "NÃO LOCALIZADA"
    out["COLUNA_ORIGEM_BC_PIS"] = col_bc_pis or "NÃO LOCALIZADA"
    out["COLUNA_ORIGEM_BC_COFINS"] = col_bc_cofins or "NÃO LOCALIZADA"

    return out.reset_index(drop=True)


def _adicionar_calculos_manuais(
    df: pd.DataFrame,
    uf: str,
    origem_aliquota: str,
    aliquota_icms_manual: float | None,
    tabela_aliquotas: pd.DataFrame,
    aliquota_pis: float,
    aliquota_cofins: float,
    regime: str,
    tolerancia_bc: float,
) -> pd.DataFrame:
    out = df.copy()

    out["UF"] = uf

    # Lógica manual: operação líquida = valor operação - desconto
    out["BASE_OPERACAO_LIQUIDA"] = out["VL_OPERACAO"] - out["VL_DESCONTO"]

    # Validação da veracidade da BC PIS
    out["DIF_BASE_OPERACAO_VS_BC_PIS"] = out["BASE_OPERACAO_LIQUIDA"] - out["VL_BC_PIS"]
    out["BC_PIS_COMPATIVEL"] = out["DIF_BASE_OPERACAO_VS_BC_PIS"].abs() <= float(tolerancia_bc)

    if origem_aliquota == "Alíquota manual":
        out["ALIQUOTA_ICMS"] = float(aliquota_icms_manual or 0.0)
        out["FONTE_ALIQUOTA"] = "MANUAL"
        out["OBS_ALIQUOTA"] = "Alíquota informada pelo usuário"
    else:
        aliquotas = out["COMPETENCIA"].apply(
            lambda comp: _buscar_aliquota_por_uf_competencia(uf, comp, tabela_aliquotas)
        )
        out["ALIQUOTA_ICMS"] = aliquotas.apply(lambda x: x[0])
        out["FONTE_ALIQUOTA"] = aliquotas.apply(lambda x: x[1])
        out["OBS_ALIQUOTA"] = aliquotas.apply(lambda x: x[2])

    # Estimativa manual do ICMS-ST embutido
    out["ICMS_ST_ESTIMADO"] = out["BASE_OPERACAO_LIQUIDA"] * out["ALIQUOTA_ICMS"]
    out["BASE_ESTIMADA_SEM_ICMS_ST"] = out["BASE_OPERACAO_LIQUIDA"] - out["ICMS_ST_ESTIMADO"]

    # Recalculo PIS/COFINS com alíquotas do regime selecionado
    out["REGIME_PIS_COFINS"] = regime
    out["ALIQUOTA_PIS_CALCULO"] = float(aliquota_pis)
    out["ALIQUOTA_COFINS_CALCULO"] = float(aliquota_cofins)
    out["ALIQUOTA_TOTAL_PIS_COFINS"] = float(aliquota_pis) + float(aliquota_cofins)

    out["PIS_RECALCULADO_SEM_ST"] = out["BASE_ESTIMADA_SEM_ICMS_ST"] * out["ALIQUOTA_PIS_CALCULO"]
    out["COFINS_RECALCULADO_SEM_ST"] = out["BASE_ESTIMADA_SEM_ICMS_ST"] * out["ALIQUOTA_COFINS_CALCULO"]
    out["PISCOFINS_RECALCULADO_SEM_ST"] = out["PIS_RECALCULADO_SEM_ST"] + out["COFINS_RECALCULADO_SEM_ST"]

    # Crédito estimado sobre o ICMS-ST retirado da base
    out["CREDITO_PIS_ESTIMADO"] = out["ICMS_ST_ESTIMADO"] * out["ALIQUOTA_PIS_CALCULO"]
    out["CREDITO_COFINS_ESTIMADO"] = out["ICMS_ST_ESTIMADO"] * out["ALIQUOTA_COFINS_CALCULO"]
    out["CREDITO_TOTAL_ESTIMADO"] = out["CREDITO_PIS_ESTIMADO"] + out["CREDITO_COFINS_ESTIMADO"]

    def status(row):
        if not _lista_contem_codigo(row.get("CFOP", ""), "5405"):
            return "FORA CFOP 5405"
        if not _lista_contem_codigo(row.get("CST_PIS", ""), "01"):
            return "CST PIS DIFERENTE DE 01"
        if not _lista_contem_codigo(row.get("CST_COFINS", ""), "01"):
            return "CST COFINS DIFERENTE DE 01"
        if row.get("ALIQUOTA_ICMS", 0) <= 0:
            return "SEM ALÍQUOTA ICMS"
        if not bool(row.get("BC_PIS_COMPATIVEL", False)):
            return "BC PIS INCOMPATÍVEL"
        return "ELEGÍVEL"

    out["STATUS_ANALISE"] = out.apply(status, axis=1)
    out["TIPO_APURACAO"] = "ESTIMADO"
    out["CRITERIO"] = (
        "CFOP 5405 + CST PIS/COFINS 01 + BC PIS compatível com "
        "Valor da Operação - Valor de Desconto"
    )

    return out


# ---------------------------------------------------------------------
# Função principal chamada pelo app.py
# ---------------------------------------------------------------------

def processar_icms_st(
    xls_pis: pd.ExcelFile,
    get_sheet_name,
    modo: str,
    uf: str,
    data_inicio: date,
    data_fim: date,
    origem_aliquota: str,
    aliquota_icms_manual: float | None,
    aliquota_pis: float,
    aliquota_cofins: float,
    regime: str,
    tolerancia_bc: float,
) -> dict[str, pd.DataFrame]:
    registros = []
    if modo in ["C170", "C170 + C175"]:
        registros.append("C170")
    if modo in ["C175", "C170 + C175"]:
        registros.append("C175")

    frames = []
    erros_leitura = []

    for registro in registros:
        try:
            aba = get_sheet_name(xls_pis, registro)
            df = pd.read_excel(xls_pis, sheet_name=aba, dtype=object)
            frames.append(_preparar_contribuicoes_st(df, registro))
        except Exception as e:
            erros_leitura.append({"REGISTRO": registro, "ERRO": str(e)})

    if frames:
        base = pd.concat(frames, ignore_index=True)
    else:
        base = pd.DataFrame()

    tabela_aliquotas = carregar_tabela_aliquotas()

    if base.empty:
        parametros = pd.DataFrame([
            {"PARAMETRO": "Módulo", "VALOR": "ICMS-ST - análise preliminar"},
            {"PARAMETRO": "Aviso", "VALOR": "Nenhuma linha lida do SPED Contribuições."},
        ])
        return {
            "01_resumo_mensal": pd.DataFrame(),
            "02_analitico_documental": pd.DataFrame(),
            "03_elegiveis_credito": pd.DataFrame(),
            "04_divergencias": pd.DataFrame(erros_leitura),
            "05_parametros": parametros,
            "06_tabela_aliquotas_usada": tabela_aliquotas,
        }

    # Filtro de período. Se competência não for parseada, não elimina automaticamente:
    # mantém em divergências para revisão.
    base["DATA_COMP"] = pd.to_datetime(base["COMPETENCIA"].astype(str) + "-01", errors="coerce")
    inicio = pd.to_datetime(data_inicio)
    fim = pd.to_datetime(data_fim)

    dentro_periodo = base["DATA_COMP"].isna() | ((base["DATA_COMP"] >= inicio) & (base["DATA_COMP"] <= fim))
    base_periodo = base[dentro_periodo].copy()

    analitico = _adicionar_calculos_manuais(
        base_periodo,
        uf=uf,
        origem_aliquota=origem_aliquota,
        aliquota_icms_manual=aliquota_icms_manual,
        tabela_aliquotas=tabela_aliquotas,
        aliquota_pis=aliquota_pis,
        aliquota_cofins=aliquota_cofins,
        regime=regime,
        tolerancia_bc=tolerancia_bc,
    )

    # A aba 02 mostra o documental filtrado em CFOP 5405, porque é o foco do seu trabalho manual.
    analitico_5405 = analitico[analitico["CFOP"].apply(lambda x: _lista_contem_codigo(x, "5405"))].copy()

    elegiveis = analitico_5405[analitico_5405["STATUS_ANALISE"] == "ELEGÍVEL"].copy()
    divergencias = analitico_5405[analitico_5405["STATUS_ANALISE"] != "ELEGÍVEL"].copy()

    if erros_leitura:
        divergencias = pd.concat([divergencias, pd.DataFrame(erros_leitura)], ignore_index=True)

    if elegiveis.empty:
        resumo = pd.DataFrame(
            columns=[
                "COMPETENCIA",
                "UF",
                "ALIQUOTA_ICMS_MEDIA",
                "QTD_REGISTROS",
                "QTD_DOCUMENTOS",
                "BASE_OPERACAO_LIQUIDA",
                "ICMS_ST_ESTIMADO",
                "BASE_ESTIMADA_SEM_ICMS_ST",
                "CREDITO_PIS_ESTIMADO",
                "CREDITO_COFINS_ESTIMADO",
                "CREDITO_TOTAL_ESTIMADO",
            ]
        )
    else:
        resumo = (
            elegiveis.groupby(["COMPETENCIA", "UF"], dropna=False)
            .agg(
                ALIQUOTA_ICMS_MEDIA=("ALIQUOTA_ICMS", "mean"),
                QTD_REGISTROS=("DOCUMENTO", "size"),
                QTD_DOCUMENTOS=("DOCUMENTO", "nunique"),
                BASE_OPERACAO_LIQUIDA=("BASE_OPERACAO_LIQUIDA", "sum"),
                ICMS_ST_ESTIMADO=("ICMS_ST_ESTIMADO", "sum"),
                BASE_ESTIMADA_SEM_ICMS_ST=("BASE_ESTIMADA_SEM_ICMS_ST", "sum"),
                CREDITO_PIS_ESTIMADO=("CREDITO_PIS_ESTIMADO", "sum"),
                CREDITO_COFINS_ESTIMADO=("CREDITO_COFINS_ESTIMADO", "sum"),
                CREDITO_TOTAL_ESTIMADO=("CREDITO_TOTAL_ESTIMADO", "sum"),
            )
            .reset_index()
            .sort_values(["COMPETENCIA", "UF"])
        )

    # Diagnóstico para explicar quando sai vazio
    diagnostico = pd.DataFrame(
        [
            {"ETAPA": "Linhas lidas", "QTD": len(base)},
            {"ETAPA": "Linhas no período", "QTD": len(base_periodo)},
            {"ETAPA": "Linhas CFOP 5405", "QTD": len(analitico_5405)},
            {"ETAPA": "Elegíveis", "QTD": len(elegiveis)},
            {"ETAPA": "Divergências/revisar", "QTD": len(divergencias)},
        ]
    )

    parametros = pd.DataFrame(
        [
            {"PARAMETRO": "Data da análise", "VALOR": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M:%S")},
            {"PARAMETRO": "Módulo", "VALOR": "ICMS-ST - análise preliminar documental"},
            {"PARAMETRO": "Modo", "VALOR": modo},
            {"PARAMETRO": "UF", "VALOR": uf},
            {"PARAMETRO": "Período inicial", "VALOR": str(data_inicio)},
            {"PARAMETRO": "Período final", "VALOR": str(data_fim)},
            {"PARAMETRO": "Origem da alíquota ICMS", "VALOR": origem_aliquota},
            {"PARAMETRO": "Regime PIS/COFINS", "VALOR": regime},
            {"PARAMETRO": "Alíquota PIS", "VALOR": aliquota_pis},
            {"PARAMETRO": "Alíquota COFINS", "VALOR": aliquota_cofins},
            {"PARAMETRO": "Tolerância BC PIS", "VALOR": tolerancia_bc},
            {"PARAMETRO": "Critério", "VALOR": "CFOP 5405 + CST PIS/COFINS 01 + BC PIS compatível com Valor da Operação - Valor de Desconto"},
            {"PARAMETRO": "Aviso", "VALOR": "Cálculo estimativo; validar NCM/CEST/produto/FECOP/legislação estadual antes de usar como valor definitivo."},
        ]
    )

    tabela_usada = tabela_aliquotas[tabela_aliquotas["UF"].astype(str).str.upper() == str(uf).upper()].copy()

    for df in [analitico_5405, elegiveis, divergencias, base_periodo, analitico]:
        if isinstance(df, pd.DataFrame) and "DATA_COMP" in df.columns:
            df.drop(columns=["DATA_COMP"], inplace=True)

    return {
        "01_resumo_mensal": resumo,
        "02_analitico_documental": analitico_5405,
        "03_elegiveis_credito": elegiveis,
        "04_divergencias": divergencias,
        "05_parametros": parametros,
        "06_tabela_aliquotas_usada": tabela_usada,
        "07_diagnostico": diagnostico,
    }
