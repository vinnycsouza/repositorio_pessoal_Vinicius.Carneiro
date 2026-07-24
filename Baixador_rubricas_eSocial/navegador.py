from __future__ import annotations

from pathlib import Path
from typing import Callable
import json
import re
import time

from playwright.sync_api import sync_playwright, Browser, Page, TimeoutError as PlaywrightTimeoutError


class AutomacaoESocial:
    def __init__(self, config_path: str | Path, log: Callable[[str], None]):
        self.config_path = Path(config_path)
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.log = log
        self.pw = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    def conectar(self) -> str:
        porta = int(self.config.get("porta_cdp", 9222))
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{porta}")

        contextos = self.browser.contexts
        if not contextos:
            raise RuntimeError("Nenhum contexto do Chrome foi encontrado.")

        paginas = [p for c in contextos for p in c.pages]
        if not paginas:
            raise RuntimeError("Nenhuma página aberta foi encontrada.")

        paginas_esocial = [p for p in paginas if "esocial" in p.url.lower()]
        self.page = paginas_esocial[-1] if paginas_esocial else paginas[-1]
        self.page.set_default_timeout(int(self.config.get("timeout_ms", 20000)))
        return self.page.url

    def fechar(self) -> None:
        try:
            if self.pw:
                self.pw.stop()
        finally:
            self.pw = None
            self.browser = None
            self.page = None

    def validar_cnpj(self, cnpj_esperado: str) -> bool:
        seletor = self.config["seletores"].get("texto_cnpj_ou_empregador", "").strip()
        if not cnpj_esperado.strip():
            return True
        if not seletor:
            self.log("Validação de CNPJ não executada: seletor não configurado.")
            return True

        texto = self.page.locator(seletor).inner_text()
        so_numeros_tela = re.sub(r"\D", "", texto)
        so_numeros_esperado = re.sub(r"\D", "", cnpj_esperado)
        return so_numeros_esperado in so_numeros_tela

    def _validar_seletores(self) -> None:
        obrigatorios = [
            "campo_codigo_rubrica",
            "botao_pesquisar",
            "linhas_resultado",
            "botao_download_na_linha",
        ]
        faltando = [k for k in obrigatorios if not self.config["seletores"].get(k, "").strip()]
        if faltando:
            raise RuntimeError(
                "Seletores ainda não configurados no config.json: " + ", ".join(faltando)
            )

    def consultar_e_baixar(
        self,
        codigo: str,
        pasta_destino: str | Path,
        vigencias_locais: set[str],
        modo_completo: bool,
    ) -> list[tuple[str, str, str]]:
        if not self.page:
            raise RuntimeError("Chrome não conectado.")

        self._validar_seletores()
        seletores = self.config["seletores"]
        pasta = Path(pasta_destino)
        pasta.mkdir(parents=True, exist_ok=True)

        campo = self.page.locator(seletores["campo_codigo_rubrica"])
        campo.fill("")
        campo.fill(codigo)
        self.page.locator(seletores["botao_pesquisar"]).click()

        linhas = self.page.locator(seletores["linhas_resultado"])
        try:
            linhas.first.wait_for(state="visible")
        except PlaywrightTimeoutError:
            return [("", "nao_encontrado", "")]

        resultados: list[tuple[str, str, str]] = []
        total = linhas.count()

        for i in range(total):
            linha = linhas.nth(i)
            texto_linha = linha.inner_text()
            vigencia_match = re.search(r"(20\d{2})[-/](0[1-9]|1[0-2])", texto_linha)
            vigencia = ""
            if vigencia_match:
                vigencia = f"{vigencia_match.group(1)}-{vigencia_match.group(2)}"

            if modo_completo and vigencia and vigencia in vigencias_locais:
                resultados.append((vigencia, "ja_existente", ""))
                continue

            botao = linha.locator(seletores["botao_download_na_linha"])
            with self.page.expect_download() as download_info:
                botao.click()
            download = download_info.value

            nome_sugerido = download.suggested_filename or f"{codigo}_{vigencia or i+1}.xml"
            destino = pasta / nome_sugerido
            if destino.exists():
                base = destino.stem
                ext = destino.suffix
                n = 1
                while destino.exists():
                    destino = pasta / f"{base} ({n}){ext}"
                    n += 1

            download.save_as(destino)
            resultados.append((vigencia, "baixado", str(destino)))

        time.sleep(float(self.config.get("pausa_entre_codigos_seg", 0.8)))
        return resultados
