from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from calculo_terceiros import calcular, mudancas_lotacao, propostas_cadastrais
from leitura import ZERO


@dataclass
class Fechamento:
    apuracao: object
    debitos: dict
    calculo: object
    conciliado: bool

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


def validar_fechamento(apuracao, catalogo):
    calculo = calcular(apuracao)
    debitos = defaultdict(lambda: ZERO)
    for cr in apuracao.contribuicoes:
        codigo = cr["Código de receita"]
        if not cr["Estabelecimento"] and codigo in catalogo:
            debitos[codigo] += cr["Apurado"]
    conciliado = not calculo.pendencias and all(
        debitos.get(cr, ZERO) == calculo.debitos.get(cr, ZERO)
        for cr in debitos.keys() | calculo.debitos.keys()
    )
    return Fechamento(apuracao, dict(debitos), calculo, conciliado)


def variacao(antes, depois):
    return depois - antes if antes is not None and depois is not None else None


def detalhe_entidade(a, b, catalogo, somente_mudancas=True):
    linhas = []
    for codigo in sorted(a.debitos.keys() | b.debitos.keys() | a.calculo.bases.keys() | b.calculo.bases.keys()):
        antes, depois = a.debitos.get(codigo, ZERO), b.debitos.get(codigo, ZERO)
        ba = a.calculo.bases.get(codigo, ZERO) if a.conciliado else None
        bd = b.calculo.bases.get(codigo, ZERO) if b.conciliado else None
        if not somente_mudancas or antes != depois or (ba is not None and bd is not None and ba != bd):
            linhas.append({
                "Receita": f"{codigo[:4]}-{codigo[4:]}", "Entidade": catalogo[codigo],
                "Base antes": ba, "Base depois": bd, "Variação da base": variacao(ba, bd),
                "Débito antes": antes, "Débito depois": depois, "Variação do débito": depois - antes,
            })
    return linhas


def dados_fechamento(f):
    a = f.apuracao
    return {
        "Competência": a.competencia, "Recebido em": f.data, "Classificação tributária": a.classificacao,
        "Base de terceiros": f.base, "Débito de terceiros": f.total,
        "Conferência da base": "Conciliada" if f.conciliado else "Em revisão",
        "Recibo S-1299": a.recibo, "XML S-5011": a.arquivo, "XML S-1299": a.fechamento,
    }


def relatorio_geral(apuracoes, catalogo, cadastro=(), referencias=None):
    referencias = referencias or {}
    grupos = defaultdict(list)
    for apuracao in apuracoes:
        grupos[apuracao.competencia].append(validar_fechamento(apuracao, catalogo))
    abas = {nome: [] for nome in (
        "Resumo", "Movimentos", "Entidades", "Lotações", "Fechamentos",
        "Bases por entidade", "Bases por lotação",
    )}
    dctfweb, quadro_simulacoes, simulacoes, lotacoes_simuladas = [], [], [], []
    for competencia in sorted(grupos.keys() | referencias.keys(), key=lambda c: c if "-" in c else f"{c}-13"):
        fechamentos = sorted(grupos[competencia], key=lambda f: (f.data is None, f.data or datetime.min))
        datados = [f for f in fechamentos if f.data is not None]
        primeiro = datados[0] if datados else None
        recente = datados[-1] if datados else None
        if len(fechamentos) == 1:
            primeiro = recente = fechamentos[0]
        mudanca_debito = None
        n_movimentos = 0
        for a, b in zip(datados, datados[1:]):
            if a.data == b.data:
                continue
            entidades = detalhe_entidade(a, b, catalogo)
            lotacoes = mudancas_lotacao(a.calculo, b.calculo) if a.conciliado and b.conciliado else []
            if not entidades and not lotacoes:
                continue
            n_movimentos += 1
            tem_debito = any(linha["Variação do débito"] for linha in entidades)
            if tem_debito:
                mudanca_debito = b.data, b.total - a.total
            identificacao = {"Competência": competencia, "Movimento": f"{competencia}/{n_movimentos:02d}"}
            abas["Movimentos"].append({
                **identificacao, "Recebido antes em": a.data, "Recebido depois em": b.data,
                "Base antes": a.base, "Base depois": b.base, "Variação da base": variacao(a.base, b.base),
                "Débito antes": a.total, "Débito depois": b.total, "Variação do débito": b.total - a.total,
                "Classificação antes": a.apuracao.classificacao, "Classificação depois": b.apuracao.classificacao,
                "Recibo antes": a.apuracao.recibo, "Recibo depois": b.apuracao.recibo,
                "XML antes": a.apuracao.arquivo, "XML depois": b.apuracao.arquivo,
            })
            abas["Entidades"].extend({**identificacao, **linha} for linha in entidades)
            abas["Lotações"].extend({**identificacao, **linha} for linha in lotacoes)

        estado, anterior_dctf, atual_dctf = referencias.get(competencia, ("Não informada", None, None))
        tem_intervalo = primeiro is not None and len(datados) >= 2 and primeiro.data < recente.data
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
        })
        for f in fechamentos:
            abas["Fechamentos"].append(dados_fechamento(f))
            chave = {"Competência": competencia, "Recebido em": f.data, "Recibo S-1299": f.apuracao.recibo}
            for cr in sorted(f.debitos.keys() | f.calculo.bases.keys()):
                abas["Bases por entidade"].append({
                    **chave, "Receita": f"{cr[:4]}-{cr[4:]}", "Entidade": catalogo[cr],
                    "Base de terceiros": f.calculo.bases.get(cr, ZERO) if f.conciliado else None,
                    "Débito no S-5011": f.debitos.get(cr, ZERO),
                })
            for lotacao in f.calculo.lotacoes.values():
                abas["Bases por lotação"].append({
                    **chave, **lotacao, "Base de terceiros": lotacao["Base de terceiros"] if f.conciliado else None,
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
        candidatos = [f for f in datados if f.conciliado and (anterior_dctf is None or f.total == anterior_dctf)]
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
        sim = Fechamento(f.apuracao, simulado.debitos, simulado, True)
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
    ):
        if linhas:
            abas[nome] = linhas
    return abas


def adicionar_resumo_manad(abas, empresa, mestres):
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
    xmls = {linha["Competência"]: linha for linha in abas["Resumo"]}
    abas["MANAD"] = []
    for competencia in sorted(bases, key=lambda c: c if "-" in c else f"{c}-13"):
        xml = xmls.get(competencia, {})
        tem_xml = bool(xml.get("S-5011"))
        abas["MANAD"].append({
            "Competência": competencia,
            "Base previdenciária MANAD": None if competencia in sobrepostas else bases[competencia],
            "S-5011": xml.get("S-5011", 0),
            "Último fechamento XML": xml.get("Último fechamento"),
            "Base de terceiros XML": xml.get("Base recente"),
            "Débito de terceiros XML": xml.get("Débito recente"),
            "Conferência": ("Arquivos MANAD sobrepostos" if competencia in sobrepostas
                            else "XML e MANAD disponíveis" if tem_xml else "Sem S-5011 no ZIP"),
        })


def gerar_excel(abas, empresa):
    workbook = Workbook()
    workbook.remove(workbook.active)
    notas = {
        "Resumo": "Primeiro e último S-5011 datados disponíveis. Valores de débito apurado de terceiros antes de créditos e pagamentos.",
        "Movimentos": "Compara fechamentos consecutivos com data de recebimento e destaca mudanças no débito, na base ou no enquadramento.",
        "Entidades": "Diferença por código de receita. A mesma remuneração pode compor a base de várias entidades.",
        "Lotações": "Lotações que explicam a mudança da base ou do enquadramento, quando os dois cálculos conciliam com os XMLs.",
        "Fechamentos": "Recibos e caminhos dos XMLs usados. Base em branco quando o cálculo não conciliou.",
        "Bases por entidade": "Apuração de cada fechamento por código de receita.",
        "Bases por lotação": "Base da folha nos perfis calculados e base de terceiros por lotação e fechamento.",
        "DCTFWeb": "Referências registradas pelo usuário. Coincidência de total no ZIP não confirma a apuração por código.",
        "Simulações": "Hipóteses calculadas com S-1020 posteriores. O S-5011 atualizado confirma a apuração efetiva.",
        "Entidades simuladas": "Débitos e bases por código nas hipóteses. Valores simulados dependem de confirmação com o S-5011.",
        "Lotações simuladas": "Bases da folha anterior com o enquadramento posterior testado a partir do S-1020.",
        "MANAD": "Base previdenciária original do K250. Base e débito de terceiros do último S-5011 disponível, por competência.",
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
                elif isinstance(valor, datetime):
                    celula.number_format = "dd/mm/yyyy hh:mm"
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
