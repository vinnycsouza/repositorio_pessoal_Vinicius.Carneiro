from datetime import date, datetime
import re
from unicodedata import normalize

from openpyxl import load_workbook


MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()


def texto(valor):
    return normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode().strip().lower()


def competencia(valor):
    if isinstance(valor, date):
        return valor.strftime("%Y-%m")
    valor = texto(valor)
    if re.fullmatch(r"\d{4}", valor):
        return valor
    partes = re.fullmatch(r"(\d{4})[-/](\d{1,2})|(\d{1,2}|[a-z]{3})[-/](\d{2}|\d{4})", valor)
    if not partes:
        return None
    ano, mes, mes_br, ano_br = partes.groups()
    if ano_br:
        ano = ("20" + ano_br) if len(ano_br) == 2 else ano_br
        if mes_br.isdigit():
            mes = mes_br
        elif mes_br in MESES:
            mes = MESES.index(mes_br) + 1
        else:
            return None
    mes = int(mes)
    if mes == 13:
        return ano
    return f"{ano}-{mes:02d}" if 1 <= mes <= 12 else None


def data_controle(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if valor:
        for formato in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(valor).strip(), formato).date()
            except ValueError:
                continue
    return None


def ler_controle(fonte):
    """Importa referências de período, data e situação, sem ler os valores como apuração."""
    with fonte.abrir() as arquivo:
        workbook = load_workbook(arquivo, read_only=True, data_only=True)
        try:
            resumos = sorted(workbook.worksheets, key=lambda aba: not texto(aba.title).startswith("resumo"))
            for aba in resumos:
                for numero, dados in enumerate(aba.iter_rows(max_row=20, values_only=True), 1):
                    cabecalho = {texto(valor): indice for indice, valor in enumerate(dados)}
                    periodo = next((cabecalho[c] for c in ("competencia", "apuracao", "periodo de apuracao")
                                    if c in cabecalho), None)
                    data = next((cabecalho[c] for c in ("data da retificacao", "data do movimento")
                                 if c in cabecalho), None)
                    situacao = cabecalho.get("situacao")
                    if periodo is None or (data is None and situacao is None):
                        continue
                    referencias = {}
                    for linha, celulas in enumerate(aba.iter_rows(min_row=numero + 1, values_only=True), numero + 1):
                        chave = competencia(celulas[periodo])
                        if not chave:
                            continue
                        recebido = data_controle(celulas[data]) if data is not None else None
                        estado = str(celulas[situacao] or "").strip() if situacao is not None else ""
                        if recebido is None and texto(estado) not in {"retificado", "em andamento", "alterado"}:
                            continue
                        if chave in referencias:
                            raise ValueError(f"Competência {chave} repetida no resumo do controle.")
                        referencias[chave] = {
                            "Data no controle": recebido,
                            "Situação no controle": estado,
                            "Fonte do controle": f"{fonte.nome} / {aba.title}, linha {linha}",
                        }
                    return referencias
        finally:
            workbook.close()
    raise ValueError("O controle precisa de uma aba com competência e data da retificação ou situação.")
