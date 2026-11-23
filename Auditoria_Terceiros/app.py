from pathlib import Path
from decimal import Decimal
from zipfile import BadZipFile
import sys

import pandas as pd
import streamlit as st

PASTA_APP = str(Path(__file__).resolve().parent)
if PASTA_APP not in sys.path:
    sys.path.insert(0, PASTA_APP)
from leitura import Fonte, ler_manad, ler_xmls


CHAVE_XML = ["Tipo de inscrição", "Estabelecimento", "Lotação"]
CHAVE_CR = ["Estabelecimento", "Código de receita"]
CHAVE_MANAD = ["Estabelecimento", "Lotação MANAD", "Competência", "Tipo de folha", "Trabalhador"]
COL_LOT = CHAVE_XML + ["FPAS", "Código de terceiros", "Código suspenso", "Base previdenciária"]
COL_CR = CHAVE_CR + ["Apurado", "Suspenso"]


@st.cache_data(show_spinner=False, max_entries=3)
def importar_xml(fontes, versoes):
    return ler_xmls(fontes)


@st.cache_data(show_spinner=False, max_entries=3)
def importar_manad(fontes, versoes):
    return ler_manad(fontes)


def selecionar_fontes(rotulo, extensoes, chave):
    arquivos = st.file_uploader(rotulo, type=extensoes, accept_multiple_files=True, key=f"{chave}_upload")
    with st.expander("Usar caminho local"):
        caminhos = st.text_area(
            "Um caminho por linha", key=f"{chave}_local",
            help="Permite ler arquivos grandes diretamente no computador onde o Streamlit está rodando.",
        )
    fontes = [Fonte(f.name, conteudo=f.getvalue()) for f in arquivos]
    versoes = []
    for caminho in caminhos.splitlines():
        if not caminho.strip():
            continue
        p = Path(caminho.strip().strip('"')).expanduser().resolve()
        if not p.is_file() or p.suffix.lower().lstrip(".") not in extensoes:
            raise ValueError(f"Arquivo inválido ou inacessível: {p}")
        if any(f.caminho == str(p) for f in fontes):
            continue
        dados = p.stat()
        fontes.append(Fonte(p.name, caminho=str(p)))
        versoes.append((str(p), dados.st_mtime_ns, dados.st_size))
    return tuple(fontes), tuple(versoes)


def tabela(df, nome, chave):
    if df.empty:
        st.info("Sem registros para exibir.")
        return
    exibicao = df.map(lambda v: float(v) if isinstance(v, Decimal) else v)
    st.dataframe(exibicao, hide_index=True, width="stretch")
    exportacao = df.map(lambda v: format(v, "f").replace(".", ",") if isinstance(v, Decimal) else v)
    st.download_button(
        "Baixar CSV", exportacao.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name=f"{nome}.csv", mime="text/csv", key=chave,
    )


def lotacoes(apuracao):
    return pd.DataFrame(apuracao.lotacoes, columns=COL_LOT)


def contribuicoes(apuracao):
    return pd.DataFrame(apuracao.contribuicoes, columns=COL_CR)


def selecionar_fechamento(opcoes, rotulo, chave, indice):
    def rotular(i):
        a = opcoes[i]
        data = a.data_fechamento[:19].replace("T", " ") if a.data_fechamento else "Data indisponível"
        return f"{data} | recibo {a.recibo or 'não identificado'}"

    escolha = st.selectbox(rotulo, range(len(opcoes)), index=indice, format_func=rotular, key=chave)
    return opcoes[escolha]


def evidencias(apuracao):
    st.write("Totalizador S-5011", apuracao.arquivo)
    if apuracao.fechamento:
        st.write("Fechamento S-1299", apuracao.fechamento)
    else:
        st.caption("S-1299 correspondente ausente na importação. Confira o recibo para validar a posição no histórico.")


def apurar_xml(apuracao):
    evidencias(apuracao)
    abas = st.tabs(["Lotações", "Contribuições por código de receita", "Detalhe das bases"])
    with abas[0]:
        st.caption("A coluna de base mostra a base previdenciária retornada por lotação. FPAS e código de terceiros são os usados no fechamento.")
        dados = lotacoes(apuracao)
        tabela(dados, "lotacoes_esocial", "apur_lot")
        with st.expander("Base previdenciária agrupada por FPAS e código de terceiros"):
            grupos = dados.groupby(["FPAS", "Código de terceiros"], as_index=False)["Base previdenciária"].sum()
            tabela(grupos, "base_por_fpas_e_codigo", "apur_grupos")
    with abas[1]:
        cr = contribuicoes(apuracao)
        nivel = st.radio("Consolidação", ["Empresa", "Estabelecimentos"], horizontal=True)
        tabela(cr[cr["Estabelecimento"].eq("") == (nivel == "Empresa")], "contribuicoes_esocial", "apur_cr")
    with abas[2]:
        st.caption("Campos do S-5011 por categoria e tipo de incidência. O detalhamento por rubrica exige os eventos de remuneração e a tabela S-1010.")
        tabela(pd.DataFrame(apuracao.bases), "detalhe_bases_esocial", "apur_base")


def resumo_fechamentos(apuracoes):
    with st.expander("Fechamentos disponíveis no período"):
        linhas = [
            {
                "Competência": a.competencia,
                "Apuração": "Anual" if a.tipo == "2" else "Mensal",
                "Data de fechamento": a.data_fechamento,
                "Recibo de fechamento": a.recibo,
                "Base previdenciária das lotações": sum(lot["Base previdenciária"] for lot in a.lotacoes),
                "Arquivo S-5011": a.arquivo,
            }
            for a in reversed(apuracoes)
        ]
        tabela(pd.DataFrame(linhas), "fechamentos_esocial", "apur_fechamentos")


def historico_lotacao(cadastro, empresa):
    linhas = [linha for linha in cadastro if linha["Empresa"] == empresa and linha["Lotação"]]
    if not linhas:
        return
    with st.expander("Histórico cadastral das lotações (S-1020)"):
        codigos = sorted({linha["Lotação"] for linha in linhas})
        codigo = st.selectbox("Lotação para consultar", codigos, index=None, placeholder="Escolha uma lotação")
        if codigo:
            df = pd.DataFrame(linha for linha in linhas if linha["Lotação"] == codigo)
            tabela(df.sort_values(["Recebido em", "Início da vigência"]), "historico_lotacao", "hist_lot")


def comparar_colunas(antes, depois, chave, numericas):
    resultado = antes.merge(depois, on=chave, how="outer", suffixes=(" antes", " depois"), indicator=True)
    resultado["Presença"] = resultado.pop("_merge").map(
        {"left_only": "Só antes", "right_only": "Só depois", "both": "Nos dois"}
    )
    for campo in numericas:
        a, d = f"{campo} antes", f"{campo} depois"
        resultado[f"Diferença de {campo.lower()}"] = resultado[d].fillna(0) - resultado[a].fillna(0)
    comparaveis = [col for col in antes.columns if col not in chave]
    mudancas = pd.Series(False, index=resultado.index)
    for col in comparaveis:
        mudancas |= resultado[f"{col} antes"].fillna("") != resultado[f"{col} depois"].fillna("")
    resultado["Mudou"] = mudancas | resultado["Presença"].ne("Nos dois")
    return resultado


def comparar_xml(antes, depois):
    for rotulo, apuracao in (("Antes", antes), ("Depois", depois)):
        with st.expander(rotulo):
            evidencias(apuracao)
    somente = st.checkbox("Mostrar somente linhas com mudança", value=True)
    abas = st.tabs(["Lotações", "Contribuições por código de receita"])
    with abas[0]:
        df = comparar_colunas(lotacoes(antes), lotacoes(depois), CHAVE_XML, ["Base previdenciária"])
        tabela(df[df["Mudou"]] if somente else df, "comparacao_lotacoes", "cmp_lot")
    with abas[1]:
        nivel = st.radio("Consolidação", ["Empresa", "Estabelecimentos"], horizontal=True)
        df = comparar_colunas(contribuicoes(antes), contribuicoes(depois), CHAVE_CR, ["Apurado", "Suspenso"])
        df = df[df["Estabelecimento"].eq("") == (nivel == "Empresa")]
        tabela(df[df["Mudou"]] if somente else df, "comparacao_contribuicoes", "cmp_cr")


def comparar_manad(apuracao, mestres, itens):
    if not mestres or not itens:
        st.warning("A importação precisa conter os registros K250 e K300 do MANAD.")
        return
    base = pd.DataFrame(mestres)
    detalhe = pd.DataFrame(itens)
    for df in (base, detalhe):
        df.drop(df.index[
            df["Competência"].ne(apuracao.competencia) |
            ~df["Estabelecimento"].str.startswith(apuracao.empresa)
        ], inplace=True)
    if base.empty:
        st.warning("O MANAD importado não tem K250 para esta empresa e competência.")
        return
    fontes_por_chave = base.groupby(CHAVE_MANAD)["Arquivo"].nunique()
    if fontes_por_chave.gt(1).any():
        st.warning("Há arquivos MANAD sobrepostos nesta competência. Importe uma única versão da folha original.")
        return
    valores = base.groupby(CHAVE_MANAD, as_index=False)["Base registrada"].sum()
    parcelas = detalhe.groupby(CHAVE_MANAD, as_index=False)["Parcela da base"].sum()
    conferencia = valores.merge(parcelas, how="outer", on=CHAVE_MANAD, indicator=True)
    conferencia["Diferença"] = conferencia["Parcela da base"].fillna(0) - conferencia["Base registrada"].fillna(0)
    divergencia = conferencia["Diferença"].ne(0) | conferencia["_merge"].ne("both")
    st.metric("Base previdenciária registrada no MANAD", moeda(base["Base registrada"].sum()))
    st.write(f"{(~divergencia).sum()} registros conciliados entre K250 e K300 de {len(conferencia)} chaves verificadas.")
    with st.expander("Conferência K250 × K300"):
        tabela(conferencia[divergencia].rename(columns={"_merge": "Origem"}), "conferencia_manad", "man_check")
    abas = st.tabs(["Comparar por lotação", "Rubricas da folha original", "Apuração posterior"])
    with abas[0]:
        mapear_lotacoes(base, apuracao)
    with abas[1]:
        opcoes = list(dict.fromkeys(detalhe["Lotação MANAD"].sort_values()))
        filtro = st.multiselect("Lotações MANAD", opcoes, format_func=lambda v: v or "Sem código")
        tabela(detalhe[detalhe["Lotação MANAD"].isin(filtro)] if filtro else detalhe,
               "rubricas_manad", "man_rubricas")
    with abas[2]:
        apurar_xml(apuracao)


def mapear_lotacoes(base, apuracao):
    st.caption("Confirme a correspondência da lotação antes de comparar as bases previdenciárias. O FPAS e o código de terceiros exibidos são do fechamento XML selecionado.")
    origem = base.groupby(["Estabelecimento", "Lotação MANAD"], as_index=False).agg(
        {"Descrição da lotação": "first", "Base registrada": "sum"}
    )
    destino = lotacoes(apuracao)
    opcoes = set(zip(destino["Estabelecimento"], destino["Lotação"]))
    editor = origem[["Estabelecimento", "Lotação MANAD", "Descrição da lotação"]].copy()
    editor["Lotação eSocial confirmada"] = ""
    if any((estab, lot) in opcoes for estab, lot in zip(editor["Estabelecimento"], editor["Lotação MANAD"])):
        if st.checkbox("Usar códigos idênticos no mesmo estabelecimento como correspondência"):
            editor["Lotação eSocial confirmada"] = [
                lot if (estab, lot) in opcoes else "" for estab, lot in zip(editor["Estabelecimento"], editor["Lotação MANAD"])
            ]
    mapa = st.data_editor(
        editor, hide_index=True, disabled=list(editor.columns[:3]), width="stretch",
        key=f"mapa_{apuracao.empresa}_{apuracao.competencia}_{apuracao.recibo}",
    )
    origem["Lotação"] = mapa["Lotação eSocial confirmada"].fillna("").str.strip()
    reconhecidas = pd.Series(
        [(estab, lot) in opcoes and bool(lot) for estab, lot in zip(origem["Estabelecimento"], origem["Lotação"])],
        index=origem.index, dtype=bool,
    )
    if (~reconhecidas).any():
        with st.expander(f"Lotações MANAD sem correspondência confirmada ({(~reconhecidas).sum()})"):
            tabela(origem[~reconhecidas], "lotes_manad_pendentes", "man_pendentes")
    confirmado = origem[reconhecidas].groupby(["Estabelecimento", "Lotação"], as_index=False)["Base registrada"].sum()
    resultado = confirmado.merge(destino, how="inner", on=["Estabelecimento", "Lotação"])
    resultado["Diferença de base previdenciária"] = resultado["Base previdenciária"] - resultado["Base registrada"]
    tabela(resultado, "comparacao_manad_xml", "man_cmp")


def moeda(valor):
    return f"R$ {valor:,.2f}".translate(str.maketrans({",": ".", ".": ","}))


def principal():
    st.set_page_config(page_title="Auditoria de Terceiros", layout="wide")
    st.title("Auditoria de Terceiros")
    fluxo = st.radio("Fluxo", ["Apurar XML", "XML × XML", "MANAD × XML"], horizontal=True)
    try:
        fontes = selecionar_fontes("XMLs do eSocial ou pacotes ZIP", ["xml", "zip"], "xml")
        if not fontes[0]:
            return
        with st.spinner("Localizando fechamentos e lendo totalizadores..."):
            apuracoes, inventario, avisos, cadastro = importar_xml(*fontes)
        with st.expander("Arquivos lidos"):
            st.dataframe([{"Evento": tipo, "Arquivos": n} for tipo, n in sorted(inventario.items())], hide_index=True)
            for aviso in avisos:
                st.warning(aviso)
        if not apuracoes:
            st.warning("Nenhum totalizador S-5011 foi encontrado.")
            return
        empresa = st.selectbox("Empresa", sorted({a.empresa for a in apuracoes}))
        historico_lotacao(cadastro, empresa)
        arquivo_empresa = [a for a in apuracoes if a.empresa == empresa]
        if fluxo == "Apurar XML":
            resumo_fechamentos(arquivo_empresa)
        periodo = st.selectbox("Competência", sorted({a.competencia for a in arquivo_empresa}, reverse=True),
                              format_func=lambda p: f"13º de {p}" if len(p) == 4 else p)
        opcoes = [a for a in arquivo_empresa if a.competencia == periodo]
        identificadas = [i for i, a in enumerate(opcoes) if a.data_fechamento]
        posterior = identificadas[-1] if identificadas else len(opcoes) - 1
        depois = selecionar_fechamento(opcoes, "Fechamento" if fluxo == "Apurar XML" else "Fechamento depois",
                                        f"depois_{empresa}_{periodo}_{fluxo}", posterior)
        if fluxo == "Apurar XML":
            apurar_xml(depois)
        elif fluxo == "XML × XML":
            anteriores = [a for a in opcoes if a != depois]
            if not anteriores:
                st.info("Só há um fechamento disponível para esta competência.")
                return
            candidatos = [i for i, a in enumerate(anteriores) if a.data_fechamento and a.data_fechamento < depois.data_fechamento]
            antes = selecionar_fechamento(anteriores, "Fechamento antes", f"antes_{empresa}_{periodo}_{depois.recibo}",
                                            candidatos[-1] if candidatos else 0)
            if antes.data_fechamento and depois.data_fechamento and antes.data_fechamento > depois.data_fechamento:
                st.warning("O fechamento selecionado como antes tem data posterior ao fechamento depois.")
            comparar_xml(antes, depois)
        else:
            fontes_manad = selecionar_fontes("MANAD original", ["txt"], "manad")
            if fontes_manad[0]:
                comparar_manad(depois, *importar_manad(*fontes_manad))
    except (OSError, ValueError, BadZipFile, ArithmeticError) as erro:
        st.error(f"Falha na leitura dos arquivos: {erro}")


if __name__ == "__main__":
    principal()
