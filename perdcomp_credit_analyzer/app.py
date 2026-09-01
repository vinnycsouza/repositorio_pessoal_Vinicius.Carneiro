import io
import inspect

import pandas as pd
import streamlit as st

from src.analyzer import competence_summary, deduplicate_records, organize_records
from src.parsers import ExtractionError, iter_pdf_files, parse_individual_pdf

MAX_FILE_UPLOAD_MB = 25
MAX_TOTAL_UPLOAD_BYTES = 50 * 1024 * 1024


def brl(value):
    if value is None:
        return "Não informado"
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def excel_bytes(sheets):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()


st.set_page_config(page_title="Analisador PER/DCOMP", page_icon="📊", layout="wide")
st.title("Analisador de créditos PER/DCOMP")
st.write(
    "Envie os demonstrativos individuais em PDF ou uma pasta ZIP. "
    "O sistema organiza as declarações por competência e transmissão, identifica "
    "retificações e apresenta o saldo atual do crédito."
)

with st.container(border=True):
    st.subheader("1. Selecione os documentos")
    st.warning(
        "Os arquivos podem conter dados fiscais e pessoais. Envie somente documentos "
        "que você está autorizado a analisar. O conteúdo não é salvo pela aplicação."
    )
    privacy_acknowledged = st.checkbox(
        "Confirmo que estou autorizado a processar estes documentos.",
        key="privacy_acknowledged",
    )
    uploader_options = {}
    if "max_upload_size" in inspect.signature(st.file_uploader).parameters:
        uploader_options["max_upload_size"] = MAX_FILE_UPLOAD_MB
    uploads = st.file_uploader(
        "PDFs individuais ou arquivos ZIP",
        type=["pdf", "zip"],
        accept_multiple_files=True,
        disabled=not privacy_acknowledged,
        help=(
            "Até 25 MB por envio, 50 MB no total, 50 PDFs por processamento, "
            "10 MB e 100 páginas por PDF."
        ),
        **uploader_options,
    )
    st.caption(
        "Limites: 25 MB por arquivo enviado, 50 MB no total e até 50 PDFs. "
        "Os documentos são processados em memória e não ficam armazenados."
    )

if not uploads:
    st.info("Envie ao menos um PDF ou ZIP para iniciar a análise.")
    st.stop()

total_upload_bytes = sum(len(item.getvalue()) for item in uploads)
if total_upload_bytes > MAX_TOTAL_UPLOAD_BYTES:
    st.error("O conjunto enviado excede o limite total de 50 MB.")
    st.stop()

pdfs, errors = iter_pdf_files([(item.name, item.getvalue()) for item in uploads])
if len(pdfs) > 50:
    st.error(f"Foram encontrados {len(pdfs)} PDFs; o limite por processamento é 50.")
    st.stop()
records = []
for file_name, content in pdfs:
    try:
        records.append(parse_individual_pdf(file_name, content))
    except ExtractionError as exc:
        errors.append(f"{file_name}: {exc}")

records, duplicate_warnings = deduplicate_records(records)
errors.extend(duplicate_warnings)

if not records:
    st.error("Nenhum demonstrativo PER/DCOMP válido foi encontrado nos arquivos enviados.")
    if errors:
        with st.expander("Ver detalhes do processamento"):
            for error in errors:
                st.warning(error)
    st.stop()

ordered = organize_records(records)
summaries = competence_summary(ordered)
available_count = sum(row["status"] == "Crédito disponível" for row in summaries)
zero_count = len(summaries) - available_count
total_balance = sum(row["current_balance"] for row in summaries)

st.subheader("2. Resultado geral")
metric_a, metric_b, metric_c, metric_d = st.columns(4)
metric_a.metric("PDFs processados", len(records))
metric_b.metric("Competências", len(summaries))
metric_c.metric("Com crédito", available_count)
metric_d.metric("Saldo total identificado", brl(total_balance))

summary_df = pd.DataFrame(
    [
        {
            "Competência": row["competence"],
            "Crédito passível de restituição": brl(row["initial_credit"]),
            "Crédito utilizado": brl(row["used_credit"]),
            "Saldo atual": brl(row["current_balance"]),
            "Situação": row["status"],
            "Última transmissão": row["latest_transmission"].strftime("%d/%m/%Y"),
            "Último PER/DCOMP": row["latest_number"],
            "Declarações": row["record_count"],
        }
        for row in summaries
    ]
)
st.dataframe(summary_df, use_container_width=True, hide_index=True)
st.caption(f"{available_count} competência(s) com saldo e {zero_count} com crédito zerado.")

st.subheader("3. Histórico por competência")
selected_competence = st.selectbox(
    "Selecione a competência para conferir a sequência",
    [row["competence"] for row in summaries],
)
selected_records = [r for r in ordered if r.competence == selected_competence]
details_df = pd.DataFrame(
    [
        {
            "Transmissão": record.transmission_date.strftime("%d/%m/%Y"),
            "PER/DCOMP": record.number,
            "Crédito passível de restituição": brl(record.refundable_credit),
            "Crédito original na entrega": brl(record.original_credit_at_delivery),
            "Crédito original utilizado": brl(record.original_credit_used),
            "Saldo do crédito original": brl(record.original_credit_balance),
            "Situação": "Válido" if record.effective else "Retificado/substituído",
            "Observação": record.note,
        }
        for record in selected_records
    ]
)
st.dataframe(details_df, use_container_width=True, hide_index=True)

all_details_df = pd.DataFrame(
    [
        {
            "Competência": record.competence,
            "Transmissão": record.transmission_date.strftime("%d/%m/%Y"),
            "PER/DCOMP": record.number,
            "Crédito passível de restituição": brl(record.refundable_credit),
            "Crédito original na entrega": brl(record.original_credit_at_delivery),
            "Crédito original utilizado": brl(record.original_credit_used),
            "Saldo do crédito original": brl(record.original_credit_balance),
            "Situação": "Válido" if record.effective else "Retificado/substituído",
            "Observação": record.note,
            "Arquivo de origem": record.source_file,
        }
        for record in ordered
    ]
)

st.subheader("4. Exportar relatório")
st.download_button(
    "Baixar relatório em Excel",
    data=excel_bytes({"Resumo por competência": summary_df, "Histórico completo": all_details_df}),
    file_name="relatorio_creditos_perdcomp.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

if errors:
    with st.expander(f"Avisos do processamento ({len(errors)})"):
        for error in errors:
            st.warning(error)
