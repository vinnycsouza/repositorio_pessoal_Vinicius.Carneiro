import io
import pandas as pd
import streamlit as st
from src.analyzer import competence_summary, organize_records, reconcile
from src.parsers import ExtractionError, iter_pdf_files, parse_consolidated_pdf, parse_individual_pdf

def brl(v):
    if v is None: return "Não informado"
    return "R$ "+f"{v:,.2f}".replace(",","X").replace(".",",").replace("X",".")
def excel_bytes(sheets):
    output=io.BytesIO()
    with pd.ExcelWriter(output,engine="openpyxl") as writer:
        for name,frame in sheets.items(): frame.to_excel(writer,sheet_name=name,index=False)
    return output.getvalue()

st.set_page_config(page_title="Analisador PER/DCOMP",page_icon="📊",layout="wide")
st.title("Analisador de créditos PER/DCOMP")
tab1,tab2=st.tabs(["PDFs individuais","Relatório consolidado"])
with tab1:
    uploads=st.file_uploader("Envie PDFs ou ZIPs",type=["pdf","zip"],accept_multiple_files=True,key="individual")
    if uploads:
        pdfs,errors=iter_pdf_files([(f.name,f.getvalue()) for f in uploads]); records=[]
        for name,data in pdfs:
            try: records.append(parse_individual_pdf(name,data))
            except ExtractionError as exc: errors.append(f"{name}: {exc}")
        if records:
            ordered=organize_records(records); st.session_state["individual_records"]=ordered
            summary=pd.DataFrame([{"Competência":r["competence"],"Crédito inicial":brl(r["initial_credit"]),"Saldo atual":brl(r["current_balance"]),"Situação":r["status"],"Última transmissão":r["latest_transmission"].strftime("%d/%m/%Y"),"Último PER/DCOMP":r["latest_number"],"Documentos":r["record_count"]} for r in competence_summary(ordered)])
            details=pd.DataFrame([{"Competência":r.competence,"Transmissão":r.transmission_date.strftime("%d/%m/%Y"),"PER/DCOMP":r.number,"Crédito passível de restituição":brl(r.refundable_credit),"Crédito original na entrega":brl(r.original_credit_at_delivery),"Crédito original utilizado":brl(r.original_credit_used),"Saldo":brl(r.original_credit_balance),"Situação interna":"Válido" if r.effective else "Retificado/substituído","Observação":r.note} for r in ordered])
            st.subheader("Saldo por competência"); st.dataframe(summary,use_container_width=True,hide_index=True)
            st.subheader("Histórico cronológico"); selected=st.selectbox("Competência",["Todas"]+sorted(details["Competência"].unique().tolist()))
            st.dataframe(details if selected=="Todas" else details[details["Competência"]==selected],use_container_width=True,hide_index=True)
            st.download_button("Baixar Excel",excel_bytes({"Resumo":summary,"Histórico":details}),"analise_perdcomp.xlsx")
        if errors:
            with st.expander(f"Avisos ({len(errors)})"):
                for error in errors: st.warning(error)
with tab2:
    uploads=st.file_uploader("Envie o PDF consolidado",type="pdf",accept_multiple_files=True,key="report")
    if uploads:
        reports=[]
        for f in uploads:
            try: reports.extend(parse_consolidated_pdf(f.name,f.getvalue()))
            except ExtractionError as exc: st.warning(f"{f.name}: {exc}")
        individual=st.session_state.get("individual_records",[])
        if reports and individual:
            frame=pd.DataFrame(reconcile(individual,reports)); frame["Valor utilizado"]=frame["Valor utilizado"].map(brl); frame["Saldo"]=frame["Saldo"].map(brl)
            st.subheader("Conciliação"); st.dataframe(frame,use_container_width=True,hide_index=True)
        elif reports: st.info("Envie primeiro os PDFs individuais na primeira aba.")
st.caption("Arquivos processados em memória; nenhum documento é armazenado.")
