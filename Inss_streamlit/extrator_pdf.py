import re
import pdfplumber

# ---------- util ----------
def normalizar_valor(txt: str):
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except Exception:
        return None

def _money_regex_findall(s: str):
    # aceita 1.234,56 ou 1234,56
    return re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}", s)

def pagina_eh_de_bases(page) -> bool:
    t = (page.extract_text() or "").lower()
    gat = [
        "bases de calculo", "bases de cálculo",
        "resumo geral", "identificacao geral", "identificação geral",
        "salario contribuicao", "salário contribuição",
        "terceiros", "fap", "acidente de trabalho", "rat"
    ]
    return any(g in t for g in gat)

# ---------- BASE OFICIAL (por grupo) ----------
def extrair_base_empresa_page(page):
    """
    Procura especificamente 'Salário Contribuição Empresa' e extrai valores por grupo.
    Retorna dict:
      {"ativos": x, "desligados": y, "afastados": z, "total": t}
    ou None.
    """
    texto = (page.extract_text() or "")
    linhas = [l.strip() for l in texto.split("\n") if l.strip()]

    alvo_variantes = [
        "salario contribuicao empresa",
        "salário contribuição empresa"
    ]

    for i, linha in enumerate(linhas):
        l = linha.lower()
        if any(a in l for a in alvo_variantes):
            # tenta na mesma linha
            vals = _money_regex_findall(linha)
            if len(vals) >= 4:
                nums = [normalizar_valor(v) for v in vals[-4:]]
                if all(v is not None for v in nums):
                    return {"ativos": nums[0], "desligados": nums[1], "afastados": nums[2], "total": nums[3]}

            # tenta na próxima linha (muito comum)
            if i + 1 < len(linhas):
                vals2 = _money_regex_findall(linhas[i + 1])
                if len(vals2) >= 4:
                    nums = [normalizar_valor(v) for v in vals2[-4:]]
                    if all(v is not None for v in nums):
                        return {"ativos": nums[0], "desligados": nums[1], "afastados": nums[2], "total": nums[3]}

    return None

# ---------- EVENTOS (por grupo) ----------
def _achar_colunas_por_header(page):
    """
    Localiza aproximadamente as colunas ATIVOS / DESLIGADOS / TOTAL no quadro de eventos
    usando posições x do cabeçalho.
    Retorna dict com x (centro aproximado) ou None se não achar.
    """
    words = page.extract_words(use_text_flow=True)
    # guarda x0 de palavras importantes
    xs = {"ativos": [], "desligados": [], "total": []}

    for w in words:
        tx = w["text"].strip().lower()
        if tx in ["ativos", "ativo", "atv"]:
            xs["ativos"].append(w["x0"])
        if tx in ["desligados", "desligado", "desl"]:
            xs["desligados"].append(w["x0"])
        if tx in ["total"]:
            xs["total"].append(w["x0"])

    # pega mediana simples (primeiro) se existir
    if not xs["ativos"] or not xs["desligados"] or not xs["total"]:
        return None

    # escolhe os menores x (o cabeçalho costuma repetir no lado esquerdo e direito)
    # mas aqui usamos isso depois por "lado" (provento/desconto)
    return xs

def _pick_nearest(values_with_x, target_x, max_dist=45):
    """
    values_with_x: list[(x, value_float)]
    Retorna value mais próximo do target_x dentro de max_dist.
    """
    best = None
    bestd = None
    for x, v in values_with_x:
        d = abs(x - target_x)
        if d <= max_dist and (bestd is None or d < bestd):
            best = v
            bestd = d
    return best

def extrair_eventos_page(page):
    """
    Extrai eventos (rubricas) por grupo:
      rubrica, tipo, ativos, desligados, total
    IMPORTANTE: se página for de bases, retorna [].
    """
    if pagina_eh_de_bases(page):
        return []

    largura = page.width
    eixo = largura * 0.50  # esquerda provento, direita desconto (padrão do seu modelo)

    # tentar achar header pra pegar posições x (tanto do lado esquerdo quanto direito)
    header_xs = _achar_colunas_por_header(page)
    if header_xs is None:
        # sem header detectado: devolve vazio (evita bagunçar com extração errada)
        return []

    words = page.extract_words(use_text_flow=True)

    # agrupar por linha visual (y)
    linhas = {}
    for w in words:
        y = round(w["top"], 1)
        linhas.setdefault(y, []).append(w)

    registros = []

    for itens in linhas.values():
        itens = sorted(itens, key=lambda x: x["x0"])
        texto_linha = " ".join(i["text"] for i in itens).strip()
        low = texto_linha.lower()

        # filtros anti-cabeçalho
        if any(p in low for p in ["cod", "provento", "desconto", "refer", "ativos", "desligados", "afastados", "total"]):
            continue

        # separa lados
        esquerda = [i for i in itens if i["x0"] < eixo]
        direita = [i for i in itens if i["x0"] >= eixo]

        def processar_lado(bloco, tipo, lado):
            if not bloco:
                return None

            # descrição = parte não-numérica (tira valores monetários)
            texto_bloco = " ".join(i["text"] for i in bloco).strip()
            if not texto_bloco:
                return None

            # pega candidatos a valores monetários com posição x
            valores = []
            for i in bloco:
                tx = i["text"].strip()
                if re.match(r"^\d{1,3}(?:\.\d{3})*,\d{2}$|^\d+,\d{2}$", tx):
                    v = normalizar_valor(tx)
                    if v is not None:
                        valores.append((i["x0"], v))

            if not valores:
                return None

            # escolhe targets x do header para o lado atual (pega o mais próximo do lado)
            if lado == "esquerda":
                # pega os menores xs (lado esquerdo)
                x_ativos = min(header_xs["ativos"])
                x_desl = min(header_xs["desligados"])
                x_total = min(header_xs["total"])
            else:
                # pega os maiores xs (lado direito)
                x_ativos = max(header_xs["ativos"])
                x_desl = max(header_xs["desligados"])
                x_total = max(header_xs["total"])

            v_ativos = _pick_nearest(valores, x_ativos)
            v_desl = _pick_nearest(valores, x_desl)
            v_total = _pick_nearest(valores, x_total)

            # se não conseguiu mapear total, ignora (evita sujeira)
            if v_total is None and (v_ativos is None and v_desl is None):
                return None

            # remove valores e código do começo
            desc = re.sub(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}", "", texto_bloco)
            desc = re.sub(r"^\d+\s*", "", desc).strip()

            if len(desc) < 3:
                return None

            return {
                "rubrica": desc,
                "tipo": tipo,
                "ativos": v_ativos or 0.0,
                "desligados": v_desl or 0.0,
                "total": v_total if v_total is not None else (v_ativos or 0.0) + (v_desl or 0.0),
            }

        r_prov = processar_lado(esquerda, "PROVENTO", "esquerda")
        r_desc = processar_lado(direita, "DESCONTO", "direita")

        if r_prov:
            registros.append(r_prov)
        if r_desc:
            registros.append(r_desc)

    return registros
