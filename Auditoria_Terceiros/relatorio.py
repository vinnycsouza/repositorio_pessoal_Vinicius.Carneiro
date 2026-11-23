from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from calculo_terceiros import CHAVE, Calculo, calcular, comparar_lotacoes_xml, mudancas_lotacao, propostas_cadastrais
from leitura import Apuracao, ZERO


CHAVE_MANAD = ["Estabelecimento", "Lotação MANAD", "Competência", "Tipo de folha", "Trabalhador"]


@dataclass
class Fechamento:
    apuracao: Apuracao
    debitos: dict
    calculo: Calculo
    conciliado: bool
    suspensos: dict = field(default_factory=dict)
    estabelecimentos: dict = field(default_factory=dict)
    diferencas_por_codigo: dict = field(default_factory=dict)

    @property
    def total(self):
        return sum(self.debitos.values(), ZERO)

    @property
    def base(self):
        if not self.conciliado:
            return None
        return sum((lotacao["Base de terceiros"] for lotacao in self.calculo.lotacoes.values()), ZERO)

    @property
    def data(self):
        valor = self.apuracao.data_fechamento
        return datetime.fromisoformat(valor).replace(tzinfo=None) if valor else None


def validar_fechamento(apuracao, catalogo, calculo=None):
    calculo = calcular(apuracao) if calculo is None else calculo
    debitos, suspensos, estabelecimentos = (defaultdict(lambda: ZERO) for _ in range(3))
    for cr in apuracao.contribuicoes:
        codigo = cr["Código de receita"]
        if codigo not in catalogo:
            continue
        if cr["Estabelecimento"]:
            estabelecimentos[(cr["Estabelecimento"], codigo, "Débito")] += cr["Apurado"]
            estabelecimentos[(cr["Estabelecimento"], codigo, "Suspenso")] += cr["Suspenso"]
            continue
        debitos[codigo] += cr["Apurado"]
        suspensos[codigo] += cr["Suspenso"]
    diferencas = {
        cr: (calculo.debitos.get(cr, ZERO), debitos.get(cr, ZERO))
        for cr in debitos.keys() | calculo.debitos.keys()
        if debitos.get(cr, ZERO) != calculo.debitos.get(cr, ZERO)
    }
    conciliado = not calculo.pendencias and not diferencas
    return Fechamento(apuracao, dict(debitos), calculo, conciliado, dict(suspensos), dict(estabelecimentos), diferencas)


def variacao(antes, depois):
    return depois - antes if antes is not None and depois is not None else None


def detalhe_entidade(a, b, catalogo, somente_mudancas=True):
    linhas = []
    for codigo in sorted(a.debitos.keys() | b.debitos.keys() | a.calculo.bases.keys() | b.calculo.bases.keys()):
        antes, depois = a.debitos.get(codigo, ZERO), b.debitos.get(codigo, ZERO)
        ba = a.calculo.bases.get(codigo, ZERO) if a.conciliado else None
        bd = b.calculo.bases.get(codigo, ZERO) if b.conciliado else None
        sa, sd = a.suspensos.get(codigo, ZERO), b.suspensos.get(codigo, ZERO)
        if not somente_mudancas or antes != depois or sa != sd or (ba is not None and bd is not None and ba != bd):
            linhas.append({
                "Receita": f"{codigo[:4]}-{codigo[4:]}", "Entidade": catalogo[codigo],
                "Base antes": ba, "Base depois": bd, "Variação da base": variacao(ba, bd),
                "Débito antes": antes, "Débito depois": depois, "Variação do débito": depois - antes,
                "Suspenso antes": sa, "Suspenso depois": sd, "Variação do suspenso": sd - sa,
            })
    return linhas


def detalhe_estabelecimento(a, b, catalogo):
    if not a.estabelecimentos or not b.estabelecimentos:
        return []
    linhas = []
    for estab, codigo, campo in sorted(a.estabelecimentos.keys() | b.estabelecimentos.keys()):
        chave = estab, codigo, campo
        antes, depois = a.estabelecimentos.get(chave, ZERO), b.estabelecimentos.get(chave, ZERO)
        if antes != depois:
            linhas.append({
                "Estabelecimento": estab, "Receita": f"{codigo[:4]}-{codigo[4:]}", "Entidade": catalogo[codigo],
                "Campo": campo, "Valor antes": antes, "Valor depois": depois, "Variação": depois - antes,
            })
    return linhas


def dados_fechamento(f):
    a = f.apuracao
    return {
        "Competência": a.competencia, "Recebido em": f.data, "Classificação tributária": a.classificacao,
        "Base de terceiros": f.base, "Débito de terceiros": f.total,
        "Conferência da base": "Conciliada" if f.conciliado else "Em revisão",
        "Motivo da revisão": (" / ".join(f.calculo.pendencias[:3]) or "O cálculo diverge do débito no S-5011")
        if not f.conciliado else "",
        "Vínculo do fechamento": " ".join(a.alertas) or ("Conferido" if f.data else "Data indisponível"),
        "Recibo S-1299": a.recibo, "XML S-5011": a.arquivo, "XML S-1299": a.fechamento,
    }


def comparar_controle(competencia, referencia, datados):
    data = referencia["Data no controle"]
    antes = depois = None
    if data is None:
        resultado = "Sem data no controle"
    else:
        anteriores = [f for f in datados if f.data.date() < data]
        posteriores = [f for f in datados if f.data.date() >= data]
        na_data = [f for f in posteriores if f.data.date() == data]
        antes = anteriores[-1] if anteriores else None
        depois = na_data[-1] if na_data else (posteriores[0] if posteriores else None)
        if depois is None:
            resultado = "Sem fechamento na data ou posterior"
        elif depois.data.date() != data:
            resultado = "Fechamento posterior candidato"
        else:
            resultado = "Fechamento na data"
    return {
        "Competência": competencia, **referencia, "Busca no XML": resultado,
        "Fechamento anterior": antes.data if antes else None,
        "Fechamento na data ou posterior": depois.data if depois else None,
        "Débito anterior": antes.total if antes else None, "Débito depois": depois.total if depois else None,
        "Variação do débito": depois.total - antes.total if antes and depois else None,
        "Recibo anterior": antes.apuracao.recibo if antes else "",
        "Recibo na data ou posterior": depois.apuracao.recibo if depois else "",
    }


def relatorio_geral(apuracoes, catalogo, cadastro=(), referencias=None, controle=None, avisos_xml=()):
    referencias = referencias or {}
    controle = controle or {}
    if len({apuracao.empresa for apuracao in apuracoes}) > 1:
        raise ValueError("Selecione uma empresa por relatório.")
    grupos = defaultdict(list)
    for apuracao in apuracoes:
        grupos[apuracao.competencia].append(validar_fechamento(apuracao, catalogo))
    abas = {nome: [] for nome in (
        "Resumo", "Movimentos", "Entidades", "Lotações", "Fechamentos",
        "Bases por entidade", "Bases por lotação",
    )}
    dctfweb, quadro_simulacoes, simulacoes, lotacoes_simuladas, rec_estab, controle_xml = [], [], [], [], [], []
    pendencias = [pendencia_verificacao("", "Leitura do XML", aviso) for aviso in avisos_xml]
    for competencia in sorted(grupos.keys() | referencias.keys() | controle.keys(), key=lambda c: c if "-" in c else f"{c}-13"):
        fechamentos = sorted(grupos[competencia], key=lambda f: (f.data is None, f.data or datetime.min))
        datados = [f for f in fechamentos if f.data is not None]
        contagem_datas = Counter(f.data for f in datados)
        unicos = [f for f in datados if contagem_datas[f.data] == 1]
        sequencia_parcial = len(unicos) != len(fechamentos)
        primeiro = datados[0] if datados and contagem_datas[datados[0].data] == 1 else None
        recente = datados[-1] if datados and contagem_datas[datados[-1].data] == 1 else None
        if len(fechamentos) == 1:
            primeiro = recente = fechamentos[0]
        if any(quantidade > 1 for quantidade in contagem_datas.values()):
            pendencias.append(pendencia_verificacao(
                competencia, "Ordem dos fechamentos", "Mais de um S-1299 tem a mesma data e hora de recebimento.",
            ))
        mudanca_debito = None
        n_movimentos = 0
        for a, b in zip(datados, datados[1:]):
            if contagem_datas[a.data] > 1 or contagem_datas[b.data] > 1:
                continue
            entidades = detalhe_entidade(a, b, catalogo)
            lotacoes = comparar_lotacoes_xml(a.apuracao, b.apuracao,
                                           a.calculo if a.conciliado else None, b.calculo if b.conciliado else None)
            estabs = detalhe_estabelecimento(a, b, catalogo)
            if not entidades and not lotacoes and not estabs:
                continue
            n_movimentos += 1
            tem_debito = any(linha["Variação do débito"] for linha in entidades)
            delta_debito = b.total - a.total
            if tem_debito:
                mudanca_debito = b.data, delta_debito
            delta_base = variacao(a.base, b.base)
            residuo_debito = delta_debito - sum((linha["Variação do débito"] for linha in entidades), ZERO)
            residuo_base = (
                delta_base - sum((linha["Variação da base de terceiros"] for linha in lotacoes), ZERO)
                if delta_base is not None else None
            )
            identificacao = {"Competência": competencia, "Movimento": f"{competencia}/{n_movimentos:02d}"}
            if residuo_debito or residuo_base:
                pendencias.append(pendencia_verificacao(
                    competencia, "Conciliação do movimento",
                    f"{identificacao['Movimento']}: diferença de débito {residuo_debito}, diferença de base {residuo_base}.", b,
                ))
            abas["Movimentos"].append({
                **identificacao, "Recebido antes em": a.data, "Recebido depois em": b.data,
                "Base antes": a.base, "Base depois": b.base, "Variação da base": delta_base,
                "Débito antes": a.total, "Débito depois": b.total, "Variação do débito": delta_debito,
                "Códigos com débito alterado": sum(bool(linha["Variação do débito"]) for linha in entidades),
                "Lotações alteradas": len(lotacoes),
                "Bases conciliadas": "Sim" if delta_base is not None and not residuo_base else "Em revisão",
                "Diferença não explicada no débito": residuo_debito, "Diferença não explicada na base": residuo_base,
                "Ordem dos XMLs": "Parcial" if sequencia_parcial else "Conferida",
                "Classificação antes": a.apuracao.classificacao, "Classificação depois": b.apuracao.classificacao,
                "Recibo antes": a.apuracao.recibo, "Recibo depois": b.apuracao.recibo,
                "XML antes": a.apuracao.arquivo, "XML depois": b.apuracao.arquivo,
                **({"Data no controle": controle.get(competencia, {}).get("Data no controle"),
                    "Situação no controle": controle.get(competencia, {}).get("Situação no controle", "")}
                   if controle else {}),
            })
            abas["Entidades"].extend({**identificacao, **linha} for linha in entidades)
            abas["Lotações"].extend({**identificacao, **linha} for linha in lotacoes)
            rec_estab.extend({**identificacao, **linha} for linha in estabs)

        if competencia in controle:
            controle_xml.append(comparar_controle(competencia, controle[competencia], unicos))

        estado, anterior_dctf, atual_dctf = referencias.get(competencia, ("Não informada", None, None))
        tem_intervalo = primeiro is not None and recente is not None and len(datados) >= 2 and primeiro.data < recente.data
        abas["Resumo"].append({
            "Competência": competencia, "S-5011": len(fechamentos), "Movimentos": n_movimentos,
            "Primeiro fechamento": primeiro.data if primeiro else None,
            "Último fechamento": recente.data if recente else None,
            "Base inicial": primeiro.base if primeiro else None,
            "Base recente": recente.base if recente else None,
            "Variação da base": variacao(primeiro.base, recente.base) if tem_intervalo else None,
            "Débito inicial": primeiro.total if primeiro else None,
            "Débito recente": recente.total if recente else None,
            "Variação acumulada": recente.total - primeiro.total if tem_intervalo else None,
            "Última mudança no débito": mudanca_debito[0] if mudanca_debito else None,
            "Variação do último movimento": mudanca_debito[1] if mudanca_debito else None,
            "DCTFWeb informada": estado,
            "Ordem dos XMLs": ("Parcial" if sequencia_parcial else "Conferida") if fechamentos else "Sem S-5011",
        })
        for f in fechamentos:
            abas["Fechamentos"].append(dados_fechamento(f))
            alertas = f.apuracao.alertas or (() if f.data else ("Data do fechamento indisponível.",))
            pendencias.extend(pendencia_verificacao(competencia, "Vínculo do fechamento", texto, f) for texto in alertas)
            if f.calculo.pendencias:
                pendencias.append(pendencia_verificacao(
                    competencia, "Cobertura da base", " / ".join(f.calculo.pendencias[:3]), f,
                ))
            if f.diferencas_por_codigo:
                codigos = ", ".join(sorted(f.diferencas_por_codigo))
                pendencias.append(pendencia_verificacao(
                    competencia, "Conciliação por entidade", f"O cálculo difere do S-5011 nos códigos {codigos}.", f,
                ))
            chave = {"Competência": competencia, "Recebido em": f.data, "Recibo S-1299": f.apuracao.recibo}
            for cr in sorted(f.debitos.keys() | f.calculo.bases.keys()):
                abas["Bases por entidade"].append({
                    **chave, "Receita": f"{cr[:4]}-{cr[4:]}", "Entidade": catalogo[cr],
                    "Base de terceiros": f.calculo.bases.get(cr, ZERO) if f.conciliado else None,
                    "Débito no S-5011": f.debitos.get(cr, ZERO),
                })
            declaradas = {tuple(linha[campo] for campo in CHAVE): linha["Base previdenciária"]
                          for linha in f.apuracao.lotacoes}
            for chave_lotacao, lotacao in f.calculo.lotacoes.items():
                abas["Bases por lotação"].append({
                    **chave, **lotacao, "Base declarada no XML": declaradas[chave_lotacao],
                    "Base de terceiros": lotacao["Base de terceiros"] if f.conciliado else None,
                })
        correspondentes = [f for f in fechamentos if f.total == atual_dctf]
        if competencia in referencias:
            dctfweb.append({
                "Competência": competencia, "Situação informada": estado,
                "Débito anterior da DCTFWeb": anterior_dctf, "Débito em análise na DCTFWeb": atual_dctf,
                "Variação na DCTFWeb": variacao(anterior_dctf, atual_dctf),
                "S-5011 com o valor em análise": len(correspondentes) if atual_dctf is not None else None,
                "Recibos candidatos": ", ".join(f.apuracao.recibo for f in correspondentes if f.apuracao.recibo),
            })
        if len(fechamentos) > 1 and (atual_dctf is None or correspondentes or anterior_dctf is None):
            continue
        candidatos = [f for f in unicos if f.conciliado and (anterior_dctf is None or f.total == anterior_dctf)]
        if correspondentes or len(candidatos) != 1:
            continue
        f = candidatos[0]
        propostas = propostas_cadastrais(f.apuracao, cadastro, f.calculo)
        substituicoes = {chave: config for chave, config, _ in propostas}
        if not propostas or len(substituicoes) != len(propostas):
            continue
        simulado = calcular(f.apuracao, substituicoes)
        if simulado.pendencias:
            continue
        sim = Fechamento(f.apuracao, simulado.debitos, simulado, True, f.suspensos)
        if sim.total == f.total:
            continue
        chave = {"Competência": competencia, "Referência": "Simulação S-1020", "Recibo anterior": f.apuracao.recibo}
        quadro_simulacoes.append({
            **chave, "Fechamento de referência": f.data, "Lotações simuladas": len(substituicoes),
            "Base no XML": f.base, "Base simulada": sim.base, "Variação da base": variacao(f.base, sim.base),
            "Débito no XML": f.total, "Débito simulado": sim.total, "Variação simulada": sim.total - f.total,
            "Débito em análise na DCTFWeb": atual_dctf,
            "Diferença para a DCTFWeb": variacao(atual_dctf, sim.total),
        })
        simulacoes.extend({**chave, **linha} for linha in detalhe_entidade(f, sim, catalogo, somente_mudancas=False))
        fontes = {(lot[1], lot[2]): evento["Arquivo"] for lot, _, evento in propostas}
        lotacoes_simuladas.extend(
            {**chave, **linha, "XML S-1020": fontes[(linha["Estabelecimento"], linha["Lotação"])]}
            for linha in mudancas_lotacao(f.calculo, simulado)
        )
    for nome, linhas in (
        ("DCTFWeb", dctfweb), ("Simulações", quadro_simulacoes),
        ("Entidades simuladas", simulacoes), ("Lotações simuladas", lotacoes_simuladas),
        ("Estabelecimentos", rec_estab), ("Controle", controle_xml),
        ("Verificação", pendencias),
    ):
        if linhas:
            abas[nome] = linhas
    return abas


def pendencia_verificacao(competencia, verificacao, detalhe, fechamento=None):
    return {
        "Competência": competencia, "Verificação": verificacao, "Detalhe": detalhe,
        "Recibo S-1299": fechamento.apuracao.recibo if fechamento else "",
        "XML S-5011": fechamento.apuracao.arquivo if fechamento else "",
    }


def conferir_bases_manad(mestres, itens):
    totais = []
    for registros, coluna in ((mestres, "Base registrada"), (itens, "Parcela da base")):
        agrupado = defaultdict(lambda: ZERO)
        for linha in registros:
            agrupado[tuple(linha[campo] for campo in CHAVE_MANAD)] += linha[coluna]
        totais.append(agrupado)
    k250, k300 = totais
    conferir = defaultdict(lambda: [0, 0, ZERO])
    for chave in k250.keys() | k300.keys():
        estab, _, competencia, _, _ = chave
        resumo = conferir[estab, competencia]
        saldo = k300.get(chave, ZERO) - k250.get(chave, ZERO)
        resumo[0] += 1
        resumo[1] += int(bool(saldo) or chave not in k250 or chave not in k300)
        resumo[2] += saldo
    return dict(conferir)


def adicionar_resumo_manad(abas, empresa, mestres, conferencia=None):
    bases = defaultdict(lambda: ZERO)
    fontes_chave = defaultdict(set)
    for registro in mestres:
        if not registro["Estabelecimento"].startswith(empresa):
            continue
        competencia = registro["Competência"]
        bases[competencia] += registro["Base registrada"]
        chave = (competencia, registro["Estabelecimento"], registro["Tipo de folha"],
                 registro["Lotação MANAD"], registro["Trabalhador"])
        fontes_chave[chave].add(registro["Arquivo"])
    sobrepostas = {chave[0] for chave, fontes in fontes_chave.items() if len(fontes) > 1}
    totais_conferencia = defaultdict(lambda: [0, 0, ZERO])
    for (estab, competencia), (qtde, divergentes, saldo) in (conferencia or {}).items():
        if estab.startswith(empresa):
            resumo = totais_conferencia[competencia]
            resumo[0] += qtde
            resumo[1] += divergentes
            resumo[2] += saldo
    xmls = {linha["Competência"]: linha for linha in abas["Resumo"]}
    abas["MANAD"] = []
    for competencia in sorted(bases.keys() | totais_conferencia.keys(), key=lambda c: c if "-" in c else f"{c}-13"):
        xml = xmls.get(competencia, {})
        tem_xml = bool(xml.get("S-5011"))
        qtde, divergentes, saldo = totais_conferencia.get(competencia, (None, None, None))
        problema = (
            "Arquivos MANAD sobrepostos" if competencia in sobrepostas else
            "Divergências entre K250 e K300" if divergentes else
            "K250 e K300 conferidos" if qtde else "K300 não conferido"
        )
        abas["MANAD"].append({
            "Competência": competencia,
            "Base previdenciária MANAD": None if competencia in sobrepostas else bases.get(competencia),
            "Chaves K250 × K300": qtde, "Chaves divergentes": divergentes, "Diferença K300 − K250": saldo,
            "Conferência MANAD": problema,
            "S-5011": xml.get("S-5011", 0),
            "Último fechamento XML": xml.get("Último fechamento"),
            "Base de terceiros XML": xml.get("Base recente"),
            "Débito de terceiros XML": xml.get("Débito recente"),
            "Cobertura XML": "S-5011 disponível" if tem_xml else "Sem S-5011 no ZIP",
        })


def gerar_excel(abas, empresa):
    workbook = Workbook()
    workbook.remove(workbook.active)
    notas = {
        "Resumo": "Primeiro e último S-5011 datados disponíveis. Valores de débito apurado de terceiros antes de créditos e pagamentos.",
        "Movimentos": "Compara fechamentos consecutivos com data de recebimento e destaca mudanças no débito, na base ou no enquadramento.",
        "Entidades": "Diferença por código de receita. A mesma remuneração pode compor a base de várias entidades.",
        "Lotações": "Base declarada e enquadramento observados no S-5011. A base por entidade aparece quando o cálculo concilia.",
        "Fechamentos": "Recibos e caminhos dos XMLs usados. Base em branco quando o cálculo não conciliou.",
        "Bases por entidade": "Apuração de cada fechamento por código de receita.",
        "Bases por lotação": "Base da folha nos perfis calculados e base de terceiros por lotação e fechamento.",
        "DCTFWeb": "Referências registradas pelo usuário. Coincidência de total no ZIP não confirma a apuração por código.",
        "Simulações": "Hipóteses calculadas com S-1020 posteriores. O S-5011 atualizado confirma a apuração efetiva.",
        "Entidades simuladas": "Débitos e bases por código nas hipóteses. Valores simulados dependem de confirmação com o S-5011.",
        "Lotações simuladas": "Bases da folha anterior com o enquadramento posterior testado a partir do S-1020.",
        "MANAD": "Conferência das rubricas K300 com a base previdenciária K250. Valores de terceiros vêm do último S-5011 disponível.",
        "Estabelecimentos": "Alterações nos débitos ou suspensões de terceiros retornados por estabelecimento no S-5011.",
        "Controle": "Situação e data do controle como referência. Os fechamentos candidatos e os valores vêm dos XMLs.",
        "Verificação": "Pendências de leitura, vínculo, cobertura ou conciliação. Confira a evidência indicada.",
    }
    for nome, linhas in abas.items():
        aba = workbook.create_sheet(nome)
        colunas = list(linhas[0]) if linhas else ["Situação"]
        ultima = get_column_letter(len(colunas))
        for linha in (1, 2):
            if len(colunas) > 1:
                aba.merge_cells(f"A{linha}:{ultima}{linha}")
        aba["A1"] = f"{nome} | Auditoria de Terceiros | {empresa}"
        aba["A1"].fill = PatternFill("solid", fgColor="173E4D")
        aba["A1"].font = Font(color="FFFFFF", bold=True, size=15)
        aba["A1"].alignment = Alignment(vertical="center", indent=1)
        aba["A2"] = notas[nome]
        aba["A2"].font = Font(color="425563", size=11)
        aba["A2"].alignment = Alignment(wrap_text=True, vertical="center", indent=1)
        aba.row_dimensions[1].height = 26
        aba.row_dimensions[2].height = 32
        for i, coluna in enumerate(colunas, 1):
            celula = aba.cell(4, i, coluna)
            celula.fill = PatternFill("solid", fgColor="216878")
            celula.font = Font(color="FFFFFF", bold=True)
            celula.alignment = Alignment(wrap_text=True, vertical="center")
            textos = [len(str(linha.get(coluna) or "")) for linha in linhas[:200]]
            largura = min(54, max(15, len(coluna) + 4, max(textos, default=0) + 3))
            aba.column_dimensions[get_column_letter(i)].width = largura
        aba.row_dimensions[4].height = 30
        for i, linha in enumerate(linhas or [{"Situação": "Sem ocorrências no conjunto importado."}], 5):
            for j, coluna in enumerate(colunas, 1):
                valor = linha.get(coluna)
                celula = aba.cell(i, j, valor)
                if isinstance(valor, str):
                    celula.data_type = "s"
                elif isinstance(valor, date):
                    celula.number_format = "dd/mm/yyyy hh:mm" if isinstance(valor, datetime) else "dd/mm/yyyy"
                elif isinstance(valor, Decimal):
                    celula.number_format = '"R$" #,##0.00;[Red]-"R$" #,##0.00;"R$" 0.00'
                if i % 2 == 0:
                    celula.fill = PatternFill("solid", fgColor="ECF4F6")
        aba.sheet_view.showGridLines = False
        aba.freeze_panes = "B5" if len(colunas) > 1 else "A5"
        aba.auto_filter.ref = f"A4:{ultima}{max(5, len(linhas) + 4)}"
    arquivo = BytesIO()
    workbook.save(arquivo)
    return arquivo.getvalue()
