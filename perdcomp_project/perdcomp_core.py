from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import pdfplumber


QUARTER_ORDER = {
    "1º Trimestre": 1,
    "2º Trimestre": 2,
    "3º Trimestre": 3,
    "4º Trimestre": 4,
    "1o Trimestre": 1,
    "2o Trimestre": 2,
    "3o Trimestre": 3,
    "4o Trimestre": 4,
}

MONTH_MAP = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}

LEVANTAMENTO_SYNONYMS = {
    "ano": ["ano"],
    "mes": ["mes", "mês"],
    "credito_pis": ["credito pis", "crédito pis", "pis", "valor pis"],
    "credito_cofins": ["credito cofins", "crédito cofins", "cofins", "valor cofins"],
}


@dataclass
class ExtractedPerdcomp:
    arquivo: str
    tipo_credito: str
    tipo_periodo_credito: Optional[str]
    trimestre: Optional[str]
    ano: Optional[int]
    valor_original_credito: Optional[float]
    saldo_credito_original: Optional[float]
    credito_utilizado_documento: Optional[float]
    credito_atualizado: Optional[float]
    data_criacao: Optional[str]
    data_transmissao: Optional[str]
    observacao: str = ""


class PerdcompExtractionError(Exception):
    pass


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def normalize_key(text: str) -> str:
    text = strip_accents(str(text or "")).lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def parse_brazilian_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    cleaned = str(value).strip().replace(".", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9\.-]", "", cleaned)
    if cleaned in {"", ".", "-", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    texts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
    return "\n".join(texts)


def search_group(pattern: str, text: str, flags: int = re.IGNORECASE | re.MULTILINE) -> Optional[str]:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def identify_tipo_credito(text: str) -> str:
    upper = strip_accents(text).upper()
    if "PIS/PASEP NAO-CUMULATIVO" in upper or "PIS/PASEP NAO CUMULATIVO" in upper:
        return "PIS"
    if "COFINS NAO-CUMULATIVA" in upper or "COFINS NAO CUMULATIVA" in upper:
        return "COFINS"
    if re.search(r"Tipo de Credito\s+PIS", strip_accents(text), re.IGNORECASE):
        return "PIS"
    if re.search(r"Tipo de Credito\s+COFINS", strip_accents(text), re.IGNORECASE):
        return "COFINS"
    return "NÃO IDENTIFICADO"


def extract_perdcomp_fields(text: str, arquivo: str) -> ExtractedPerdcomp:
    tipo_credito = identify_tipo_credito(text)

    tipo_periodo_credito = search_group(r"Tipo de Per[ií]odo do Cr[eé]dito\s+(.+)", text)
    trimestre = search_group(r"Trimestre\s+([0-9ºo]+\s*Trimestre)", text)
    ano_raw = search_group(r"Ano\s+(\d{4})", text)
    valor_original = search_group(r"Valor Original do Cr[eé]dito Inicial\s+([\d\.,-]+)", text)
    saldo_original = search_group(r"Saldo do Cr[eé]dito Original\s+([\d\.,-]+)", text)
    credito_utilizado = search_group(
        r"Total do Cr[eé]dito Original Utilizado neste Documento\s+([\d\.,-]+)", text
    )
    credito_atualizado = search_group(r"Cr[eé]dito Atualizado\s+([\d\.,-]+)", text)
    data_criacao = search_group(r"Data de Cria[cç][aã]o\s+(\d{2}/\d{2}/\d{4})", text)
    data_transmissao = search_group(r"Data de Transmiss[aã]o\s+(\d{2}/\d{2}/\d{4})", text)

    observacoes: list[str] = []
    if not tipo_periodo_credito:
        observacoes.append("Tipo de período do crédito não localizado")
    if not trimestre:
        observacoes.append("Trimestre não localizado")
    if not ano_raw:
        observacoes.append("Ano não localizado")

    return ExtractedPerdcomp(
        arquivo=arquivo,
        tipo_credito=tipo_credito,
        tipo_periodo_credito=tipo_periodo_credito,
        trimestre=trimestre,
        ano=int(ano_raw) if ano_raw else None,
        valor_original_credito=parse_brazilian_number(valor_original),
        saldo_credito_original=parse_brazilian_number(saldo_original),
        credito_utilizado_documento=parse_brazilian_number(credito_utilizado),
        credito_atualizado=parse_brazilian_number(credito_atualizado),
        data_criacao=data_criacao,
        data_transmissao=data_transmissao,
        observacao="; ".join(observacoes),
    )


def process_pdf_files(files: Iterable[tuple[str, bytes]]) -> pd.DataFrame:
    rows: list[dict] = []
    for filename, content in files:
        try:
            text = extract_text_from_pdf_bytes(content)
            extracted = extract_perdcomp_fields(text, filename)
            rows.append(extracted.__dict__)
        except Exception as exc:  # pragma: no cover - defensive
            rows.append(
                {
                    "arquivo": filename,
                    "tipo_credito": "ERRO",
                    "tipo_periodo_credito": None,
                    "trimestre": None,
                    "ano": None,
                    "valor_original_credito": None,
                    "saldo_credito_original": None,
                    "credito_utilizado_documento": None,
                    "credito_atualizado": None,
                    "data_criacao": None,
                    "data_transmissao": None,
                    "observacao": f"Falha ao processar PDF: {exc}",
                }
            )

    df = pd.DataFrame(rows)
    return sort_perdcomp_df(df)


def sort_perdcomp_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["ordem_trimestre"] = df["trimestre"].map(QUARTER_ORDER)
    df = df.sort_values(
        by=["ano", "ordem_trimestre", "tipo_credito", "arquivo"],
        ascending=[True, True, True, True],
        na_position="last",
    )
    return df.drop(columns=["ordem_trimestre"])


def detect_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    normalized_map = {normalize_key(col): col for col in df.columns}
    for candidate in candidates:
        normalized = normalize_key(candidate)
        if normalized in normalized_map:
            return normalized_map[normalized]
    return None


def parse_month_value(value) -> Optional[int]:
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        month = int(value)
        return month if 1 <= month <= 12 else None

    text = normalize_key(str(value))
    if text.isdigit():
        month = int(text)
        return month if 1 <= month <= 12 else None
    return MONTH_MAP.get(text)


def month_to_quarter(month: int) -> str:
    if month in (1, 2, 3):
        return "1º Trimestre"
    if month in (4, 5, 6):
        return "2º Trimestre"
    if month in (7, 8, 9):
        return "3º Trimestre"
    return "4º Trimestre"


def load_levantamento_excel(file_bytes: bytes, filename: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    raw_frames: list[pd.DataFrame] = []
    norm_frames: list[pd.DataFrame] = []

    for sheet_name in xls.sheet_names:
        sheet_df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name)
        if sheet_df.empty:
            continue
        raw_frames.append(sheet_df.assign(_aba_origem=sheet_name))

        col_ano = detect_column(sheet_df, LEVANTAMENTO_SYNONYMS["ano"])
        col_mes = detect_column(sheet_df, LEVANTAMENTO_SYNONYMS["mes"])
        col_pis = detect_column(sheet_df, LEVANTAMENTO_SYNONYMS["credito_pis"])
        col_cofins = detect_column(sheet_df, LEVANTAMENTO_SYNONYMS["credito_cofins"])

        if not (col_ano and col_mes and (col_pis or col_cofins)):
            continue

        temp = pd.DataFrame()
        temp["ano"] = pd.to_numeric(sheet_df[col_ano], errors="coerce").astype("Int64")
        temp["mes_original"] = sheet_df[col_mes]
        temp["mes_numero"] = sheet_df[col_mes].apply(parse_month_value)
        temp["trimestre"] = temp["mes_numero"].apply(lambda x: month_to_quarter(int(x)) if pd.notna(x) else None)
        temp["credito_pis"] = (
            pd.to_numeric(sheet_df[col_pis], errors="coerce") if col_pis else 0.0
        )
        temp["credito_cofins"] = (
            pd.to_numeric(sheet_df[col_cofins], errors="coerce") if col_cofins else 0.0
        )
        temp["arquivo_levantamento"] = filename
        temp["aba_origem"] = sheet_name
        norm_frames.append(temp)

    if not norm_frames:
        raise ValueError(
            "Não foi possível localizar colunas compatíveis no Excel de levantamento. "
            "Use colunas como: Ano, Mês, Crédito PIS e Crédito COFINS."
        )

    normalizado = pd.concat(norm_frames, ignore_index=True)
    normalizado = normalizado.dropna(subset=["ano", "mes_numero"], how="any")
    normalizado["ano"] = normalizado["ano"].astype(int)
    normalizado["credito_pis"] = pd.to_numeric(normalizado["credito_pis"], errors="coerce").fillna(0.0)
    normalizado["credito_cofins"] = pd.to_numeric(normalizado["credito_cofins"], errors="coerce").fillna(0.0)

    agrupado = (
        normalizado.groupby(["ano", "trimestre"], as_index=False)[["credito_pis", "credito_cofins"]]
        .sum()
        .sort_values(by=["ano", "trimestre"], key=lambda s: s.map(QUARTER_ORDER) if s.name == "trimestre" else s)
    )
    agrupado["credito_total_levantado"] = agrupado["credito_pis"] + agrupado["credito_cofins"]

    raw_df = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame()
    return normalizado, agrupado


def summarize_perdcomp_by_type(df_perdcomp: pd.DataFrame) -> pd.DataFrame:
    if df_perdcomp.empty:
        return pd.DataFrame(
            columns=[
                "ano",
                "trimestre",
                "perdcomp_pis_valor_original",
                "perdcomp_pis_saldo",
                "perdcomp_pis_utilizado",
                "perdcomp_cofins_valor_original",
                "perdcomp_cofins_saldo",
                "perdcomp_cofins_utilizado",
            ]
        )

    base = df_perdcomp.copy()
    grouped = (
        base.groupby(["ano", "trimestre", "tipo_credito"], as_index=False)[
            ["valor_original_credito", "saldo_credito_original", "credito_utilizado_documento"]
        ]
        .sum(min_count=1)
    )

    rows: list[dict] = []
    for (ano, trimestre), sub in grouped.groupby(["ano", "trimestre"]):
        row = {"ano": ano, "trimestre": trimestre}
        for _, r in sub.iterrows():
            prefix = "perdcomp_pis" if r["tipo_credito"] == "PIS" else "perdcomp_cofins"
            row[f"{prefix}_valor_original"] = r["valor_original_credito"]
            row[f"{prefix}_saldo"] = r["saldo_credito_original"]
            row[f"{prefix}_utilizado"] = r["credito_utilizado_documento"]
        rows.append(row)

    out = pd.DataFrame(rows)
    for col in [
        "perdcomp_pis_valor_original",
        "perdcomp_pis_saldo",
        "perdcomp_pis_utilizado",
        "perdcomp_cofins_valor_original",
        "perdcomp_cofins_saldo",
        "perdcomp_cofins_utilizado",
    ]:
        if col not in out.columns:
            out[col] = 0.0
    return out.sort_values(by=["ano", "trimestre"], key=lambda s: s.map(QUARTER_ORDER) if s.name == "trimestre" else s)


def build_crosswalk(df_perdcomp: pd.DataFrame, levantamento_trimestral: pd.DataFrame) -> pd.DataFrame:
    perdcomp_resumo = summarize_perdcomp_by_type(df_perdcomp)
    cruzamento = pd.merge(
        levantamento_trimestral,
        perdcomp_resumo,
        on=["ano", "trimestre"],
        how="outer",
    ).fillna(0.0)

    cruzamento["diferenca_pis_utilizado"] = (
        cruzamento["credito_pis"] - cruzamento["perdcomp_pis_utilizado"]
    )
    cruzamento["diferenca_cofins_utilizado"] = (
        cruzamento["credito_cofins"] - cruzamento["perdcomp_cofins_utilizado"]
    )
    cruzamento["diferenca_total_utilizado"] = (
        cruzamento["diferenca_pis_utilizado"] + cruzamento["diferenca_cofins_utilizado"]
    )

    return cruzamento.sort_values(
        by=["ano", "trimestre"],
        key=lambda s: s.map(QUARTER_ORDER) if s.name == "trimestre" else s,
    )


def autosize_worksheet(worksheet) -> None:
    for column_cells in worksheet.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            try:
                length = len(str(cell.value)) if cell.value is not None else 0
                if length > max_length:
                    max_length = length
            except Exception:
                pass
        worksheet.column_dimensions[column_letter].width = min(max_length + 2, 40)


def export_phase1_excel(df_perdcomp: pd.DataFrame, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_perdcomp.to_excel(writer, sheet_name="PERDCOMP_EXTRAIDO", index=False)
        resumo = summarize_perdcomp_by_type(df_perdcomp)
        resumo.to_excel(writer, sheet_name="RESUMO_TRIMESTRAL", index=False)

        wb = writer.book
        for ws in wb.worksheets:
            autosize_worksheet(ws)
    return output_path


def export_phase2_excel(
    df_perdcomp: pd.DataFrame,
    levantamento_normalizado: pd.DataFrame,
    levantamento_trimestral: pd.DataFrame,
    cruzamento: pd.DataFrame,
    output_path: str | Path,
) -> Path:
    output_path = Path(output_path)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_perdcomp.to_excel(writer, sheet_name="PERDCOMP_EXTRAIDO", index=False)
        levantamento_normalizado.to_excel(writer, sheet_name="LEVANTAMENTO_MENSAL_NORM", index=False)
        levantamento_trimestral.to_excel(writer, sheet_name="LEVANTAMENTO_TRIMESTRAL", index=False)
        cruzamento.to_excel(writer, sheet_name="CRUZAMENTO", index=False)

        wb = writer.book
        for ws in wb.worksheets:
            autosize_worksheet(ws)
    return output_path
