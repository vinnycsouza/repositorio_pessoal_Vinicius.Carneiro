import io
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pdfplumber


# =========================
# Utilitários de texto
# =========================

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    text_parts: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return normalize_text("\n".join(text_parts))


def extract_first(pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[str]:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def parse_brl_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None

    cleaned = value.strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)

    if not cleaned:
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


def quarter_sort_key(q: Optional[str]) -> int:
    if not q:
        return 99

    q = str(q).strip().lower()

    mapping = {
        "1º trimestre": 1,
        "1o trimestre": 1,
        "1 trimestre": 1,
        "2º trimestre": 2,
        "2o trimestre": 2,
        "2 trimestre": 2,
        "3º trimestre": 3,
        "3o trimestre": 3,
        "3 trimestre": 3,
        "4º trimestre": 4,
        "4o trimestre": 4,
        "4 trimestre": 4,
    }
    return mapping.get(q, 99)


def month_to_quarter(month_value) -> str:
    if pd.isna(month_value):
        raise ValueError("Mês vazio no levantamento.")

    if isinstance(month_value, (int, float)):
        month_num = int(month_value)
    else:
        raw = str(month_value).strip().lower()

        month_map = {
            "janeiro": 1,
            "jan": 1,
            "fevereiro": 2,
            "fev": 2,
            "março": 3,
            "marco": 3,
            "mar": 3,
            "abril": 4,
            "abr": 4,
            "maio": 5,
            "mai": 5,
            "junho": 6,
            "jun": 6,
            "julho": 7,
            "jul": 7,
            "agosto": 8,
            "ago": 8,
            "setembro": 9,
            "set": 9,
            "outubro": 10,
            "out": 10,
            "novembro": 11,
            "nov": 11,
            "dezembro": 12,
            "dez": 12,
        }

        if raw.isdigit():
            month_num = int(raw)
        elif raw in month_map:
            month_num = month_map[raw]
        else:
            raise ValueError(f"Mês inválido no levantamento: {month_value}")

    if month_num in (1, 2, 3):
        return "1º Trimestre"
    if month_num in (4, 5, 6):
        return "2º Trimestre"
    if month_num in (7, 8, 9):
        return "3º Trimestre"
    if month_num in (10, 11, 12):
        return "4º Trimestre"

    raise ValueError(f"Mês inválido no levantamento: {month_value}")


# =========================
# Extração PER/DCOMP
# =========================

def identify_credit_type(text: str) -> str:
    upper = text.upper()

    if "PIS/PASEP NÃO-CUMULATIVO" in upper or "PIS/PASEP NAO-CUMULATIVO" in upper:
        return "PIS"

    if "COFINS NÃO-CUMULATIVA" in upper or "COFINS NAO-CUMULATIVA" in upper:
        return "COFINS"

    if "TIPO DE CRÉDITO PIS/PASEP" in upper or "TIPO DE CREDITO PIS/PASEP" in upper:
        return "PIS"

    if "TIPO DE CRÉDITO COFINS" in upper or "TIPO DE CREDITO COFINS" in upper:
        return "COFINS"

    return "NÃO IDENTIFICADO"


def extract_perdcomp_fields(text: str, filename: str) -> Dict:
    tipo_credito = identify_credit_type(text)

    data_criacao = extract_first(r"Data de Criação\s+(\d{2}/\d{2}/\d{4})", text)
    data_transmissao = extract_first(r"Data de Transmissão\s+(\d{2}/\d{2}/\d{4})", text)

    tipo_periodo_credito = extract_first(r"Tipo de Período do Crédito\s+([^\n\r]+)", text)
    trimestre = extract_first(r"Trimestre\s+([^\n\r]+)", text)
    ano = extract_first(r"\bAno\s+(\d{4})", text)

    valor_original_credito = parse_brl_number(
        extract_first(r"Valor Original do Crédito Inicial\s+([\d\.\,]+)", text)
    )

    saldo_credito_original = parse_brl_number(
        extract_first(r"Saldo do Crédito Original\s+([\d\.\,]+)", text)
    )

    credito_atualizado = parse_brl_number(
        extract_first(r"Crédito Atualizado\s+([\d\.\,]+)", text)
    )

    total_credito_utilizado = parse_brl_number(
        extract_first(
            r"Total do Crédito Original Utilizado neste Documento\s+([\d\.\,]+)",
            text,
        )
    )

    return {
        "Arquivo": filename,
        "Tipo Crédito": tipo_credito,
        "Tipo de Período do Crédito": tipo_periodo_credito,
        "Trimestre": trimestre,
        "Ano": int(ano) if ano else None,
        "Valor Original do Crédito": valor_original_credito,
        "Saldo do Crédito Original": saldo_credito_original,
        "Crédito Atualizado": credito_atualizado,
        "Crédito Utilizado no Documento": total_credito_utilizado,
        "Data de Criação": data_criacao,
        "Data de Transmissão": data_transmissao,
    }


def process_phase1_pdfs(uploaded_pdfs) -> pd.DataFrame:
    records: List[Dict] = []

    for uploaded_file in uploaded_pdfs:
        try:
            pdf_bytes = uploaded_file.read()
            text = extract_text_from_pdf_bytes(pdf_bytes)
            record = extract_perdcomp_fields(text, uploaded_file.name)
            records.append(record)
        except Exception as e:
            records.append(
                {
                    "Arquivo": uploaded_file.name,
                    "Tipo Crédito": "ERRO",
                    "Tipo de Período do Crédito": None,
                    "Trimestre": None,
                    "Ano": None,
                    "Valor Original do Crédito": None,
                    "Saldo do Crédito Original": None,
                    "Crédito Atualizado": None,
                    "Crédito Utilizado no Documento": None,
                    "Data de Criação": None,
                    "Data de Transmissão": None,
                    "Erro": str(e),
                }
            )

    df = pd.DataFrame(records)

    if df.empty:
        return df

    if "Erro" not in df.columns:
        df["Erro"] = None

    df["QuarterOrder"] = df["Trimestre"].apply(quarter_sort_key)
    df = df.sort_values(
        by=["Ano", "QuarterOrder", "Tipo Crédito", "Arquivo"],
        ascending=[True, True, True, True],
        na_position="last",
    ).reset_index(drop=True)

    df = df.drop(columns=["QuarterOrder"])
    return df


# =========================
# Exportação Fase 1
# =========================

def export_phase1_excel(df: pd.DataFrame) -> io.BytesIO:
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="PERDCOMP_EXTRAIDO")

    output.seek(0)
    return output


# =========================
# Leitura do levantamento
# =========================

def read_levantamento_excel(uploaded_excel) -> pd.DataFrame:
    df = pd.read_excel(uploaded_excel)

    # Padronização leve de nomes
    rename_map = {}
    for col in df.columns:
        lower = str(col).strip().lower()

        if lower == "ano":
            rename_map[col] = "Ano"
        elif lower in ("mês", "mes"):
            rename_map[col] = "Mês"
        elif lower in ("crédito pis", "credito pis", "pis"):
            rename_map[col] = "Crédito PIS"
        elif lower in ("crédito cofins", "credito cofins", "cofins"):
            rename_map[col] = "Crédito COFINS"

    df = df.rename(columns=rename_map)

    required = ["Ano", "Mês", "Crédito PIS", "Crédito COFINS"]
    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(
            f"O levantamento deve conter as colunas: {required}. Ausentes: {missing}"
        )

    return df.copy()


# =========================
# Fase 2
# =========================

def normalize_levantamento(df_levantamento: pd.DataFrame) -> pd.DataFrame:
    df = df_levantamento.copy()

    df["Ano"] = pd.to_numeric(df["Ano"], errors="coerce").astype("Int64")
    df["Crédito PIS"] = pd.to_numeric(df["Crédito PIS"], errors="coerce").fillna(0.0)
    df["Crédito COFINS"] = pd.to_numeric(df["Crédito COFINS"], errors="coerce").fillna(0.0)

    df["Trimestre"] = df["Mês"].apply(month_to_quarter)

    grouped = (
        df.groupby(["Ano", "Trimestre"], as_index=False)[["Crédito PIS", "Crédito COFINS"]]
        .sum()
    )

    grouped["Crédito Total Levantado"] = (
        grouped["Crédito PIS"] + grouped["Crédito COFINS"]
    )

    grouped["QuarterOrder"] = grouped["Trimestre"].apply(quarter_sort_key)
    grouped = grouped.sort_values(
        by=["Ano", "QuarterOrder"],
        ascending=[True, True],
        na_position="last",
    ).reset_index(drop=True)

    grouped = grouped.drop(columns=["QuarterOrder"])
    return grouped


def normalize_phase1_for_merge(df_phase1: pd.DataFrame) -> pd.DataFrame:
    df = df_phase1.copy()

    required_cols = [
        "Tipo Crédito",
        "Ano",
        "Trimestre",
        "Valor Original do Crédito",
        "Saldo do Crédito Original",
        "Crédito Utilizado no Documento",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"O Excel da Fase 1 não possui as colunas esperadas. Ausentes: {missing}"
        )

    df["Ano"] = pd.to_numeric(df["Ano"], errors="coerce").astype("Int64")
    df["Valor Original do Crédito"] = pd.to_numeric(
        df["Valor Original do Crédito"], errors="coerce"
    ).fillna(0.0)
    df["Saldo do Crédito Original"] = pd.to_numeric(
        df["Saldo do Crédito Original"], errors="coerce"
    ).fillna(0.0)
    df["Crédito Utilizado no Documento"] = pd.to_numeric(
        df["Crédito Utilizado no Documento"], errors="coerce"
    ).fillna(0.0)

    grouped = (
        df.groupby(["Ano", "Trimestre", "Tipo Crédito"], as_index=False)[
            [
                "Valor Original do Crédito",
                "Saldo do Crédito Original",
                "Crédito Utilizado no Documento",
            ]
        ]
        .sum()
    )

    return grouped


def build_phase2_outputs(
    df_phase1: pd.DataFrame,
    df_levantamento: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    df_levant_trim = normalize_levantamento(df_levantamento)
    df_phase1_grouped = normalize_phase1_for_merge(df_phase1)

    df_pis = (
        df_phase1_grouped[df_phase1_grouped["Tipo Crédito"] == "PIS"]
        .drop(columns=["Tipo Crédito"])
        .rename(
            columns={
                "Valor Original do Crédito": "PIS PERDCOMP - Valor Original",
                "Saldo do Crédito Original": "PIS PERDCOMP - Saldo",
                "Crédito Utilizado no Documento": "PIS PERDCOMP - Utilizado",
            }
        )
    )

    df_cofins = (
        df_phase1_grouped[df_phase1_grouped["Tipo Crédito"] == "COFINS"]
        .drop(columns=["Tipo Crédito"])
        .rename(
            columns={
                "Valor Original do Crédito": "COFINS PERDCOMP - Valor Original",
                "Saldo do Crédito Original": "COFINS PERDCOMP - Saldo",
                "Crédito Utilizado no Documento": "COFINS PERDCOMP - Utilizado",
            }
        )
    )

    df_final = df_levant_trim.merge(
        df_pis,
        on=["Ano", "Trimestre"],
        how="outer",
    ).merge(
        df_cofins,
        on=["Ano", "Trimestre"],
        how="outer",
    )

    numeric_cols = [
        "Crédito PIS",
        "Crédito COFINS",
        "Crédito Total Levantado",
        "PIS PERDCOMP - Valor Original",
        "PIS PERDCOMP - Saldo",
        "PIS PERDCOMP - Utilizado",
        "COFINS PERDCOMP - Valor Original",
        "COFINS PERDCOMP - Saldo",
        "COFINS PERDCOMP - Utilizado",
    ]

    for col in numeric_cols:
        if col in df_final.columns:
            df_final[col] = pd.to_numeric(df_final[col], errors="coerce").fillna(0.0)

    df_final["Diferença PIS"] = (
        df_final["Crédito PIS"] - df_final.get("PIS PERDCOMP - Utilizado", 0.0)
    )
    df_final["Diferença COFINS"] = (
        df_final["Crédito COFINS"] - df_final.get("COFINS PERDCOMP - Utilizado", 0.0)
    )

    df_final["QuarterOrder"] = df_final["Trimestre"].apply(quarter_sort_key)
    df_final = df_final.sort_values(
        by=["Ano", "QuarterOrder"],
        ascending=[True, True],
        na_position="last",
    ).reset_index(drop=True)

    df_final = df_final.drop(columns=["QuarterOrder"])

    return df_levant_trim, df_final


# =========================
# Exportação Fase 2
# =========================

def export_phase2_excel(
    df_levantamento_trim: pd.DataFrame,
    df_cruzamento: pd.DataFrame,
) -> io.BytesIO:
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_levantamento_trim.to_excel(
            writer,
            index=False,
            sheet_name="LEVANTAMENTO_TRIMESTRAL",
        )
        df_cruzamento.to_excel(
            writer,
            index=False,
            sheet_name="CRUZAMENTO",
        )

    output.seek(0)
    return output