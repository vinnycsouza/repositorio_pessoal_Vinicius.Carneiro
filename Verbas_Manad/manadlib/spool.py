from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, Set

import pandas as pd

from .layout import extrair_codigo_evento


def spool_init_state() -> dict:
    """
    Estado serializável para processamento incremental no Streamlit Cloud.
    """
    return {
        "initialized": False,
        "done": False,
        "offset": 0,          # bytes consumidos no TXT
        "buffer": "",         # sobra de linha entre chunks no TXT
        "paths": {},          # código do evento -> caminho temporário
        "counts": {},         # código do evento -> quantidade de linhas
        "is_txt": None,
        "total_bytes": 1,
    }


def _get_path(
    paths: Dict[str, str],
    tmp_dir: Path,
    codigo: str,
) -> Path:
    """
    Obtém ou cria o caminho temporário de determinado evento.
    """
    if codigo not in paths:
        path_evento = tmp_dir / f"{codigo}.txt"
        paths[codigo] = str(path_evento)

    return Path(paths[codigo])


def _normalizar_valor_excel(valor) -> str:
    """
    Converte um valor vindo do Excel para texto MANAD.

    Evita:
    - NaN;
    - None;
    - espaços laterais;
    - valores numéricos inteiros terminando em '.0'.

    Exemplos:
      354.0 -> 354
      NaN   -> ""
    """
    if valor is None:
        return ""

    texto = str(valor).strip()

    if not texto:
        return ""

    if texto.lower() in {"nan", "none", "nat"}:
        return ""

    # Corrige números inteiros eventualmente lidos como 354.0
    if texto.endswith(".0"):
        parte_inteira = texto[:-2]

        if parte_inteira.lstrip("-").isdigit():
            return parte_inteira

    return texto


def _identificar_evento_excel(
    nome_aba: str,
    valores: list[str],
    eventos_alvo: Set[str],
) -> str | None:
    """
    Identifica o evento de uma linha do Excel.

    Ordem de prioridade:
    1. Primeiro campo da própria linha;
    2. Nome da aba.
    """
    if valores:
        primeiro_campo = valores[0].strip().upper()

        if primeiro_campo in eventos_alvo:
            return primeiro_campo

        # Compatibilidade com uma célula contendo a linha MANAD completa
        codigo_linha = extrair_codigo_evento(primeiro_campo)

        if codigo_linha in eventos_alvo:
            return codigo_linha

    codigo_aba = str(nome_aba).strip().upper()

    if codigo_aba in eventos_alvo:
        return codigo_aba

    # Permite nomes como "K150_RUBRICAS" ou "K300 - MOVIMENTOS"
    for evento in eventos_alvo:
        if codigo_aba.startswith(evento):
            return evento

    return None


def _processar_excel(
    uploaded_file,
    tmp_dir: Path,
    eventos_alvo: Set[str],
    paths: Dict[str, str],
    counts,
    progress_bar=None,
    status_slot=None,
) -> None:
    """
    Processa um arquivo Excel aceitando dois formatos:

    1. Excel estruturado em colunas:
       REG | CNPJ/CEI | DT_INC_ALT | COD_RUBRICA | DESC_RUBRICA

    2. Excel com a linha MANAD completa em uma única célula:
       K150|...|...|...

    Os registros são reconstruídos e gravados nos temporários:
      K150.txt
      K300.txt
      K050.txt
    """
    uploaded_file.seek(0)

    xls = pd.ExcelFile(uploaded_file)
    total_abas = len(xls.sheet_names) or 1

    for indice_aba, nome_aba in enumerate(xls.sheet_names, start=1):
        if progress_bar:
            progress_bar.progress(indice_aba / total_abas)

        if status_slot:
            status_slot.text(
                f"Lendo aba: {nome_aba} "
                f"({indice_aba}/{total_abas})"
            )

        # header=0: a primeira linha é tratada como cabeçalho.
        # dtype=str: evita conversões desnecessárias dos códigos.
        # keep_default_na=False: células vazias permanecem como "".
        df_aba = pd.read_excel(
            xls,
            sheet_name=nome_aba,
            header=0,
            dtype=str,
            keep_default_na=False,
        )

        if df_aba.empty:
            continue

        for valores_linha in df_aba.itertuples(index=False, name=None):
            valores = [
                _normalizar_valor_excel(valor)
                for valor in valores_linha
            ]

            # Remove apenas colunas totalmente excedentes no fim da linha.
            # Campos vazios intermediários são preservados.
            while valores and valores[-1] == "":
                valores.pop()

            if not valores:
                continue

            codigo = _identificar_evento_excel(
                nome_aba=nome_aba,
                valores=valores,
                eventos_alvo=eventos_alvo,
            )

            if not codigo:
                continue

            # Caso antigo: uma única coluna contém toda a linha MANAD.
            if len(valores) == 1 and "|" in valores[0]:
                linha_manad = valores[0].strip()

            else:
                # Caso novo: cada campo do MANAD está em uma coluna.
                #
                # Se a aba identifica o evento, mas a primeira coluna da linha
                # não contém REG, acrescentamos o código do evento no início.
                primeiro_campo = valores[0].strip().upper() if valores else ""

                if primeiro_campo != codigo:
                    valores.insert(0, codigo)

                linha_manad = "|".join(valores)

            if not linha_manad:
                continue

            path_evento = _get_path(
                paths=paths,
                tmp_dir=tmp_dir,
                codigo=codigo,
            )

            with path_evento.open(
                "a",
                encoding="utf-8",
                newline="\n",
            ) as arquivo_saida:
                arquivo_saida.write(linha_manad + "\n")

            counts[codigo] += 1


def spool_step(
    state: dict,
    uploaded_file,
    tmp_dir: Path,
    eventos_alvo: Set[str],
    batch_bytes: int = 8_000_000,
    progress_bar=None,
    status_slot=None,
) -> dict:
    """
    Processa o MANAD em etapas.

    TXT:
      - leitura incremental em chunks;
      - separação por evento;
      - baixo consumo de memória.

    XLSX:
      - processamento em uma etapa;
      - aceita planilhas estruturadas em colunas;
      - aceita também linha MANAD completa em uma única coluna.
    """
    eventos_alvo = {
        str(evento).strip().upper()
        for evento in eventos_alvo
    }

    if state.get("done"):
        return state

    if not state.get("initialized"):
        state["is_txt"] = (
            str(uploaded_file.name)
            .lower()
            .endswith(".txt")
        )

        state["total_bytes"] = (
            getattr(uploaded_file, "size", None)
            or 1
        )

        state["offset"] = 0
        state["buffer"] = ""
        state["paths"] = state.get("paths") or {}
        state["counts"] = state.get("counts") or {}
        state["initialized"] = True

        if status_slot:
            status_slot.info(
                "Iniciando spool em modo incremental..."
            )

    # =========================================================
    # XLSX: processa o arquivo completo em uma etapa
    # =========================================================
    if not state["is_txt"]:
        if status_slot:
            status_slot.info(
                "Entrada XLSX: processando as abas estruturadas."
            )

        counts = defaultdict(
            int,
            state.get("counts") or {},
        )

        paths: Dict[str, str] = (
            state.get("paths")
            or {}
        )

        try:
            _processar_excel(
                uploaded_file=uploaded_file,
                tmp_dir=tmp_dir,
                eventos_alvo=eventos_alvo,
                paths=paths,
                counts=counts,
                progress_bar=progress_bar,
                status_slot=status_slot,
            )

            state["paths"] = paths
            state["counts"] = dict(counts)
            state["done"] = True

            if progress_bar:
                progress_bar.progress(1.0)

            if status_slot:
                eventos_encontrados = ", ".join(
                    sorted(paths.keys())
                )

                status_slot.success(
                    "Spool do Excel finalizado. "
                    f"Eventos encontrados: "
                    f"{eventos_encontrados or 'nenhum'}."
                )

            return state

        except Exception as erro:
            state["paths"] = paths
            state["counts"] = dict(counts)
            state["done"] = True
            state["error"] = str(erro)

            if status_slot:
                status_slot.error(
                    f"Erro ao processar o Excel: {erro}"
                )

            return state

    # =========================================================
    # TXT: processamento incremental por bytes
    # =========================================================
    counts = defaultdict(
        int,
        state.get("counts") or {},
    )

    paths: Dict[str, str] = (
        state.get("paths")
        or {}
    )

    try:
        uploaded_file.seek(state["offset"])
        chunk = uploaded_file.read(batch_bytes)

    except Exception as erro:
        state["counts"] = dict(counts)
        state["paths"] = paths
        state["done"] = True
        state["error"] = str(erro)
        return state

    if not chunk:
        # Finaliza eventual linha restante no buffer.
        buffer_restante = (
            state.get("buffer")
            or ""
        ).strip("\r\n")

        if buffer_restante:
            codigo = extrair_codigo_evento(
                buffer_restante
            )

            if codigo and codigo in eventos_alvo:
                path_evento = _get_path(
                    paths=paths,
                    tmp_dir=tmp_dir,
                    codigo=codigo,
                )

                with path_evento.open(
                    "a",
                    encoding="utf-8",
                    newline="\n",
                ) as arquivo_saida:
                    arquivo_saida.write(
                        buffer_restante + "\n"
                    )

                counts[codigo] += 1

        state["counts"] = dict(counts)
        state["paths"] = paths
        state["done"] = True

        if progress_bar:
            progress_bar.progress(1.0)

        if status_slot:
            status_slot.success(
                "Spool do TXT finalizado."
            )

        return state

    # Decodifica e preserva eventual linha incompleta.
    texto = chunk.decode(
        "latin1",
        errors="ignore",
    )

    texto = (
        state.get("buffer")
        or ""
    ) + texto

    linhas = texto.split("\n")

    state["buffer"] = linhas[-1]
    linhas_completas = linhas[:-1]

    for linha in linhas_completas:
        linha = linha.rstrip("\r")

        if not linha:
            continue

        codigo = extrair_codigo_evento(linha)

        if not codigo or codigo not in eventos_alvo:
            continue

        path_evento = _get_path(
            paths=paths,
            tmp_dir=tmp_dir,
            codigo=codigo,
        )

        with path_evento.open(
            "a",
            encoding="utf-8",
            newline="\n",
        ) as arquivo_saida:
            arquivo_saida.write(linha + "\n")

        counts[codigo] += 1

    state["offset"] += len(chunk)
    state["counts"] = dict(counts)
    state["paths"] = paths

    total_bytes = state.get("total_bytes") or 1

    if progress_bar:
        progress_bar.progress(
            min(
                state["offset"] / total_bytes,
                1.0,
            )
        )

    if status_slot:
        status_slot.text(
            "Spool em andamento... "
            f"{state['offset']}/{total_bytes} bytes"
        )

    return state