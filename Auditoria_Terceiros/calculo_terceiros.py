from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from leitura import BASES_CP, ZERO


# Tabela 04 do eSocial, NT 01/2023. Combinações de folha validadas nesta auditoria.
ALIQUOTAS = {
    1: ("1170", Decimal("0.025")),
    2: ("1176", Decimal("0.002")),
    4: ("1181", Decimal("0.010")),
    8: ("1184", Decimal("0.015")),
    16: ("1191", Decimal("0.010")),
    32: ("1196", Decimal("0.015")),
    64: ("1200", Decimal("0.006")),
}
CONFIGURACOES = {("507", "0079"), ("507", "0066"), ("515", "0115")}
SIMPLES = {"01", "02", "03", "04"}
CHAVE = ("Tipo de inscrição", "Estabelecimento", "Lotação")


@dataclass
class Calculo:
    lotacoes: dict
    bases: dict
    debitos: dict
    pendencias: list


def calcular(apuracao, substituicoes=None):
    """Aplica o enquadramento às bases de remuneração informadas no S-5011."""
    substituicoes = substituicoes or {}
    bases_por_lotacao = defaultdict(lambda: ZERO)
    categorias_pendentes = defaultdict(set)
    for linha in apuracao.bases:
        chave = tuple(linha[campo] for campo in CHAVE)
        valor = sum((linha[campo] for campo in BASES_CP), ZERO)
        categoria = linha["Categoria"]
        if categoria in {"101", "103"} and linha["Tipo de incidência"] in {"1", "2", "9"}:
            bases_por_lotacao[chave] += valor
        elif categoria != "723" and valor:
            categorias_pendentes[chave].add(categoria or linha["Tipo de incidência"])

    lotacoes, bases = {}, defaultdict(lambda: ZERO)
    pendencias = []
    sufixo = "21" if apuracao.tipo == "2" else "01"
    for linha in apuracao.lotacoes:
        chave = tuple(linha[campo] for campo in CHAVE)
        fpas, codigo = substituicoes.get(chave, (linha["FPAS"], linha["Código de terceiros"]))
        base = bases_por_lotacao[chave]
        configuracao = (fpas, codigo)
        aplicada = ZERO
        motivo = ""
        if codigo == "0000" or apuracao.classificacao in SIMPLES:
            pass
        elif configuracao not in CONFIGURACOES or apuracao.classificacao != "99":
            motivo = f"enquadramento {apuracao.classificacao or 'ausente'}, FPAS {fpas}, código {codigo or 'ausente'}"
        elif categorias_pendentes[chave]:
            motivo = f"categorias ou bases fora do cálculo ({', '.join(sorted(categorias_pendentes[chave]))})"
        else:
            aplicada = base
            for bit, (receita, _) in ALIQUOTAS.items():
                if int(codigo) & bit:
                    bases[receita + sufixo] += aplicada
        if motivo:
            pendencias.append(f"{chave[2]} ({chave[1]}): {motivo}")
        lotacoes[chave] = {
            "Lotação": chave[2], "Estabelecimento": chave[1], "FPAS": fpas, "Código de terceiros": codigo,
            "Base elegível da folha": base, "Base de terceiros": None if motivo else aplicada,
        }
    # O truncamento do cálculo sobre a base consolidada por código reproduz o S-5011
    # dos perfis validados. A interface compara cada valor com o retorno oficial.
    taxas = {receita + sufixo: taxa for receita, taxa in ALIQUOTAS.values()}
    debitos = {cr: (base * taxas[cr]).quantize(Decimal("0.01"), rounding=ROUND_DOWN) for cr, base in bases.items()}
    return Calculo(lotacoes, dict(bases), debitos, pendencias)


def propostas_cadastrais(apuracao, cadastro, calculo):
    """Sugere mudanças 0000 → código ativo com registro posterior e vigência na competência."""
    if len(apuracao.competencia) != 7 or not apuracao.data_fechamento:
        return []
    propostas = {}
    for evento in cadastro:
        if evento["Empresa"] != apuracao.empresa or evento["Recebido em"] <= apuracao.data_fechamento:
            continue
        if evento["Operação"] not in {"inclusao", "alteracao"}:
            continue
        inicio = evento["Novo início"] or evento["Início da vigência"]
        fim = evento["Novo fim"] if evento["Novo início"] else evento["Fim da vigência"]
        if not inicio or inicio > apuracao.competencia or (fim and fim < apuracao.competencia):
            continue
        configuracao = (evento["FPAS"], evento["Código de terceiros"])
        if configuracao not in CONFIGURACOES:
            continue
        for chave, lotacao in calculo.lotacoes.items():
            if chave[2] != evento["Lotação"] or lotacao["Código de terceiros"] != "0000":
                continue
            if not lotacao["Base elegível da folha"]:
                continue
            anterior = propostas.get((chave, configuracao))
            if anterior is None or evento["Recebido em"] > anterior["Recebido em"]:
                propostas[(chave, configuracao)] = evento
    return [(chave, configuracao, evento) for (chave, configuracao), evento in sorted(propostas.items())]


def mudancas_lotacao(antes, depois):
    linhas = []
    for chave in sorted(antes.lotacoes.keys() | depois.lotacoes.keys()):
        a, d = antes.lotacoes.get(chave, {}), depois.lotacoes.get(chave, {})
        va, vd = a.get("Base de terceiros", ZERO), d.get("Base de terceiros", ZERO)
        ca, cd = a.get("Código de terceiros", "—"), d.get("Código de terceiros", "—")
        fa, fd = a.get("FPAS", "—"), d.get("FPAS", "—")
        if (va or vd) and (va != vd or ca != cd or fa != fd):
            linhas.append({
                "Lotação": chave[2], "Estabelecimento": chave[1], "FPAS antes → depois": f"{fa} → {fd}",
                "Código antes → depois": f"{ca} → {cd}", "Base antes": va, "Base depois": vd,
                "Variação da base": vd - va,
            })
    return sorted(linhas, key=lambda linha: (-linha["Variação da base"], linha["Lotação"]))


def bases_por_categoria(apuracao):
    grupos = defaultdict(list)
    for linha in apuracao.bases:
        chave = tuple(linha[campo] for campo in CHAVE)
        valores = tuple(valor for campo, valor in linha.items() if campo not in CHAVE)
        grupos[chave].append(valores)
    return {chave: sorted(valores) for chave, valores in grupos.items()}


def comparar_lotacoes_xml(antes, depois, calculo_antes=None, calculo_depois=None):
    """Compara evidência do S-5011 sem depender da cobertura do cálculo por entidade."""
    lot_antes, lot_depois = (
        {tuple(linha[campo] for campo in CHAVE): linha for linha in apuracao.lotacoes}
        for apuracao in (antes, depois)
    )
    categorias_antes, categorias_depois = bases_por_categoria(antes), bases_por_categoria(depois)
    linhas = []
    for chave in sorted(lot_antes.keys() | lot_depois.keys()):
        a, d = lot_antes.get(chave, {}), lot_depois.get(chave, {})
        ca, cd = a.get("Código de terceiros", ""), d.get("Código de terceiros", "")
        if ca in {"", "0000"} and cd in {"", "0000"}:
            continue
        fa, fd = a.get("FPAS", ""), d.get("FPAS", "")
        sa, sd = a.get("Código suspenso", ""), d.get("Código suspenso", "")
        va, vd = a.get("Base previdenciária", ZERO), d.get("Base previdenciária", ZERO)
        base_antes = calculo_antes.lotacoes[chave]["Base de terceiros"] if a and calculo_antes else (None if a else ZERO)
        base_depois = calculo_depois.lotacoes[chave]["Base de terceiros"] if d and calculo_depois else (None if d else ZERO)
        mudancas = [
            rotulo for alterou, rotulo in (
                (bool(a) != bool(d), "Presença da lotação"),
                (ca != cd, "Código de terceiros"),
                (fa != fd, "FPAS"),
                (sa != sd, "Código suspenso"),
                (va != vd, "Base no XML"),
                (va == vd and categorias_antes.get(chave) != categorias_depois.get(chave), "Composição da base no XML"),
                (antes.classificacao != depois.classificacao, "Classificação tributária"),
                (base_antes is not None and base_depois is not None and base_antes != base_depois, "Base de terceiros"),
            )
            if alterou
        ]
        if not mudancas:
            continue
        linhas.append({
            "Lotação": chave[2], "Estabelecimento": chave[1], "O que mudou": ", ".join(mudancas),
            "FPAS antes → depois": f"{fa or '—'} → {fd or '—'}",
            "Código antes → depois": f"{ca or '—'} → {cd or '—'}",
            "Código suspenso antes → depois": f"{sa or '—'} → {sd or '—'}" if sa or sd else "",
            "Base declarada antes": va, "Base declarada depois": vd, "Variação da base declarada": vd - va,
            "Base de terceiros antes": base_antes, "Base de terceiros depois": base_depois,
            "Variação da base de terceiros": (
                base_depois - base_antes if base_antes is not None and base_depois is not None else None
            ),
        })
    return linhas
