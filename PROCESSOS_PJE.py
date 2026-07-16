from __future__ import annotations

import re
import time
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# ============================================================
# CONFIGURAÇÕES
# ============================================================

URL_BASE = "https://pje.tst.jus.br/consultaprocessual/detalhe-processo"

ARQUIVO_SAIDA = Path("status_processos_tst.xlsx")
PASTA_DIAGNOSTICO = Path("erros_consulta_tst")

TEMPO_ESPERA = 25
INTERVALO_ENTRE_PROCESSOS = 2

# False: mostra o Chrome durante os testes.
# True: executa sem mostrar a janela.
EXECUTAR_EM_SEGUNDO_PLANO = False


# ============================================================
# LISTA DE PROCESSOS
# ============================================================

processos = [
    "0000915-57.2024.5.22.0006",
    "0000805-83.2023.5.22.0106",
    "0001765-44.2024.5.07.0034",
    "0001091-48.2024.5.22.0002",
    "0000991-02.2023.5.07.0017",
    "0000031-78.2025.5.06.0122",
    "0000135-46.2024.5.07.0003",
    "0001379-10.2022.5.05.0561",
    "0000883-97.2024.5.20.0009",
    "0001290-36.2023.5.06.0201",
    "0000380-27.2022.5.06.0271",
    "0000244-98.2022.5.19.0002",
    "0000235-75.2024.5.22.0005",
    "0001004-06.2024.5.06.0013",
    "0000147-19.2025.5.19.0059",
    "0000085-03.2023.5.19.0009",
    "0000354-39.2024.5.22.0004",
    "0000049-68.2024.5.19.0059",
    "0000734-23.2024.5.06.0161",
    "0000541-96.2023.5.06.0143",
    "0001723-54.2023.5.05.0561",
    "0001323-71.2021.5.06.0144",
    "0000637-68.2022.5.06.0201",
    "0001646-94.2022.5.10.0802",
    "0000750-57.2025.5.19.0006",
    "0000935-08.2023.5.07.0004",
    "0000940-94.2024.5.07.0036",
    "0000274-46.2023.5.10.0812",
    "0001066-80.2024.5.07.0025",
    "0000235-61.2025.5.06.0401",
    "0000437-72.2024.5.06.0401",
    "0000809-76.2024.5.19.0007",
    "0000783-92.2024.5.13.0024",
    "0000826-68.2023.5.22.0006",
    "0000903-98.2022.5.19.0005",
    "0000498-36.2022.5.05.0463",
    "0000672-56.2017.5.19.0002",
    "0000684-80.2024.5.06.0101",
    "0001634-09.2016.5.05.0195",
    "0000236-37.2021.5.19.0009",
    "0000593-85.2024.5.20.0008",
    "0000441-56.2022.5.05.0030",
    "0000112-70.2015.5.05.0036",
    "0000470-88.2022.5.05.0133",
    "0000889-94.2024.5.06.0009",
    "0000850-62.2019.5.06.0142",
    "0000920-40.2022.5.05.0421",
    "0000459-27.2022.5.05.0661",
    "0000376-79.2024.5.06.0251",
    "0000063-66.2024.5.07.0033",
    "0000707-06.2022.5.06.0001",
    "0000630-15.2023.5.05.0122",
    "0000958-24.2022.5.06.0001",
    "0000359-69.2024.5.07.0007",
    "0000287-68.2024.5.22.0103",
    "0000750-31.2023.5.06.0413",
    "0000303-29.2021.5.06.0020",
    "0001473-31.2024.5.07.0011",
    "0000997-24.2023.5.19.0001",
    "0000354-39.2024.5.22.0004",
    "0001255-28.2024.5.06.0141",
    "0000658-14.2022.5.06.0017",
    "0000628-12.2023.5.05.0133",
    "0000277-96.2024.5.19.0009",
    "0000156-71.2023.5.06.0201",
    "0000921-31.2024.5.06.0161",
    "0000670-25.2022.5.05.0221",
    "0000012-24.2023.5.05.0493",
    "0000668-91.2023.5.05.0133",
    "0000915-74.2024.5.07.0006",
    "0000044-23.2024.5.06.0022",
    "0000388-32.2023.5.06.0412",
    "0000009-93.2022.5.05.0464",
    "0000300-73.2024.5.22.0004",
]


# ============================================================
# TERMOS DE ANÁLISE
# ============================================================

TERMOS_TRANSITO_CONFIRMADO = [
    "trânsito em julgado",
    "transito em julgado",
    "transitada em julgado",
    "transitado em julgado",
    "certificado o trânsito em julgado",
    "certificado o transito em julgado",
    "certidão de trânsito em julgado",
    "certidao de transito em julgado",
    "certificado trânsito em julgado",
    "certificado transito em julgado",
]

TERMOS_BAIXA = [
    "baixa definitiva",
    "baixado definitivamente",
    "arquivado definitivamente",
    "arquivamento definitivo",
    "remetidos os autos ao tribunal de origem",
    "remessa dos autos ao tribunal de origem",
]

TERMOS_NAO_ENCONTRADO = [
    "processo não encontrado",
    "processo nao encontrado",
    "nenhum processo encontrado",
    "nenhum resultado encontrado",
    "não foram encontrados processos",
    "nao foram encontrados processos",
]

TERMOS_CAPTCHA = [
    "captcha",
    "não sou um robô",
    "nao sou um robo",
    "verificação de segurança",
    "verificacao de seguranca",
    "digite os caracteres",
    "digite os números do áudio",
    "digite os numeros do audio",
]


# ============================================================
# FUNÇÕES GERAIS
# ============================================================

def criar_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()

    if EXECUTAR_EM_SEGUNDO_PLANO:
        options.add_argument("--headless=new")

    options.add_argument("--start-maximized")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    options.add_experimental_option(
        "excludeSwitches",
        ["enable-logging"],
    )

    # Selenium Manager administra o ChromeDriver automaticamente.
    return webdriver.Chrome(options=options)


def normalizar_texto(texto: str) -> str:
    texto = texto or ""
    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip().lower()


def somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def validar_numero_processo(numero: str) -> bool:
    padrao = r"^\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}$"
    return bool(re.fullmatch(padrao, numero.strip()))


def aguardar_pagina(driver: webdriver.Chrome) -> None:
    WebDriverWait(driver, TEMPO_ESPERA).until(
        lambda navegador: navegador.execute_script(
            "return document.readyState"
        ) == "complete"
    )


def obter_texto_pagina(driver: webdriver.Chrome) -> str:
    corpo = WebDriverWait(driver, TEMPO_ESPERA).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    return corpo.text


def contem_algum_termo(texto: str, termos: list[str]) -> bool:
    texto_normalizado = normalizar_texto(texto)

    return any(
        normalizar_texto(termo) in texto_normalizado
        for termo in termos
    )


def detectar_captcha(texto: str) -> bool:
    return contem_algum_termo(texto, TERMOS_CAPTCHA)


def detectar_nao_encontrado(texto: str) -> bool:
    return contem_algum_termo(texto, TERMOS_NAO_ENCONTRADO)


# ============================================================
# IDENTIFICAÇÃO DO RESULTADO DO TST
# ============================================================

def url_consulta(numero_processo: str) -> str:
    return f"{URL_BASE}/{numero_processo}"


def url_tst_direta(numero_processo: str) -> str:
    """
    O sufixo /3 identifica a terceira instância quando a página
    separa os resultados por grau.
    """
    return f"{URL_BASE}/{numero_processo}/3"


def pagina_eh_detalhe_tst(
    driver: webdriver.Chrome,
    texto: str,
) -> bool:
    url_atual = driver.current_url.rstrip("/").lower()
    texto_normalizado = normalizar_texto(texto)

    if url_atual.endswith("/3"):
        return True

    indicadores_tst = [
        "tribunal superior do trabalho",
        "tst",
        "órgão julgador",
        "orgao julgador",
        "ministro relator",
        "ministra relatora",
    ]

    quantidade = sum(
        indicador in texto_normalizado
        for indicador in indicadores_tst
    )

    return quantidade >= 2


def localizar_link_tst(
    driver: webdriver.Chrome,
    numero_processo: str,
):
    """
    Localiza somente o resultado de terceira instância.

    Prioridades:
    1. Link cujo endereço termine em /3.
    2. Elemento cujo texto contenha TST.
    3. Bloco de resultado com TST e o número do processo.
    """
    numero_digitos = somente_digitos(numero_processo)

    # Prioridade 1: endereço explicitamente terminado em /3.
    links = driver.find_elements(By.TAG_NAME, "a")

    for link in links:
        try:
            href = (link.get_attribute("href") or "").rstrip("/")

            if not href:
                continue

            if href.endswith("/3") and numero_digitos in somente_digitos(href):
                if link.is_displayed():
                    return link

        except StaleElementReferenceException:
            continue

    # Prioridade 2: link ou botão identificado como TST.
    candidatos = driver.find_elements(
        By.XPATH,
        (
            "//a[contains("
            "translate(normalize-space(.), "
            "'abcdefghijklmnopqrstuvwxyz', "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'TST')]"
            " | "
            "//button[contains("
            "translate(normalize-space(.), "
            "'abcdefghijklmnopqrstuvwxyz', "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'TST')]"
            " | "
            "//*[@role='button' and contains("
            "translate(normalize-space(.), "
            "'abcdefghijklmnopqrstuvwxyz', "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'TST')]"
        ),
    )

    for candidato in candidatos:
        try:
            texto = candidato.text.strip()
            href = candidato.get_attribute("href") or ""

            numero_no_elemento = (
                numero_digitos in somente_digitos(texto)
                or numero_digitos in somente_digitos(href)
            )

            if candidato.is_displayed() and (
                numero_no_elemento or "TST" in texto.upper()
            ):
                return candidato

        except StaleElementReferenceException:
            continue

    # Prioridade 3: procura um bloco que represente o resultado TST.
    blocos = driver.find_elements(
        By.XPATH,
        "//*[contains("
        "translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyz', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'TST')]",
    )

    for bloco in blocos:
        try:
            texto_bloco = bloco.text.strip()

            if not texto_bloco:
                continue

            if numero_digitos not in somente_digitos(texto_bloco):
                continue

            clicaveis = bloco.find_elements(
                By.XPATH,
                ".//a | .//button | .//*[@role='button']",
            )

            for clicavel in clicaveis:
                if clicavel.is_displayed():
                    return clicavel

        except (
            StaleElementReferenceException,
            NoSuchElementException,
        ):
            continue

    return None


def abrir_resultado_tst(
    driver: webdriver.Chrome,
    numero_processo: str,
) -> tuple[bool, str]:
    """
    Abre exclusivamente a terceira instância.

    Retorna:
        True, mensagem  -> TST aberto
        False, mensagem -> processo sem resultado no TST
    """
    texto_atual = obter_texto_pagina(driver)

    if pagina_eh_detalhe_tst(driver, texto_atual):
        return True, "Detalhes do TST acessados diretamente"

    link_tst = localizar_link_tst(driver, numero_processo)

    if link_tst is not None:
        url_anterior = driver.current_url

        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});",
            link_tst,
        )

        time.sleep(0.5)

        try:
            link_tst.click()
        except WebDriverException:
            driver.execute_script(
                "arguments[0].click();",
                link_tst,
            )

        try:
            WebDriverWait(driver, TEMPO_ESPERA).until(
                lambda navegador: (
                    navegador.current_url != url_anterior
                    or navegador.current_url.rstrip("/").endswith("/3")
                )
            )
        except TimeoutException:
            pass

        time.sleep(1)
        aguardar_pagina(driver)

        texto_detalhe = obter_texto_pagina(driver)

        if pagina_eh_detalhe_tst(driver, texto_detalhe):
            return True, "Resultado TST selecionado"

    # Última tentativa: acesso direto ao sufixo da terceira instância.
    driver.get(url_tst_direta(numero_processo))
    aguardar_pagina(driver)
    time.sleep(1)

    texto_direto = obter_texto_pagina(driver)

    if detectar_nao_encontrado(texto_direto):
        return False, "Não há processo localizado no TST"

    if pagina_eh_detalhe_tst(driver, texto_direto):
        return True, "Terceira instância acessada por URL direta"

    return False, "O número foi localizado, mas não há resultado TST"


# ============================================================
# ANÁLISE DO PROCESSO
# ============================================================

def analisar_transito(texto: str) -> tuple[str, str]:
    texto_normalizado = normalizar_texto(texto)

    for termo in TERMOS_TRANSITO_CONFIRMADO:
        if normalizar_texto(termo) in texto_normalizado:
            return "Sim", termo

    for termo in TERMOS_BAIXA:
        if normalizar_texto(termo) in texto_normalizado:
            return "Possível", termo

    return "Não localizado", ""


def extrair_trecho_relevante(
    texto: str,
    termos: list[str],
    margem: int = 300,
) -> str:
    texto_limpo = re.sub(r"\s+", " ", texto or "").strip()
    texto_normalizado = normalizar_texto(texto_limpo)

    for termo in termos:
        termo_normalizado = normalizar_texto(termo)
        posicao = texto_normalizado.find(termo_normalizado)

        if posicao == -1:
            continue

        inicio = max(0, posicao - margem)
        fim = min(
            len(texto_limpo),
            posicao + len(termo) + margem,
        )

        return texto_limpo[inicio:fim]

    return ""


def extrair_movimentacoes_com_data(texto: str) -> list[str]:
    """
    Localiza linhas que aparentam ser movimentações processuais
    acompanhadas de data.
    """
    linhas = [
        re.sub(r"\s+", " ", linha).strip()
        for linha in (texto or "").splitlines()
        if linha.strip()
    ]

    padrao_data = re.compile(
        r"\b\d{2}/\d{2}/\d{4}\b"
        r"|"
        r"\b\d{2}/\d{2}/\d{2}\b"
    )

    movimentacoes = []

    for linha in linhas:
        if padrao_data.search(linha):
            movimentacoes.append(linha)

    return movimentacoes


def extrair_ultima_movimentacao(texto: str) -> str:
    movimentacoes = extrair_movimentacoes_com_data(texto)

    if not movimentacoes:
        return ""

    # O portal pode apresentar a movimentação mais recente
    # no início ou no fim. Aqui preservamos a última linha exibida.
    return movimentacoes[-1][:1500]


def extrair_classe_processual(texto: str) -> str:
    padroes = [
        r"Classe\s+processual\s*:?\s*([^\n]+)",
        r"Classe\s*:?\s*([^\n]+)",
    ]

    for padrao in padroes:
        resultado = re.search(
            padrao,
            texto,
            flags=re.IGNORECASE,
        )

        if resultado:
            return resultado.group(1).strip()[:300]

    return ""


def extrair_orgao_julgador(texto: str) -> str:
    padroes = [
        r"Órgão\s+julgador\s*:?\s*([^\n]+)",
        r"Orgao\s+julgador\s*:?\s*([^\n]+)",
    ]

    for padrao in padroes:
        resultado = re.search(
            padrao,
            texto,
            flags=re.IGNORECASE,
        )

        if resultado:
            return resultado.group(1).strip()[:300]

    return ""


def extrair_relator(texto: str) -> str:
    padroes = [
        r"Relator(?:a)?\s*:?\s*([^\n]+)",
        r"Ministro(?:a)?\s+Relator(?:a)?\s*:?\s*([^\n]+)",
    ]

    for padrao in padroes:
        resultado = re.search(
            padrao,
            texto,
            flags=re.IGNORECASE,
        )

        if resultado:
            return resultado.group(1).strip()[:300]

    return ""


# ============================================================
# RESULTADOS E DIAGNÓSTICO
# ============================================================

def montar_resultado(
    processo: str,
    possui_processo_tst: str,
    transito: str,
    situacao: str,
    fundamento: str = "",
    classe_processual: str = "",
    orgao_julgador: str = "",
    relator: str = "",
    ultima_movimentacao: str = "",
    trecho_relevante: str = "",
    url_final: str = "",
    erro: str = "",
) -> dict:
    return {
        "Processo": processo,
        "Possui processo no TST": possui_processo_tst,
        "Trânsito em julgado no TST": transito,
        "Fundamento encontrado": fundamento,
        "Classe processual no TST": classe_processual,
        "Órgão julgador": orgao_julgador,
        "Relator": relator,
        "Última movimentação identificada": ultima_movimentacao,
        "Trecho relevante": trecho_relevante,
        "Situação da consulta": situacao,
        "Data e hora da consulta": datetime.now().strftime(
            "%d/%m/%Y %H:%M:%S"
        ),
        "URL consultada": url_final,
        "Detalhes do erro": erro,
    }


def salvar_diagnostico(
    driver: webdriver.Chrome,
    numero_processo: str,
) -> None:
    PASTA_DIAGNOSTICO.mkdir(
        parents=True,
        exist_ok=True,
    )

    nome_seguro = (
        numero_processo
        .replace(".", "_")
        .replace("-", "_")
    )

    imagem = PASTA_DIAGNOSTICO / f"{nome_seguro}.png"
    html = PASTA_DIAGNOSTICO / f"{nome_seguro}.html"

    try:
        driver.save_screenshot(str(imagem))
    except WebDriverException:
        pass

    try:
        html.write_text(
            driver.page_source,
            encoding="utf-8",
        )
    except (OSError, WebDriverException):
        pass


# ============================================================
# CONSULTA INDIVIDUAL
# ============================================================

def consultar_processo_tst(
    driver: webdriver.Chrome,
    numero_processo: str,
) -> dict:
    numero_processo = numero_processo.strip()

    if not validar_numero_processo(numero_processo):
        return montar_resultado(
            processo=numero_processo,
            possui_processo_tst="Não consultado",
            transito="Não consultado",
            situacao="Número em formato inválido",
            erro=(
                "Formato esperado: "
                "0000000-00.0000.0.00.0000"
            ),
        )

    # Acessa diretamente a página do número CNJ.
    driver.get(url_consulta(numero_processo))
    aguardar_pagina(driver)
    time.sleep(1)

    texto_inicial = obter_texto_pagina(driver)

    if detectar_captcha(texto_inicial):
        return montar_resultado(
            processo=numero_processo,
            possui_processo_tst="Não consultado",
            transito="Não consultado",
            situacao="CAPTCHA identificado",
            url_final=driver.current_url,
            erro=(
                "O portal apresentou verificação de segurança."
            ),
        )

    if detectar_nao_encontrado(texto_inicial):
        return montar_resultado(
            processo=numero_processo,
            possui_processo_tst="Não",
            transito="Não se aplica",
            situacao="Processo não encontrado",
            url_final=driver.current_url,
        )

    abriu_tst, mensagem_tst = abrir_resultado_tst(
        driver,
        numero_processo,
    )

    if not abriu_tst:
        return montar_resultado(
            processo=numero_processo,
            possui_processo_tst="Não",
            transito="Não se aplica",
            situacao=mensagem_tst,
            url_final=driver.current_url,
        )

    texto_tst = obter_texto_pagina(driver)

    if detectar_captcha(texto_tst):
        return montar_resultado(
            processo=numero_processo,
            possui_processo_tst="Não consultado",
            transito="Não consultado",
            situacao="CAPTCHA identificado no detalhe do TST",
            url_final=driver.current_url,
            erro=(
                "O portal solicitou verificação humana ao abrir "
                "a terceira instância."
            ),
        )

    transito, fundamento = analisar_transito(texto_tst)

    trecho = extrair_trecho_relevante(
        texto_tst,
        TERMOS_TRANSITO_CONFIRMADO + TERMOS_BAIXA,
    )

    return montar_resultado(
        processo=numero_processo,
        possui_processo_tst="Sim",
        transito=transito,
        fundamento=fundamento,
        classe_processual=extrair_classe_processual(texto_tst),
        orgao_julgador=extrair_orgao_julgador(texto_tst),
        relator=extrair_relator(texto_tst),
        ultima_movimentacao=extrair_ultima_movimentacao(
            texto_tst
        ),
        trecho_relevante=trecho,
        situacao=f"Consulta concluída — {mensagem_tst}",
        url_final=driver.current_url,
    )


# ============================================================
# GERAÇÃO DO EXCEL — SOMENTE NO FINAL
# ============================================================

def salvar_excel_final(resultados: list[dict]) -> None:
    if not resultados:
        print("Nenhum resultado disponível para gerar o Excel.")
        return

    df = pd.DataFrame(resultados)

    colunas = [
        "Processo",
        "Possui processo no TST",
        "Trânsito em julgado no TST",
        "Fundamento encontrado",
        "Classe processual no TST",
        "Órgão julgador",
        "Relator",
        "Última movimentação identificada",
        "Trecho relevante",
        "Situação da consulta",
        "Data e hora da consulta",
        "URL consultada",
        "Detalhes do erro",
    ]

    for coluna in colunas:
        if coluna not in df.columns:
            df[coluna] = ""

    df = df[colunas]

    resumo = pd.DataFrame(
        {
            "Indicador": [
                "Total de números informados",
                "Processos encontrados no TST",
                "Processos sem resultado no TST",
                "Trânsito em julgado confirmado",
                "Possível trânsito ou baixa",
                "Trânsito não localizado",
                "Consultas com erro",
            ],
            "Quantidade": [
                len(df),
                int(
                    (
                        df["Possui processo no TST"] == "Sim"
                    ).sum()
                ),
                int(
                    (
                        df["Possui processo no TST"] == "Não"
                    ).sum()
                ),
                int(
                    (
                        df["Trânsito em julgado no TST"] == "Sim"
                    ).sum()
                ),
                int(
                    (
                        df["Trânsito em julgado no TST"]
                        == "Possível"
                    ).sum()
                ),
                int(
                    (
                        df["Trânsito em julgado no TST"]
                        == "Não localizado"
                    ).sum()
                ),
                int(
                    df["Situação da consulta"]
                    .str.contains(
                        "erro|captcha",
                        case=False,
                        na=False,
                    )
                    .sum()
                ),
            ],
        }
    )

    with pd.ExcelWriter(
        ARQUIVO_SAIDA,
        engine="openpyxl",
    ) as writer:
        df.to_excel(
            writer,
            sheet_name="Resultados_TST",
            index=False,
        )

        resumo.to_excel(
            writer,
            sheet_name="Resumo",
            index=False,
        )

        planilha = writer.book["Resultados_TST"]
        planilha.freeze_panes = "A2"
        planilha.auto_filter.ref = planilha.dimensions

        preenchimento_cabecalho = PatternFill(
            fill_type="solid",
            fgColor="1F4E78",
        )

        fonte_cabecalho = Font(
            color="FFFFFF",
            bold=True,
        )

        for celula in planilha[1]:
            celula.fill = preenchimento_cabecalho
            celula.font = fonte_cabecalho
            celula.alignment = Alignment(
                horizontal="center",
                vertical="center",
                wrap_text=True,
            )

        larguras = {
            "A": 28,
            "B": 23,
            "C": 29,
            "D": 32,
            "E": 35,
            "F": 35,
            "G": 35,
            "H": 75,
            "I": 100,
            "J": 45,
            "K": 22,
            "L": 75,
            "M": 100,
        }

        for coluna, largura in larguras.items():
            planilha.column_dimensions[coluna].width = largura

        for linha in planilha.iter_rows(min_row=2):
            for celula in linha:
                celula.alignment = Alignment(
                    vertical="top",
                    wrap_text=True,
                )

        planilha_resumo = writer.book["Resumo"]
        planilha_resumo.freeze_panes = "A2"
        planilha_resumo.column_dimensions["A"].width = 40
        planilha_resumo.column_dimensions["B"].width = 15

        for celula in planilha_resumo[1]:
            celula.fill = preenchimento_cabecalho
            celula.font = fonte_cabecalho
            celula.alignment = Alignment(
                horizontal="center",
            )


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:
    resultados: list[dict] = []
    driver = None

    # Remove números duplicados preservando a ordem.
    processos_unicos = list(dict.fromkeys(processos))

    quantidade_original = len(processos)
    quantidade_unica = len(processos_unicos)
    duplicados = quantidade_original - quantidade_unica

    print("=" * 75)
    print("CONSULTA DE PROCESSOS — SOMENTE TERCEIRA INSTÂNCIA/TST")
    print(f"Números informados: {quantidade_original}")
    print(f"Números únicos: {quantidade_unica}")
    print(f"Duplicados removidos: {duplicados}")
    print("=" * 75)

    try:
        driver = criar_driver()

        for indice, numero_processo in enumerate(
            processos_unicos,
            start=1,
        ):
            print(
                f"\n[{indice}/{quantidade_unica}] "
                f"Consultando no TST: {numero_processo}"
            )

            try:
                resultado = consultar_processo_tst(
                    driver,
                    numero_processo,
                )

                resultados.append(resultado)

                print(
                    "  Processo no TST:",
                    resultado["Possui processo no TST"],
                )

                print(
                    "  Trânsito em julgado:",
                    resultado["Trânsito em julgado no TST"],
                )

                print(
                    "  Situação:",
                    resultado["Situação da consulta"],
                )

            except TimeoutException as erro:
                salvar_diagnostico(
                    driver,
                    numero_processo,
                )

                resultados.append(
                    montar_resultado(
                        processo=numero_processo,
                        possui_processo_tst="Não confirmado",
                        transito="Não analisado",
                        situacao="Tempo de espera excedido",
                        url_final=driver.current_url,
                        erro=str(erro) or "TimeoutException",
                    )
                )

                print("  Erro: tempo de espera excedido.")

            except WebDriverException as erro:
                salvar_diagnostico(
                    driver,
                    numero_processo,
                )

                resultados.append(
                    montar_resultado(
                        processo=numero_processo,
                        possui_processo_tst="Não confirmado",
                        transito="Não analisado",
                        situacao="Erro do navegador",
                        url_final=(
                            driver.current_url
                            if driver
                            else ""
                        ),
                        erro=str(erro),
                    )
                )

                print("  Erro do navegador:", erro)

            except Exception as erro:
                salvar_diagnostico(
                    driver,
                    numero_processo,
                )

                resultados.append(
                    montar_resultado(
                        processo=numero_processo,
                        possui_processo_tst="Não confirmado",
                        transito="Não analisado",
                        situacao="Erro inesperado",
                        url_final=(
                            driver.current_url
                            if driver
                            else ""
                        ),
                        erro=(
                            f"{type(erro).__name__}: {erro}\n"
                            f"{traceback.format_exc()}"
                        ),
                    )
                )

                print(
                    "  Erro inesperado:",
                    type(erro).__name__,
                    erro,
                )

            if indice < quantidade_unica:
                time.sleep(INTERVALO_ENTRE_PROCESSOS)

    finally:
        if driver is not None:
            driver.quit()

    # O Excel é criado somente aqui, depois de todo o processamento.
    salvar_excel_final(resultados)

    print("\n" + "=" * 75)
    print("PROCESSAMENTO FINALIZADO")
    print(f"Processos analisados: {len(resultados)}")
    print(f"Excel gerado: {ARQUIVO_SAIDA.resolve()}")
    print("=" * 75)


if __name__ == "__main__":
    main()