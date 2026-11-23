from pathlib import Path
from decimal import Decimal
from hashlib import sha256
from zipfile import BadZipFile
import sys

import pandas as pd
import streamlit as st

PASTA_APP = str(Path(__file__).resolve().parent)
if PASTA_APP not in sys.path:
    sys.path.insert(0, PASTA_APP)
from leitura import Fonte, ler_manad, ler_xmls
from calculo_terceiros import calcular, comparar_lotacoes_xml
from controle import ler_controle
from relatorio import (
    CHAVE_MANAD, adicionar_resumo_manad, conferir_bases_manad, gerar_excel, relatorio_geral, validar_fechamento,
)


CHAVE_XML = ["Tipo de inscrição", "Estabelecimento", "Lotação"]
CHAVE_CR = ["Estabelecimento", "Código de receita"]
COL_LOT = CHAVE_XML + ["FPAS", "Código de terceiros", "Código suspenso", "Base previdenciária"]
COL_CR = CHAVE_CR + ["Apurado", "Suspenso"]

# Códigos do eSocial no Anexo I do Manual da DCTFWeb (Receita Federal, jan/2025).
# Os desdobramentos identificam, entre outros, a apuração mensal e a de 13º.
ENTIDADES = {
    "1170": ("Salário-Educação", "01 21 51"),
    "1176": ("INCRA", "01 02 21 22 51 52"),
    "1181": ("SENAI", "01 21 51"),
    "1184": ("SESI", "01 21 51"),
    "1191": ("SENAC", "01 21 51"),
    "1196": ("SESC", "01 21 51"),
    "1200": ("SEBRAE", "01 02 21 22 51 52"),
    "1205": ("FDEPM", "01 21 51"),
    "1209": ("Fundo Aeroviário", "01 21 51"),
    "1213": ("SENAR", "01 03 05 23 53"),
    "1218": ("SEST", "01 02 21 51 52"),
    "1221": ("SENAT", "01 02 21 51 52"),
    "1225": ("SESCOOP", "01 21 51"),
}
RECEITAS_TERCEIROS = {
    f"{prefixo}{sufixo}": entidade
    for prefixo, (entidade, sufixos) in ENTIDADES.items()
    for sufixo in sufixos.split()
}


@st.cache_data(show_spinner=False, max_entries=3)
def importar_xml(fontes, versoes, revisao_leitura):
    return ler_xmls(fontes)


@st.cache_data(show_spinner=False, max_entries=3)
def importar_manad(fontes, versoes, revisao_leitura):
    mestres, itens = ler_manad(fontes)
    return (mestres, itens), conferir_bases_manad(mestres, itens)


def revisao_codigo(*nomes):
    return tuple(sha256((Path(PASTA_APP) / nome).read_bytes()).hexdigest() for nome in nomes)


def selecionar_fontes(rotulo, extensoes, chave, local_recolhido=True):
    arquivos = st.file_uploader(rotulo, type=extensoes, accept_multiple_files=True, key=f"{chave}_upload")
    with (st.expander("Usar caminho local") if local_recolhido else st.container()):
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


def tabela(df, nome, chave, baixar_csv=True):
    if df.empty:
        st.info("Sem registros para exibir.")
        return
    exibicao = df.map(lambda v: float(v) if isinstance(v, Decimal) else v)
    formato = {
        coluna: st.column_config.NumberColumn(format="%.2f")
        for coluna in df if df[coluna].map(lambda v: isinstance(v, Decimal)).any()
    }
    st.dataframe(exibicao, hide_index=True, width="stretch", column_config=formato)
    if not baixar_csv:
        return
    exportacao = df.map(lambda v: format(v, "f").replace(".", ",") if isinstance(v, Decimal) else v)
    st.download_button(
        "Baixar CSV", exportacao.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name=f"{nome}.csv", mime="text/csv", key=chave,
    )


def lotacoes(apuracao):
    return pd.DataFrame(apuracao.lotacoes, columns=COL_LOT)


def contribuicoes(apuracao):
    dados = pd.DataFrame(apuracao.contribuicoes, columns=COL_CR)
    return dados[dados["Código de receita"].isin(RECEITAS_TERCEIROS)]


def conferir_calculo(apuracao, calculo, chave):
    validacao = validar_fechamento(apuracao, RECEITAS_TERCEIROS, calculo)
    if not validacao.conciliado:
        with st.expander("Por que a base não foi conciliada"):
            for pendencia in calculo.pendencias:
                st.write(pendencia)
            if validacao.diferencas_por_codigo:
                diferencas = [
                    {"Código de receita": codigo, "Entidade ou fundo": RECEITAS_TERCEIROS.get(codigo, ""),
                     "Calculado": valores[0], "No S-5011": valores[1]}
                    for codigo, valores in sorted(validacao.diferencas_por_codigo.items())
                ]
                tabela(pd.DataFrame(diferencas), "conferencia_calculo_terceiros", chave)
    return validacao.conciliado


def base_unica(calculo):
    return sum(linha["Base de terceiros"] for linha in calculo.lotacoes.values())


def quadro_por_entidade(dados, colunas):
    dados = dados.copy()
    codigos = dados["Código de receita"]
    dados["Entidade ou fundo"] = codigos.map(RECEITAS_TERCEIROS)
    dados["Código de receita"] = codigos.str.slice(0, 4) + "-" + codigos.str.slice(4)
    return dados.sort_values(["Estabelecimento", "Código de receita"])[
        ["Código de receita", "Entidade ou fundo", *colunas]
    ]


def codigo_configurado(codigos):
    return ~codigos.fillna("").isin(["", "0000"])


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
    if apuracao.alertas:
        st.caption(" ".join(apuracao.alertas))


def terceiros_apurados(apuracao, rotulo_total="Total de terceiros apurado"):
    st.subheader("Outras Entidades e Fundos")
    dados = contribuicoes(apuracao)
    empresa = dados[dados["Estabelecimento"].eq("")].copy()
    calculo = calcular(apuracao)
    indicadores = st.columns(2)
    indicadores[0].metric(rotulo_total, moeda(empresa["Apurado"].sum()))
    colunas = ["Apurado"]
    if conferir_calculo(apuracao, calculo, "apur_conferencia_base"):
        indicadores[1].metric("Base sujeita a terceiros", moeda(base_unica(calculo)))
        empresa["Base de cálculo"] = empresa["Código de receita"].map(calculo.bases)
        colunas.insert(0, "Base de cálculo")
        st.caption("Base reconstruída por lotação com a Tabela 04 e conciliada por código de receita com o S-5011.")
    else:
        indicadores[1].metric("Base sujeita a terceiros", "Em revisão")
    if empresa["Suspenso"].ne(0).any():
        colunas.append("Suspenso")
    tabela(quadro_por_entidade(empresa, colunas), "terceiros_por_entidade", "apur_cr")

    por_estabelecimento = dados[dados["Estabelecimento"].ne("")]
    if not por_estabelecimento.empty:
        with st.expander("Contribuições por estabelecimento"):
            tabela(quadro_por_entidade(por_estabelecimento, ["Estabelecimento", "Apurado", "Suspenso"]),
                   "terceiros_por_estabelecimento", "apur_cr_estab")


def detalhar_apuracao(apuracao):
    lot = lotacoes(apuracao)
    with st.expander("Lotações tributárias"):
        st.caption("Base previdenciária, FPAS e código de terceiros retornados por lotação no fechamento selecionado.")
        todas = st.checkbox("Incluir também lotações sem código de terceiros", key="apur_lot_todas")
        if not todas:
            lot = lot[codigo_configurado(lot["Código de terceiros"])]
        tabela(lot, "lotacoes_esocial", "apur_lot")
    with st.expander("Detalhe das bases previdenciárias"):
        st.caption("Campos do S-5011 por categoria e tipo de incidência, para as lotações exibidas acima.")
        bases = pd.DataFrame(apuracao.bases)
        if not bases.empty:
            bases = bases.merge(lot[CHAVE_XML].drop_duplicates(), on=CHAVE_XML)
        tabela(bases, "detalhe_bases_esocial", "apur_base")
    with st.expander("XMLs deste fechamento"):
        evidencias(apuracao)


def historico_lotacao(cadastro, empresa, apuracoes):
    linhas = [linha for linha in cadastro if linha["Empresa"] == empresa and linha["Lotação"]]
    if not linhas:
        return
    with st.expander("Histórico cadastral das lotações (S-1020)"):
        foco = {
            lot["Lotação"] for apuracao in apuracoes for lot in apuracao.lotacoes
            if lot["Código de terceiros"] not in ("", "0000")
        }
        todas = st.checkbox("Incluir outras lotações do cadastro")
        codigos = sorted({linha["Lotação"] for linha in linhas if todas or linha["Lotação"] in foco})
        if not codigos:
            st.info("Nenhuma lotação com código de terceiros nos fechamentos selecionados.")
            return
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
    st.subheader("Outras Entidades e Fundos")
    receitas = comparar_colunas(contribuicoes(antes), contribuicoes(depois), CHAVE_CR, ["Apurado", "Suspenso"])
    valores = ["Apurado antes", "Apurado depois", "Diferença de apurado"]
    suspensoes = ["Suspenso antes", "Suspenso depois", "Diferença de suspenso"]
    receitas[valores + suspensoes] = receitas[valores + suspensoes].fillna(0)
    empresa = receitas[receitas["Estabelecimento"].eq("")]
    total_antes, total_depois = empresa[["Apurado antes", "Apurado depois"]].sum()
    indicadores = st.columns(3)
    indicadores[0].metric("Terceiros antes", moeda(total_antes))
    indicadores[1].metric("Terceiros depois", moeda(total_depois))
    indicadores[2].metric("Diferença", moeda(total_depois - total_antes))

    calculo_antes, calculo_depois = calcular(antes), calcular(depois)
    com_base_antes = conferir_calculo(antes, calculo_antes, "cmp_conferencia_antes")
    com_base_depois = conferir_calculo(depois, calculo_depois, "cmp_conferencia_depois")
    com_bases = com_base_antes and com_base_depois
    if com_bases:
        empresa = empresa.copy()
        for rotulo, calculo in (("Base antes", calculo_antes), ("Base depois", calculo_depois)):
            empresa[rotulo] = empresa["Código de receita"].map(calculo.bases).fillna(Decimal("0"))
        valores = ["Base antes", "Base depois", *valores]
        st.caption(f"Base sujeita a terceiros: {moeda(base_unica(calculo_antes))} → {moeda(base_unica(calculo_depois))}. Cada remuneração entra uma vez no total da base e pode aparecer em várias linhas por entidade.")
        if antes.classificacao != depois.classificacao:
            st.caption(f"Classificação tributária no S-5011: {antes.classificacao} → {depois.classificacao}.")
    else:
        st.caption("O débito apurado vem do S-5011. A base de terceiros fica em revisão enquanto houver diferenças ou enquadramentos não cobertos.")
    somente = st.checkbox("Mostrar só entidades com diferença")
    mudancas = empresa["Mudou"]
    if com_bases:
        mudancas = mudancas | empresa["Base antes"].ne(empresa["Base depois"])
    filtradas = empresa[mudancas] if somente else empresa
    if receitas[suspensoes].ne(0).any().any():
        valores += suspensoes
    tabela(quadro_por_entidade(filtradas, valores), "comparacao_terceiros", "cmp_cr")

    st.subheader("Lotações alteradas no XML")
    alteradas = pd.DataFrame(comparar_lotacoes_xml(
        antes, depois, calculo_antes if com_base_antes else None, calculo_depois if com_base_depois else None,
    ))
    st.caption("A base declarada vem do S-5011. A base de terceiros aparece quando o cálculo foi conciliado.")
    tabela(alteradas, "comparacao_lotacoes_terceiros", "cmp_lot")
    estabs = receitas[receitas["Estabelecimento"].ne("")].copy()
    if not estabs.empty:
        with st.expander("Diferenças por estabelecimento"):
            colunas_estab = [campo for campo in valores if campo in estabs]
            tabela(quadro_por_entidade(estabs[estabs["Mudou"]], ["Estabelecimento", *colunas_estab]),
                   "comparacao_terceiros_estabelecimentos", "cmp_cr_estabs")

    dados = comparar_colunas(lotacoes(antes), lotacoes(depois), CHAVE_XML, ["Base previdenciária"])
    with st.expander("Todas as lotações do comparativo"):
        tabela(dados, "comparacao_lotacoes", "cmp_lot_todas")
    with st.expander("XMLs do comparativo"):
        st.markdown("**Antes**")
        evidencias(antes)
        st.markdown("**Depois**")
        evidencias(depois)


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
    mapear_lotacoes(base, apuracao)
    with st.expander("Rubricas da folha original"):
        opcoes = list(dict.fromkeys(detalhe["Lotação MANAD"].sort_values()))
        filtro = st.multiselect("Lotações MANAD", opcoes, format_func=lambda v: v or "Sem código")
        todas = st.checkbox("Incluir todas as lotações do MANAD")
        if filtro or todas:
            tabela(detalhe if todas else detalhe[detalhe["Lotação MANAD"].isin(filtro)],
                   "rubricas_manad", "man_rubricas")
        else:
            st.caption("Selecione uma lotação para ver suas rubricas e as parcelas da base previdenciária.")
    with st.expander("Conferência da base original (K250 × K300)"):
        st.metric("Base previdenciária registrada no MANAD", moeda(base["Base registrada"].sum()))
        st.write(f"{(~divergencia).sum()} registros conciliados entre K250 e K300 de {len(conferencia)} chaves verificadas.")
        if divergencia.any():
            tabela(conferencia[divergencia].rename(columns={"_merge": "Origem"}), "conferencia_manad", "man_check")


def mapear_lotacoes(base, apuracao):
    origem = base.groupby(["Estabelecimento", "Lotação MANAD"], as_index=False).agg(
        {"Descrição da lotação": "first", "Base registrada": "sum"}
    )
    destino = lotacoes(apuracao)
    opcoes = set(zip(destino["Estabelecimento"], destino["Lotação"]))
    with st.expander("Vincular lotações do MANAD ao eSocial"):
        st.caption("Confirme a correspondência no mesmo estabelecimento para comparar as bases previdenciárias.")
        editor = origem[["Estabelecimento", "Lotação MANAD", "Descrição da lotação"]].copy()
        editor["Lotação eSocial confirmada"] = ""
        pares = list(zip(editor["Estabelecimento"], editor["Lotação MANAD"]))
        if any(par in opcoes for par in pares) and st.checkbox("Usar códigos idênticos no mesmo estabelecimento"):
            editor["Lotação eSocial confirmada"] = [lot if (estab, lot) in opcoes else "" for estab, lot in pares]
        mapa = st.data_editor(
            editor, hide_index=True, disabled=list(editor.columns[:3]), width="stretch",
            key=f"mapa_{apuracao.empresa}_{apuracao.competencia}_{apuracao.recibo}",
        )
    origem["Lotação"] = mapa["Lotação eSocial confirmada"].fillna("").str.strip()
    reconhecidas = pd.Series(
        [(estab, lot) in opcoes and bool(lot) for estab, lot in zip(origem["Estabelecimento"], origem["Lotação"])],
        index=origem.index, dtype=bool,
    )
    confirmado = origem[reconhecidas].groupby(["Estabelecimento", "Lotação"], as_index=False).agg(
        {"Base registrada": "sum", "Lotação MANAD": lambda codigos: ", ".join(c or "Sem código" for c in codigos)}
    )
    resultado = destino.merge(confirmado, how="left", on=["Estabelecimento", "Lotação"], indicator=True)
    resultado["Vínculo MANAD"] = resultado.pop("_merge").map({"left_only": "A confirmar", "both": "Confirmado"})
    resultado["Diferença de base previdenciária"] = resultado["Base previdenciária"] - resultado["Base registrada"]
    resultado = resultado.rename(columns={"Base registrada": "Base previdenciária MANAD",
                                          "Base previdenciária": "Base previdenciária XML"})
    campos = ["Lotação", "Estabelecimento", "FPAS", "Código de terceiros", "Lotação MANAD",
              "Base previdenciária MANAD", "Base previdenciária XML", "Diferença de base previdenciária", "Vínculo MANAD"]
    st.subheader("Lotações com código de terceiros no XML")
    relevantes = codigo_configurado(resultado["Código de terceiros"])
    tabela(resultado.loc[relevantes, campos], "comparacao_manad_xml", "man_cmp")
    if (~relevantes).any():
        with st.expander("Lotações XML sem código de terceiros"):
            tabela(resultado.loc[~relevantes, campos], "comparacao_manad_xml_sem_codigo", "man_cmp_sem_codigo")
    if (~reconhecidas).any():
        with st.expander(f"Lotações MANAD sem correspondência confirmada ({(~reconhecidas).sum()})"):
            tabela(origem[~reconhecidas], "lotes_manad_pendentes", "man_pendentes")


def registrar_dctfweb(empresa, apuracoes):
    with st.expander("Usar DCTFWeb como referência da comparação"):
        st.caption("Registre a situação e o débito apurado de Outras Entidades e Fundos. Os valores ficam na sessão e no Excel exportado.")
        anos = [int(a.competencia[:4]) for a in apuracoes]
        periodos = [
            periodo
            for ano in range(max(anos), min(anos) - 1, -1)
            for periodo in [*(f"{ano}-{mes:02d}" for mes in range(12, 0, -1)), str(ano)]
        ]
        periodo = st.selectbox(
            "Competência da referência DCTFWeb", periodos, index=None, format_func=formatar_competencia,
            key=f"dctf_competencia_{empresa}",
        )
        if periodo is None:
            return
        registros = st.session_state.setdefault(f"referencias_dctfweb_{empresa}", {})
        situacao, anterior, atual = registros.get(periodo, ("Não informada", None, None))
        with st.form(f"dctfweb_{empresa}_{periodo}"):
            situacoes = ["Não informada", "Em andamento", "Ativa", "Retificada"]
            estado = st.selectbox("Situação da declaração", situacoes, index=situacoes.index(situacao))
            campos = st.columns(2)
            antes = campos[0].number_input(
                "Débito anterior de terceiros (R$)", min_value=0.0, step=0.01, format="%.2f",
                value=float(anterior) if anterior is not None else None,
            )
            depois = campos[1].number_input(
                "Débito em análise de terceiros (R$)", min_value=0.0, step=0.01, format="%.2f",
                value=float(atual) if atual is not None else None,
            )
            if st.form_submit_button("Registrar referência"):
                registros[periodo] = (
                    estado,
                    Decimal(f"{antes:.2f}") if antes is not None else None,
                    Decimal(f"{depois:.2f}") if depois is not None else None,
                )


def formatar_competencia(periodo):
    if not periodo:
        return ""
    if len(periodo) == 4:
        return f"13º de {periodo}"
    return f"{periodo[5:]}/{periodo[:4]}"


@st.cache_data(show_spinner=False, max_entries=3)
def preparar_relatorio(empresa, apuracoes, cadastro, referencias, mestres=(), controle=None,
                       apenas_movimentos=False, filtrar_controle=False, versao=(),
                       avisos_xml=(), conferencia_manad=None):
    abas = relatorio_geral(apuracoes, RECEITAS_TERCEIROS, cadastro, referencias, controle, avisos_xml)
    if mestres:
        adicionar_resumo_manad(abas, empresa, mestres, conferencia_manad)
    if not apenas_movimentos:
        return abas, gerar_excel(abas, empresa)
    nomes = (
        "Movimentos", "Entidades", "Lotações", "Estabelecimentos", "Controle",
        "DCTFWeb", "Simulações", "Lotações simuladas", "Entidades simuladas", "Verificação",
    )
    registro = {nome: abas[nome] for nome in nomes if nome in abas}
    if filtrar_controle and controle:
        registro = {nome: [linha for linha in linhas if not linha["Competência"] or linha["Competência"] in controle]
                    for nome, linhas in registro.items()}
    return {**abas, **registro}, gerar_excel(registro, empresa)


def mostrar_consolidado(fluxo, empresa, apuracoes, cadastro, mestres=(), controle=None, focar_controle=False,
                        avisos_xml=(), conferencia_manad=None):
    st.subheader("Outras Entidades e Fundos por competência")
    referencias = st.session_state.get(f"referencias_dctfweb_{empresa}", {})
    with st.spinner("Consolidando fechamentos e preparando o Excel..."):
        abas, excel = preparar_relatorio(
            empresa, apuracoes, cadastro, referencias, mestres, controle,
            apenas_movimentos=fluxo == "XML × XML", filtrar_controle=focar_controle,
            versao=revisao_codigo("relatorio.py", "calculo_terceiros.py"),
            avisos_xml=avisos_xml, conferencia_manad=conferencia_manad,
        )
    com_mudanca = {linha["Competência"] for linha in abas["Entidades"] if linha["Variação do débito"]}
    if fluxo == "MANAD × XML":
        comuns = sum(bool(linha["S-5011"]) for linha in abas["MANAD"])
        st.caption(f"{len(abas['MANAD'])} competências no MANAD. {comuns} têm S-5011 no ZIP.")
        nomes = ["MANAD"]
    else:
        st.caption(f"{len(abas['Resumo'])} competências · {len(abas['Fechamentos'])} fechamentos · {len(com_mudanca)} competências com mudança no débito")
        nomes = ["Resumo", "Fechamentos"] if fluxo == "Apurar XML" else ["Movimentos", "Entidades", "Lotações"]
        if fluxo == "XML × XML":
            nomes += [nome for nome in ("Controle", "Simulações", "DCTFWeb") if abas.get(nome)]
            sem_data = sum(linha["Recebido em"] is None for linha in abas["Fechamentos"])
            if sem_data:
                st.caption(f"{sem_data} totalizadores sem data de fechamento. Importe os S-1299 correspondentes para ordenar esses XMLs.")
    st.download_button(
        "Baixar Excel das alterações" if fluxo == "XML × XML" else "Baixar Excel completo",
        excel, file_name=f"{'registro' if fluxo == 'XML × XML' else 'auditoria'}_terceiros_{empresa}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", on_click="ignore", type="primary",
    )
    with st.expander("Conferência dos dados"):
        fechamentos = abas["Fechamentos"]
        conciliados = sum(linha["Conferência da base"] == "Conciliada" for linha in fechamentos)
        vinculados = sum(linha["Vínculo do fechamento"] == "Conferido" for linha in fechamentos)
        st.write(f"{conciliados} de {len(fechamentos)} bases conciliadas por código de receita. "
                 f"{vinculados} de {len(fechamentos)} vínculos S-1299/S-5011 conferidos.")
        if abas.get("Verificação"):
            tabela(pd.DataFrame(abas["Verificação"]), "verificacao_dos_dados", "visao_verificacao", baixar_csv=False)
        if fluxo == "MANAD × XML":
            divergencias = sum((linha["Chaves divergentes"] or 0) for linha in abas["MANAD"])
            st.write(f"{divergencias} vínculos de trabalhador, lotação e tipo de folha divergentes entre K250 e K300.")
    paineis = st.tabs(nomes) if len(nomes) > 1 else [st.container()]
    for nome, painel in zip(nomes, paineis):
        with painel:
            quadro = pd.DataFrame(abas[nome])
            if not quadro.empty:
                quadro["Competência"] = quadro["Competência"].map(formatar_competencia)
                # Mostra a trilha de XML no Excel e na aba Fechamentos.
                if nome == "Movimentos":
                    colunas = [
                        "Competência", "Movimento", "Recebido depois em", "Débito antes", "Débito depois",
                        "Variação do débito", "Códigos com débito alterado", "Lotações alteradas",
                        "Variação da base", "Bases conciliadas",
                    ]
                    if quadro["Ordem dos XMLs"].eq("Parcial").any():
                        colunas.append("Ordem dos XMLs")
                    if controle:
                        colunas.extend(["Data no controle", "Situação no controle"])
                    quadro = quadro.loc[:, colunas].sort_values("Recebido depois em", ascending=False)
                if nome == "Entidades" and not quadro["Variação do suspenso"].ne(0).any():
                    quadro = quadro.drop(columns=["Suspenso antes", "Suspenso depois", "Variação do suspenso"])
                if nome == "Lotações" and not quadro["Código suspenso antes → depois"].ne("").any():
                    quadro = quadro.drop(columns="Código suspenso antes → depois")
                if nome == "Resumo":
                    colunas = [
                        "Competência", "S-5011", "Base inicial", "Base recente", "Variação da base",
                        "Débito inicial", "Débito recente", "Variação acumulada", "Variação do último movimento",
                    ]
                    quadro = quadro.loc[:, colunas]
                if nome in {"Resumo", "MANAD", "Fechamentos"}:
                    quadro = quadro.iloc[::-1]
            if nome == "Resumo":
                st.caption("A variação acumulada usa o primeiro e o último fechamento disponíveis. A última mudança compara o fechamento imediatamente anterior ao movimento.")
            if nome == "Simulações":
                st.caption("Hipóteses de reenquadramento calculadas com o S-1020. O novo S-5011 confirma o que foi apurado.")
            if nome == "DCTFWeb":
                st.caption("Os recibos candidatos coincidem pelo total. Confira os códigos de receita no detalhe do fechamento.")
            if nome == "Controle":
                st.caption("A planilha aponta as competências. Os valores e os recibos vêm do S-5011, vinculado ao fechamento pelo recibo.")
            if nome == "Lotações":
                st.caption("As mudanças de base declarada, FPAS e código são observadas no XML. A base efetiva de terceiros exige conciliação por entidade.")
            if nome == "MANAD":
                st.caption("O K250 mostra a base previdenciária original. As colunas de terceiros vêm do último S-5011 disponível.")
            tabela(quadro, nome, f"visao_{nome}", baixar_csv=False)
            if nome == "Simulações":
                for detalhe in ("Lotações simuladas", "Entidades simuladas"):
                    with st.expander(detalhe):
                        linhas = pd.DataFrame(abas[detalhe])
                        linhas["Competência"] = linhas["Competência"].map(formatar_competencia)
                        tabela(linhas, detalhe, f"visao_{detalhe}", baixar_csv=False)


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
            apuracoes, inventario, avisos, cadastro = importar_xml(*fontes, revisao_codigo("leitura.py"))
        with st.expander("Arquivos lidos"):
            st.dataframe([{"Evento": tipo, "Arquivos": n} for tipo, n in sorted(inventario.items())], hide_index=True)
            for aviso in avisos:
                st.warning(aviso)
        if not apuracoes:
            st.warning("Nenhum totalizador S-5011 foi encontrado.")
            return
        empresa = st.selectbox("Empresa", sorted({a.empresa for a in apuracoes}))
        arquivo_empresa = [a for a in apuracoes if a.empresa == empresa]
        controle = {}
        focar_controle = False
        if fluxo == "XML × XML":
            registrar_dctfweb(empresa, arquivo_empresa)
            with st.expander("Usar planilha de controle da retificação"):
                arquivos_controle, _ = selecionar_fontes("Controle de competências", ["xlsx"], "controle",
                                                         local_recolhido=False)
                if arquivos_controle:
                    if len(arquivos_controle) != 1:
                        st.warning("Importe uma planilha de controle por vez.")
                    else:
                        try:
                            controle = ler_controle(arquivos_controle[0])
                        except (ValueError, OSError, BadZipFile, KeyError) as erro:
                            st.warning(f"Controle não importado: {erro}")
                if controle:
                    st.caption(f"{len(controle)} competências marcadas pela data ou situação da planilha.")
                    focar_controle = st.checkbox("Mostrar e exportar só as competências marcadas")
        competencias = {a.competencia for a in arquivo_empresa}
        manad = None
        mestres = ()
        conferencia_manad = None
        if fluxo == "MANAD × XML":
            fontes_manad = selecionar_fontes("MANAD original", ["txt"], "manad")
            if not fontes_manad[0]:
                return
            manad, conferencia_manad = importar_manad(*fontes_manad, revisao_codigo("leitura.py", "relatorio.py"))
            mestres, _ = manad
            if not mestres:
                st.warning("Nenhum registro K250 foi encontrado no MANAD importado.")
                return
            competencias_manad = {
                linha["Competência"] for linha in mestres if linha["Estabelecimento"].startswith(empresa)
            }
            if not competencias_manad:
                st.warning("O MANAD contém registros K250 de outro empregador. Confira a empresa selecionada.")
                return
            competencias &= competencias_manad
        mostrar_consolidado(
            fluxo, empresa, arquivo_empresa, cadastro, mestres, controle, focar_controle, tuple(avisos), conferencia_manad,
        )
        if not competencias or not st.checkbox("Detalhar uma competência", key=f"detalhar_{fluxo}"):
            return
        opcoes_competencia = sorted(competencias, reverse=True)
        chave_periodo = f"competencia_{empresa}_{fluxo}"
        if chave_periodo in st.session_state and st.session_state[chave_periodo] not in competencias:
            st.session_state[chave_periodo] = opcoes_competencia[0]
        periodo = st.selectbox(
            "Competência", opcoes_competencia, key=chave_periodo,
            format_func=lambda p: f"13º de {p}" if len(p) == 4 else p,
        )
        opcoes = [a for a in arquivo_empresa if a.competencia == periodo]
        identificadas = [i for i, a in enumerate(opcoes) if a.data_fechamento]
        posterior = identificadas[-1] if identificadas else len(opcoes) - 1
        rotulos_fechamento = {
            "Apurar XML": "Fechamento",
            "XML × XML": "Fechamento depois",
            "MANAD × XML": "Fechamento XML de referência",
        }
        depois = selecionar_fechamento(
            opcoes, rotulos_fechamento[fluxo], f"depois_{empresa}_{periodo}_{fluxo}", posterior,
        )
        referencias = (depois,)
        if fluxo == "Apurar XML":
            terceiros_apurados(depois)
            detalhar_apuracao(depois)
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
            if not antes.data_fechamento or not depois.data_fechamento or antes.data_fechamento == depois.data_fechamento:
                st.warning("A ordem deste par não pôde ser confirmada pelos recibos. A comparação segue a seleção manual.")
            comparar_xml(antes, depois)
            referencias = (antes, depois)
        else:
            terceiros_apurados(depois, "Total de terceiros no fechamento XML")
            st.caption("O MANAD fornece a base previdenciária original. Para comparar os débitos de terceiros antes e depois, use dois S-5011 no fluxo XML × XML.")
            if manad is not None:
                comparar_manad(depois, *manad)
            detalhar_apuracao(depois)
        historico_lotacao(cadastro, empresa, referencias)
    except (OSError, ValueError, BadZipFile, ArithmeticError) as erro:
        st.error(f"Falha na leitura dos arquivos: {erro}")


if __name__ == "__main__":
    principal()
