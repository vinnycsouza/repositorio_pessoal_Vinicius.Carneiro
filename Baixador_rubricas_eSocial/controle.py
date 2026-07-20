from __future__ import annotations

from pathlib import Path
from datetime import datetime
import csv
import json
from threading import Lock


class ControleExecucao:
    def __init__(self, pasta: str | Path):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.json_path = self.pasta / "controle_execucao.json"
        self.csv_path = self.pasta / "resultado_download.csv"
        self.lock = Lock()

    def carregar_processados(self) -> set[str]:
        if not self.json_path.exists():
            return set()
        try:
            dados = json.loads(self.json_path.read_text(encoding="utf-8"))
            return {str(x).upper() for x in dados.get("processados", [])}
        except Exception:
            return set()

    def salvar_estado(self, processados: set[str], ultimo_codigo: str = "") -> None:
        conteudo = {
            "ultimo_codigo": ultimo_codigo,
            "processados": sorted(processados),
            "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        }
        with self.lock:
            self.json_path.write_text(
                json.dumps(conteudo, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def registrar(
        self,
        codigo: str,
        vigencia: str,
        status: str,
        arquivo: str = "",
        observacao: str = "",
    ) -> None:
        novo = not self.csv_path.exists()
        with self.lock, self.csv_path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            if novo:
                writer.writerow(["codigo", "vigencia", "status", "arquivo", "data_hora", "observacao"])
            writer.writerow([
                codigo,
                vigencia,
                status,
                arquivo,
                datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                observacao,
            ])
