from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
import re


ZERO = Decimal("0")
BASES_CP = ("vrBcCp00", "vrBcCp15", "vrBcCp20", "vrBcCp25")
CAMPOS_BASES = BASES_CP + ("vrSuspBcCp00", "vrSuspBcCp15", "vrSuspBcCp20", "vrSuspBcCp25")
EVENTOS = {"evtTabLotacao": "S-1020", "evtFechaEvPer": "S-1299", "evtCS": "S-5011"}


@dataclass(frozen=True)
class Fonte:
    nome: str
    caminho: str | None = None
    conteudo: bytes | None = None

    def abrir(self):
        return Path(self.caminho).open("rb") if self.caminho else BytesIO(self.conteudo)


@dataclass(frozen=True)
class Apuracao:
    empresa: str
    competencia: str
    tipo: str
    recibo: str
    data_fechamento: str
    arquivo: str
    fechamento: str
    lotacoes: tuple
    bases: tuple
    contribuicoes: tuple
    classificacao: str = ""
    alertas: tuple[str, ...] = ()


def xmls_zip(arquivo, prefixo):
    with ZipFile(arquivo) as pacote:
        for membro in pacote.infolist():
            if membro.is_dir():
                continue
            nome = membro.filename
            origem = f"{prefixo} / {nome}"
            if nome.lower().endswith(".zip"):
                yield from xmls_zip(BytesIO(pacote.read(membro)), origem)
            elif nome.lower().endswith(".xml"):
                match = re.search(r"\.(S-\d{4})\.xml$", nome, re.I)
                evento = match[1].upper() if match else ""
                if not evento or evento in EVENTOS.values():
                    yield origem, evento, pacote.read(membro)
                else:
                    yield origem, evento, None


def numero(valor):
    numero_decimal = Decimal(valor.replace(",", ".")) if valor else ZERO
    if not numero_decimal.is_finite():
        raise ValueError("Valor numérico inválido no arquivo.")
    return numero_decimal


def ler_documento(xml):
    raiz = ET.fromstring(xml)
    for no in raiz.iter():
        if isinstance(no.tag, str):
            no.tag = no.tag.rsplit("}", 1)[-1]
    return raiz


def totalizador(evento):
    info = evento.find("infoCS")
    if info is None:
        raise ValueError("S-5011 sem grupo infoCS.")
    lotacoes, bases, contribuicoes = [], [], []
    for estab in info.findall("ideEstab"):
        for lotacao in estab.findall("ideLotacao"):
            chave = {
                "Tipo de inscrição": estab.findtext("tpInsc", ""),
                "Estabelecimento": estab.findtext("nrInsc", ""),
                "Lotação": lotacao.findtext("codLotacao", ""),
            }
            base = ZERO
            for grupo in lotacao.findall("basesRemun"):
                valores = {campo: numero(grupo.findtext(f"basesCp/{campo}")) for campo in CAMPOS_BASES}
                base += sum((valores[campo] for campo in BASES_CP), ZERO)
                bases.append({
                    **chave, "Tipo de incidência": grupo.findtext("indIncid", ""),
                    "Categoria": grupo.findtext("codCateg", ""), **valores,
                })
            avulsos = lotacao.find("basesAvNPort")
            if avulsos is not None:
                valores = {campo: numero(avulsos.findtext(campo)) for campo in CAMPOS_BASES}
                base += sum((valores[campo] for campo in BASES_CP), ZERO)
                bases.append({**chave, "Tipo de incidência": "S-1270", "Categoria": "", **valores})
            lotacoes.append({
                **chave,
                "FPAS": lotacao.findtext("fpas", ""),
                "Código de terceiros": lotacao.findtext("codTercs", ""),
                "Código suspenso": lotacao.findtext("codTercsSusp", ""),
                "Base previdenciária": base,
            })
        contribuicoes.extend(ler_receitas(estab.findall("infoCREstab"), estab.findtext("nrInsc", "")))
    contribuicoes.extend(ler_receitas(info.findall("infoCRContrib"), ""))
    return tuple(lotacoes), tuple(bases), tuple(contribuicoes)


def ler_receitas(grupos, estabelecimento):
    return [
        {
            "Estabelecimento": estabelecimento,
            "Código de receita": grupo.findtext("tpCR", ""),
            "Apurado": numero(grupo.findtext("vrCR")),
            "Suspenso": numero(grupo.findtext("vrCRSusp") or grupo.findtext("vrSuspCR")),
        }
        for grupo in grupos
    ]


def ler_xmls(fontes):
    fechamentos, totalizadores, avisos = {}, {}, []
    conflitos_fechamento, conflitos_totalizador = set(), set()
    cadastro = {}
    inventario = Counter()
    for fonte in fontes:
        with fonte.abrir() as arquivo:
            entradas = xmls_zip(arquivo, fonte.nome) if fonte.nome.lower().endswith(".zip") else [
                (fonte.nome, "", arquivo.read())
            ]
            for origem, tipo, dados in entradas:
                if dados is None:
                    inventario[tipo] += 1
                    continue
                try:
                    raiz = ler_documento(dados)
                except ET.ParseError as erro:
                    avisos.append(f"{origem}: XML inválido ({erro}).")
                    continue
                if not tipo:
                    evento_geral = next((no for no in raiz.iter() if no.tag.startswith("evt")), None)
                    tipo = EVENTOS.get(evento_geral.tag, evento_geral.tag) if evento_geral is not None else "Não identificado"
                inventario[tipo] += 1
                recibo = (raiz.findtext(".//nrRecibo") or raiz.findtext(".//numeroRecibo") or "").strip()
                data = (raiz.findtext(".//dhRecepcao") or raiz.findtext(".//dhProcessamento") or "").strip()
                for evento in raiz.iter("evtFechaEvPer"):
                    empresa = evento.findtext("ideEmpregador/nrInsc", "")
                    if recibo:
                        chave = empresa, recibo
                        competencia = evento.findtext("ideEvento/perApur", "")
                        tipo_apuracao = evento.findtext("ideEvento/indApuracao", "")
                        anterior = fechamentos.get(chave)
                        if anterior and (anterior[2:] != (competencia, tipo_apuracao)
                                         or (anterior[0] and data and anterior[0] != data)):
                            conflitos_fechamento.add(chave)
                        elif not anterior or not anterior[0]:
                            fechamentos[chave] = (data, origem, competencia, tipo_apuracao)
                for evento in raiz.iter("evtTabLotacao"):
                    empresa = evento.findtext("ideEmpregador/nrInsc", "")
                    for operacao in evento.findall("infoLotacao/*"):
                        chave = (empresa, evento.get("Id") or origem, operacao.tag)
                        cadastro[chave] = {
                            "Empresa": empresa, "Recebido em": data, "Operação": operacao.tag,
                            "Lotação": operacao.findtext("ideLotacao/codLotacao", ""),
                            "Início da vigência": operacao.findtext("ideLotacao/iniValid", ""),
                            "Fim da vigência": operacao.findtext("ideLotacao/fimValid", ""),
                            "Novo início": operacao.findtext("novaValidade/iniValid", ""),
                            "Novo fim": operacao.findtext("novaValidade/fimValid", ""),
                            "FPAS": operacao.findtext("dadosLotacao/fpasLotacao/fpas", ""),
                            "Código de terceiros": operacao.findtext("dadosLotacao/fpasLotacao/codTercs", ""),
                            "Arquivo": origem,
                        }
                for evento in raiz.iter("evtCS"):
                    empresa = evento.findtext("ideEmpregador/nrInsc", "")
                    vinculo = evento.findtext("infoCS/nrRecArqBase", "").strip()
                    id_evento = evento.get("Id") or origem
                    try:
                        lotacoes, bases, contribuicoes = totalizador(evento)
                    except (ValueError, ArithmeticError) as erro:
                        avisos.append(f"{origem}: {erro}")
                        continue
                    chave = empresa, id_evento
                    novo = (
                        empresa, evento.findtext("ideEvento/perApur", ""), evento.findtext("ideEvento/indApuracao", ""),
                        vinculo, origem, lotacoes, bases, contribuicoes,
                        evento.findtext("infoCS/infoContrib/classTrib", ""),
                    )
                    anterior = totalizadores.get(chave)
                    if anterior and anterior[:4] + anterior[5:] != novo[:4] + novo[5:]:
                        conflitos_totalizador.add(chave)
                    elif not anterior:
                        totalizadores[chave] = novo
    apuracoes = []
    por_recibo = Counter((dados[0], dados[3]) for dados in totalizadores.values() if dados[3])
    for chave, dados in totalizadores.items():
        empresa, competencia, tipo, recibo, origem, lotacoes, bases, contribuicoes, classificacao = dados
        if chave in conflitos_totalizador:
            avisos.append(f"{origem}: o ID do S-5011 aparece com conteúdos diferentes. Totalizador excluído.")
            continue
        if not empresa or not (tipo == "1" and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", competencia)
                               or tipo == "2" and re.fullmatch(r"\d{4}", competencia)):
            avisos.append(f"{origem}: empresa, competência ou tipo de apuração inválido no S-5011.")
            continue
        data, fechamento, alertas = vincular_fechamento(
            empresa, competencia, tipo, recibo, fechamentos, conflitos_fechamento, por_recibo,
        )
        apuracoes.append(Apuracao(
            empresa, competencia, tipo, recibo, data, origem, fechamento, lotacoes, bases, contribuicoes, classificacao,
            alertas,
        ))
    apuracoes.sort(key=lambda a: (a.empresa, a.competencia, a.data_fechamento, a.recibo))
    return apuracoes, inventario, avisos, tuple(cadastro.values())


def vincular_fechamento(empresa, competencia, tipo, recibo, fechamentos, conflitos, por_recibo):
    chave = empresa, recibo
    if not recibo:
        return "", "", ("S-5011 sem recibo de fechamento.",)
    if chave in conflitos or por_recibo[chave] > 1:
        return "", "", ("Há XMLs conflitantes para este recibo.",)
    if chave not in fechamentos:
        return "", "", ("S-1299 correspondente ausente.",)
    data, origem, periodo_fechamento, tipo_fechamento = fechamentos[chave]
    if (periodo_fechamento, tipo_fechamento) != (competencia, tipo):
        return "", "", ("Competência ou tipo de apuração diverge entre S-1299 e S-5011.",)
    try:
        if "T" not in data:
            raise ValueError
        datetime.fromisoformat(data)
    except ValueError:
        return "", origem, ("O S-1299 não tem data e hora de recebimento válidas.",)
    return data, origem, ()


def competencia_manad(valor):
    return valor[2:] if valor[:2] == "13" else f"{valor[2:]}-{valor[:2]}"


def ler_manad(fontes):
    registros = defaultdict(list)
    tamanho = {"K100": 6, "K150": 5, "K250": 14, "K300": 11}
    for fonte in fontes:
        with fonte.abrir() as arquivo:
            dados = arquivo.read()
        try:
            conteudo = dados.decode("utf-8-sig")
        except UnicodeDecodeError:
            conteudo = dados.decode("cp1252")
        for linha, texto in enumerate(conteudo.splitlines(), 1):
            campos = [campo.strip() for campo in texto.split("|")]
            if campos[0] == "" and len(campos) > 1:
                campos = campos[1:]
            codigo = campos[0]
            if codigo not in tamanho:
                continue
            if len(campos) < tamanho[codigo]:
                raise ValueError(f"{fonte.nome}, linha {linha}: registro {codigo} incompleto.")
            registros[codigo].append((fonte.nome, linha, campos))
    rubricas = {(arquivo, f[1], f[3]): f[4] for arquivo, _, f in registros["K150"]}
    lotacoes = {(arquivo, f[3], f[2]): f[4] for arquivo, _, f in registros["K100"]}
    mestres, itens = [], []
    for arquivo, linha, f in registros["K250"]:
        mestres.append({
            **chave_manad(f, arquivo, lotacoes), "Base registrada": numero(f[13]),
            "Arquivo": arquivo, "Linha": linha,
        })
    for arquivo, linha, f in registros["K300"]:
        valor = numero(f[7])
        incidencia, tipo = f[10], f[8]
        parcela = ZERO
        if incidencia in {"1", "2", "7"}:
            parcela = -valor if incidencia == "7" or tipo == "D" else valor
        itens.append({
            **chave_manad(f, arquivo, lotacoes), "Rubrica": f[6],
            "Descrição da rubrica": rubricas.get((arquivo, f[1], f[6]), ""),
            "Indicador previdenciário": incidencia, "Tipo de rubrica": tipo, "Valor da rubrica": valor,
            "Parcela da base": parcela, "Arquivo": arquivo, "Linha": linha,
        })
    return mestres, itens


def chave_manad(f, arquivo, lotacoes):
    return {
        "Estabelecimento": f[1], "Tipo de folha": f[2], "Lotação MANAD": f[3],
        "Descrição da lotação": lotacoes.get((arquivo, f[1], f[3]), ""),
        "Trabalhador": f[4], "Competência": competencia_manad(f[5]),
    }
