from __future__ import annotations

import re
import time
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# ============================================================
# CONFIGURAÇÕES
# ============================================================

URL_CONSULTA = "https://pje.tst.jus.br/consultaprocessual/"

ARQUIVO_SAIDA = Path("status_processos_tst.xlsx")
PASTA_ERROS = Path("erros_consulta")

TEMPO_ESPERA = 25
INTERVALO_ENTRE_CONSULTAS = 3

# False = mostra o navegador.
# True = executa sem abrir a janela.
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

    # Continue aqui com os demais processos.
]


# ============================================================
# TERMOS UTILIZADOS NA ANÁLISE
# ============================================================

TERMOS_TRANSITO = [
    "trânsito em julgado",
    "transito em julgado",
    "transitada em julgado",
    "transitado em julgado",
    "certificado o trânsito em julgado",
    "certificado o transito em julgado",
    "certidão de trânsito em julgado",
    "certidao de transito em julgado",
]

TERMOS_BAIXA = [
    "baixa definitiva",
    "baixado definitivamente",
    "arquivado definitivamente",
    "arquivamento definitivo",
]

TERMOS_CAPTCHA = [
    "captcha",
    "não sou um robô",
    "nao sou um robo",
    "digite os caracteres",
    "digite os números do áudio",
    "digite os numeros do audio",
    "verificação de segurança",
    "verificacao de seguranca",
]

TERMOS_NAO_ENCONTRADO = [
    "processo não encontrado",
    "processo nao encontrado",
    "nenhum processo encontrado",
    "não foram encontrados processos",
    "nao foram encontrados processos",
    "nenhum resultado encontrado",
]


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def normalizar_texto(texto: str) -> str:
    """Normaliza espaços e converte o texto para minúsculas."""
    texto = texto or ""
    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip().lower()


def validar_numero_processo(numero: str) -> bool:
    """Valida apenas o formato visual do número CNJ."""
    padrao = r"^\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}$"
    return bool(re.fullmatch(padrao, numero.strip()))


def criar_driver() -> webdriver.Chrome:
    """
    Cria o Chrome usando o Selenium Manager.

    Nas versões atuais do Selenium, normalmente não é necessário
    usar webdriver-manager ou informar o caminho do ChromeDriver.
    """
    options = webdriver.ChromeOptions()

    if EXECUTAR_EM_SEGUNDO_PLANO:
        options.add_argument("--headless=new")

    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    options.add_experimental_option(
        "excludeSwitches",
        ["enable-logging"],
    )

    return webdriver.Chrome(options=options)


def encontrar_primeiro_elemento(
    driver: webdriver.Chrome,
    seletores: list[tuple[str, str]],
    timeout: int = TEMPO_ESPERA,
):
    """
    Tenta localizar um elemento usando vários seletores.
    Retorna o primeiro encontrado.
    """
    ultimo_erro = None

    for tipo, seletor in seletores:
        try:
            elemento = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((tipo, seletor))
            )

            if elemento.is_displayed():
                return elemento

        except (TimeoutException, NoSuchElementException) as erro:
            ultimo_erro = erro

    raise TimeoutException(
        "Não foi possível localizar o campo de número do processo."
    ) from ultimo_erro


def encontrar_campo_processo(driver: webdriver.Chrome):
    """
    Procura o campo de pesquisa usando diferentes possibilidades.
    Isso reduz a dependência de um único ID.
    """
    seletores = [
        (By.ID, "numeroProcesso"),
        (By.NAME, "numeroProcesso"),
        (By.CSS_SELECTOR, 'input[placeholder*="Número do processo"]'),
        (By.CSS_SELECTOR, 'input[placeholder*="número do processo"]'),
        (By.CSS_SELECTOR, 'input[placeholder*="Numero do processo"]'),
        (By.CSS_SELECTOR, 'input[aria-label*="Número do processo"]'),
        (By.CSS_SELECTOR, 'input[aria-label*="Processo"]'),
        (By.CSS_SELECTOR, 'input[type="text"]'),
    ]

    return encontrar_primeiro_elemento(driver, seletores)


def clicar_botao_pesquisar(driver: webdriver.Chrome) -> None:
    """
    Procura o botão de pesquisa por ID, texto ou tipo.
    Caso não encontre, pressiona ENTER no campo.
    """
    seletores = [
        (By.ID, "botaoPesquisar"),
        (By.ID, "btnPesquisar"),
        (By.CSS_SELECTOR, 'button[type="submit"]'),
        (
            By.XPATH,
            "//button[contains("
            "translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÃÂÉÊÍÓÔÕÚÇ', "
            "'abcdefghijklmnopqrstuvwxyzáàãâéêíóôõúç'), "
            "'pesquisar')]",
        ),
        (
            By.XPATH,
            "//button[contains("
            "translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÃÂÉÊÍÓÔÕÚÇ', "
            "'abcdefghijklmnopqrstuvwxyzáàãâéêíóôõúç'), "
            "'consultar')]",
        ),
        (
            By.XPATH,
            "//button[contains("
            "translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÃÂÉÊÍÓÔÕÚÇ', "
            "'abcdefghijklmnopqrstuvwxyzáàãâéêíóôõúç'), "
            "'buscar')]",
        ),
    ]

    for tipo, seletor in seletores:
        try:
            botao = WebDriverWait(driver, 4).until(
                EC.element_to_be_clickable((tipo, seletor))
            )

            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                botao,
            )

            try:
                botao.click()
            except WebDriverException:
                driver.execute_script("arguments[0].click();", botao)

            return

        except (TimeoutException, NoSuchElementException):
            continue

    campo = encontrar_campo_processo(driver)
    campo.send_keys(Keys.ENTER)


def obter_texto_pagina(driver: webdriver.Chrome) -> str:
    """Captura todo o texto visível da página."""
    corpo = WebDriverWait(driver, TEMPO_ESPERA).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    return corpo.text


def detectar_captcha(texto: str) -> bool:
    texto_normalizado = normalizar_texto(texto)
    return any(termo in texto_normalizado for termo in TERMOS_CAPTCHA)


def detectar_processo_nao_encontrado(texto: str) -> bool:
    texto_normalizado = normalizar_texto(texto)

    return any(
        termo in texto_normalizado
        for termo in TERMOS_NAO_ENCONTRADO
    )


def analisar_transito(texto: str) -> tuple[str, str]:
    """
    Retorna:
        resultado: Sim, Não ou Indeterminado
        fundamento: termo encontrado
    """
    texto_normalizado = normalizar_texto(texto)

    for termo in TERMOS_TRANSITO:
        if termo in texto_normalizado:
            return "Sim", termo

    for termo in TERMOS_BAIXA:
        if termo in texto_normalizado:
            return "Possível", termo

    return "Não localizado", ""


def extrair_trecho_relevante(
    texto: str,
    termos: list[str],
    tamanho: int = 250,
) -> str:
    """Extrai um pequeno trecho em torno do termo encontrado."""
    texto_limpo = re.sub(r"\s+", " ", texto or "").strip()
    texto_minusculo = texto_limpo.lower()

    for termo in termos:
        posicao = texto_minusculo.find(termo.lower())

        if posicao >= 0:
            inicio = max(0, posicao - tamanho)
            fim = min(len(texto_limpo), posicao + tamanho)

            return texto_limpo[inicio:fim]

    return ""


def extrair_ultima_movimentacao(texto: str) -> str:
    """
    Tenta capturar a última movimentação exibida.

    Como cada portal pode apresentar uma estrutura diferente,
    esta extração é aproximada.
    """
    linhas = [
        linha.strip()
        for linha in texto.splitlines()
        if linha.strip()
    ]

    padrao_data = re.compile(
        r"\b\d{2}/\d{2}/\d{4}\b"
        r"|"
        r"\b\d{2}/\d{2}/\d{2}\b"
    )

    linhas_com_data = [
        linha
        for linha in linhas
        if padrao_data.search(linha)
    ]

    if not linhas_com_data:
        return ""

    return linhas_com_data[-1][:1000]


def salvar_resultados(resultados: list[dict]) -> None:
    """
    Salva os resultados após cada consulta.

    Assim, se a execução for interrompida, os processos já
    analisados permanecem no Excel.
    """
    df = pd.DataFrame(resultados)

    colunas = [
        "Processo",
        "Trânsito em Julgado",
        "Fundamento encontrado",
        "Última movimentação identificada",
        "Trecho relevante",
        "Situação da consulta",
        "Data e hora da consulta",
        "URL final",
        "Detalhes do erro",
    ]

    for coluna in colunas:
        if coluna not in df.columns:
            df[coluna] = ""

    df = df[colunas]

    with pd.ExcelWriter(
        ARQUIVO_SAIDA,
        engine="openpyxl",
    ) as writer:
        df.to_excel(
            writer,
            sheet_name="Resultados",
            index=False,
        )

        planilha = writer.book["Resultados"]
        planilha.freeze_panes = "A2"
        planilha.auto_filter.ref = planilha.dimensions

        larguras = {
            "A": 28,
            "B": 22,
            "C": 30,
            "D": 70,
            "E": 100,
            "F": 28,
            "G": 22,
            "H": 60,
            "I": 100,
        }

        for coluna, largura in larguras.items():
            planilha.column_dimensions[coluna].width = largura

        for linha in planilha.iter_rows(min_row=2):
            for celula in linha:
                celula.alignment = celula.alignment.copy(
                    vertical="top",
                    wrap_text=True,
                )


def salvar_diagnostico(
    driver: webdriver.Chrome,
    numero_processo: str,
) -> None:
    """Salva captura de tela e HTML quando ocorrer erro."""
    PASTA_ERROS.mkdir(exist_ok=True)

    nome_seguro = numero_processo.replace(".", "_").replace("-", "_")

    caminho_imagem = PASTA_ERROS / f"{nome_seguro}.png"
    caminho_html = PASTA_ERROS / f"{nome_seguro}.html"

    try:
        driver.save_screenshot(str(caminho_imagem))
    except WebDriverException:
        pass

    try:
        caminho_html.write_text(
            driver.page_source,
            encoding="utf-8",
        )
    except (OSError, WebDriverException):
        pass


def montar_resultado(
    processo: str,
    transito: str,
    fundamento: str = "",
    ultima_movimentacao: str = "",
    trecho: str = "",
    situacao: str = "",
    url_final: str = "",
    erro: str = "",
) -> dict:
    return {
        "Processo": processo,
        "Trânsito em Julgado": transito,
        "Fundamento encontrado": fundamento,
        "Última movimentação identificada": ultima_movimentacao,
        "Trecho relevante": trecho,
        "Situação da consulta": situacao,
        "Data e hora da consulta": datetime.now().strftime(
            "%d/%m/%Y %H:%M:%S"
        ),
        "URL final": url_final,
        "Detalhes do erro": erro,
    }


# ============================================================
# CONSULTA DE UM PROCESSO
# ============================================================

def consultar_processo(
    driver: webdriver.Chrome,
    numero_processo: str,
) -> dict:
    numero_processo = numero_processo.strip()

    if not validar_numero_processo(numero_processo):
        return montar_resultado(
            processo=numero_processo,
            transito="Não consultado",
            situacao="Número em formato inválido",
            erro=(
                "Formato esperado: "
                "0000000-00.0000.0.00.0000"
            ),
        )

    driver.get(URL_CONSULTA)

    WebDriverWait(driver, TEMPO_ESPERA).until(
        lambda navegador: navegador.execute_script(
            "return document.readyState"
        ) == "complete"
    )

    texto_inicial = obter_texto_pagina(driver)

    if detectar_captcha(texto_inicial):
        return montar_resultado(
            processo=numero_processo,
            transito="Não consultado",
            situacao="CAPTCHA identificado",
            url_final=driver.current_url,
            erro=(
                "O portal apresentou uma verificação de segurança. "
                "Resolva o CAPTCHA manualmente no navegador e execute "
                "novamente."
            ),
        )

    campo = encontrar_campo_processo(driver)

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});",
        campo,
    )

    campo.click()
    campo.send_keys(Keys.CONTROL, "a")
    campo.send_keys(Keys.BACKSPACE)
    campo.send_keys(numero_processo)

    clicar_botao_pesquisar(driver)

    # Aguarda a página ou o conteúdo da consulta mudar.
    try:
        WebDriverWait(driver, TEMPO_ESPERA).until(
            lambda navegador: (
                numero_processo in navegador.page_source
                or navegador.current_url != URL_CONSULTA
                or "resultado" in navegador.page_source.lower()
                or "movimenta" in navegador.page_source.lower()
                or "captcha" in navegador.page_source.lower()
            )
        )
    except TimeoutException:
        # Continua para analisar o conteúdo disponível.
        pass

    time.sleep(2)

    texto_resultado = obter_texto_pagina(driver)

    if detectar_captcha(texto_resultado):
        return montar_resultado(
            processo=numero_processo,
            transito="Não consultado",
            situacao="CAPTCHA identificado",
            url_final=driver.current_url,
            erro=(
                "O portal solicitou verificação humana durante "
                "a consulta."
            ),
        )

    if detectar_processo_nao_encontrado(texto_resultado):
        return montar_resultado(
            processo=numero_processo,
            transito="Não localizado",
            situacao="Processo não encontrado no portal",
            url_final=driver.current_url,
        )

    transito, fundamento = analisar_transito(texto_resultado)

    trecho = extrair_trecho_relevante(
        texto_resultado,
        TERMOS_TRANSITO + TERMOS_BAIXA,
    )

    ultima_movimentacao = extrair_ultima_movimentacao(
        texto_resultado
    )

    return montar_resultado(
        processo=numero_processo,
        transito=transito,
        fundamento=fundamento,
        ultima_movimentacao=ultima_movimentacao,
        trecho=trecho,
        situacao="Consulta concluída",
        url_final=driver.current_url,
    )


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:
    resultados: list[dict] = []

    # Remove duplicidades preservando a ordem original.
    processos_unicos = list(dict.fromkeys(processos))

    print("=" * 70)
    print("CONSULTA PROCESSUAL")
    print(f"Quantidade informada: {len(processos)}")
    print(f"Quantidade sem duplicidade: {len(processos_unicos)}")
    print("=" * 70)

    driver = None

    try:
        driver = criar_driver()

        for indice, numero_processo in enumerate(
            processos_unicos,
            start=1,
        ):
            print(
                f"\n[{indice}/{len(processos_unicos)}] "
                f"Consultando {numero_processo}..."
            )

            try:
                resultado = consultar_processo(
                    driver,
                    numero_processo,
                )

                resultados.append(resultado)

                print(
                    "Resultado:",
                    resultado["Trânsito em Julgado"],
                    "-",
                    resultado["Situação da consulta"],
                )

            except TimeoutException as erro:
                salvar_diagnostico(driver, numero_processo)

                resultados.append(
                    montar_resultado(
                        processo=numero_processo,
                        transito="Erro na consulta",
                        situacao="Tempo de espera excedido",
                        url_final=driver.current_url,
                        erro=str(erro) or "TimeoutException",
                    )
                )

                print("Erro: tempo de espera excedido.")

            except WebDriverException as erro:
                salvar_diagnostico(driver, numero_processo)

                resultados.append(
                    montar_resultado(
                        processo=numero_processo,
                        transito="Erro na consulta",
                        situacao="Erro do navegador",
                        url_final=(
                            driver.current_url
                            if driver
                            else ""
                        ),
                        erro=str(erro),
                    )
                )

                print("Erro do navegador:", erro)

            except Exception as erro:
                salvar_diagnostico(driver, numero_processo)

                resultados.append(
                    montar_resultado(
                        processo=numero_processo,
                        transito="Erro na consulta",
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
                    f"Erro inesperado: "
                    f"{type(erro).__name__}: {erro}"
                )

            # Salva depois de cada processo.
            salvar_resultados(resultados)

            if indice < len(processos_unicos):
                time.sleep(INTERVALO_ENTRE_CONSULTAS)

    finally:
        if driver is not None:
            driver.quit()

    print("\n" + "=" * 70)
    print("AUTOMAÇÃO FINALIZADA")
    print(f"Arquivo gerado: {ARQUIVO_SAIDA.resolve()}")
    print(f"Processos consultados: {len(resultados)}")
    print("=" * 70)


if __name__ == "__main__":
    main()