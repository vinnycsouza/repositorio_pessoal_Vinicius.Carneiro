from __future__ import annotations

import shutil
from pathlib import Path


# O download_button mantém os bytes em memória. A margem abaixo evita atingir
# o limite padrão de mensagem do Streamlit e preserva RAM para a aplicação.
LIMITE_DOWNLOAD_STREAMLIT = 180 * 1024 * 1024


def exige_entrega_local(caminho: str | Path) -> bool:
    return Path(caminho).stat().st_size > LIMITE_DOWNLOAD_STREAMLIT


def pasta_downloads_padrao() -> Path:
    return (Path.home() / "Downloads").resolve()


def _destino_disponivel(pasta: Path, nome: str) -> Path:
    candidato = pasta / nome
    if not candidato.exists():
        return candidato
    origem = Path(nome)
    indice = 1
    while True:
        candidato = pasta / f"{origem.stem} ({indice}){origem.suffix}"
        if not candidato.exists():
            return candidato
        indice += 1


def copiar_para_downloads(
    caminho: str | Path,
    pasta_downloads: str | Path | None = None,
) -> Path:
    origem = Path(caminho).expanduser().resolve()
    if not origem.is_file():
        raise FileNotFoundError(f"Arquivo não localizado: {origem}")
    pasta = (
        Path(pasta_downloads).expanduser().resolve()
        if pasta_downloads is not None
        else pasta_downloads_padrao()
    )
    pasta.mkdir(parents=True, exist_ok=True)
    destino = _destino_disponivel(pasta, origem.name)
    shutil.copy2(origem, destino)
    return destino
