from __future__ import annotations

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from leitor_codigos import ler_codigos
from leitor_xml import varrer_pasta_xml
from controle import ControleExecucao
from navegador import AutomacaoESocial


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


class Aplicacao:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("eSocial - Baixador de Rubricas")
        self.root.geometry("760x620")
        self.root.minsize(700, 560)

        self.caminho_lista = tk.StringVar()
        self.caminho_pasta = tk.StringVar()
        self.cnpj = tk.StringVar()
        self.modo = tk.StringVar(value="completo")

        self.codigos: list[str] = []
        self.xml_existentes: dict[str, set[str]] = {}
        self.automacao: AutomacaoESocial | None = None
        self.parar_evento = threading.Event()
        self.fila = queue.Queue()

        self._montar_interface()
        self.root.after(150, self._processar_fila)

    def _montar_interface(self):
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Lista de códigos (TXT, CSV ou Excel)").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.caminho_lista).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(frame, text="Selecionar", command=self._selecionar_lista).grid(row=1, column=1)

        ttk.Label(frame, text="Pasta dos XMLs").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.caminho_pasta).grid(row=3, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(frame, text="Selecionar", command=self._selecionar_pasta).grid(row=3, column=1)

        ttk.Label(frame, text="CNPJ esperado").grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.cnpj).grid(row=5, column=0, sticky="ew", padx=(0, 8))

        modos = ttk.LabelFrame(frame, text="Modo", padding=8)
        modos.grid(row=6, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Radiobutton(
            modos, text="Rápido: ignora o código quando já existe na pasta",
            variable=self.modo, value="rapido"
        ).pack(anchor="w")
        ttk.Radiobutton(
            modos, text="Completo: consulta e baixa apenas vigências ausentes",
            variable=self.modo, value="completo"
        ).pack(anchor="w")

        botoes = ttk.Frame(frame)
        botoes.grid(row=7, column=0, columnspan=2, sticky="ew")
        ttk.Button(botoes, text="Analisar pasta", command=self._analisar).pack(side="left", padx=(0, 6))
        ttk.Button(botoes, text="Conectar ao Chrome", command=self._conectar).pack(side="left", padx=6)
        ttk.Button(botoes, text="Iniciar", command=self._iniciar).pack(side="left", padx=6)
        ttk.Button(botoes, text="Parar", command=self._parar).pack(side="left", padx=6)

        self.resumo = ttk.Label(frame, text="Nenhuma análise executada.")
        self.resumo.grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 6))

        self.progresso = ttk.Progressbar(frame, mode="determinate")
        self.progresso.grid(row=9, column=0, columnspan=2, sticky="ew")

        self.log = tk.Text(frame, height=20, wrap="word")
        self.log.grid(row=10, column=0, columnspan=2, sticky="nsew", pady=(10, 0))

        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(10, weight=1)

    def _selecionar_lista(self):
        caminho = filedialog.askopenfilename(
            filetypes=[
                ("Arquivos suportados", "*.txt *.csv *.xlsx *.xlsm"),
                ("Todos os arquivos", "*.*"),
            ]
        )
        if caminho:
            self.caminho_lista.set(caminho)

    def _selecionar_pasta(self):
        caminho = filedialog.askdirectory()
        if caminho:
            self.caminho_pasta.set(caminho)

    def _log(self, texto: str):
        self.fila.put(("log", texto))

    def _analisar(self):
        try:
            if not self.caminho_lista.get():
                raise ValueError("Selecione a lista de códigos.")
            if not self.caminho_pasta.get():
                raise ValueError("Selecione a pasta dos XMLs.")

            self.codigos = ler_codigos(self.caminho_lista.get())
            self.xml_existentes = varrer_pasta_xml(self.caminho_pasta.get())

            existentes = sum(1 for c in self.codigos if c.upper() in self.xml_existentes)
            faltantes = len(self.codigos) - existentes
            self.resumo.config(
                text=f"Códigos na lista: {len(self.codigos)} | "
                     f"Já encontrados: {existentes} | Faltantes: {faltantes}"
            )
            self._log("Análise concluída.")
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))

    def _conectar(self):
        try:
            if self.automacao:
                self.automacao.fechar()
            self.automacao = AutomacaoESocial(CONFIG_PATH, self._log)
            url = self.automacao.conectar()
            if not self.automacao.validar_cnpj(self.cnpj.get()):
                raise RuntimeError("O CNPJ exibido no portal não corresponde ao CNPJ informado.")
            self._log(f"Conectado ao Chrome. Página: {url}")
            messagebox.showinfo("Conexão", "Chrome conectado com sucesso.")
        except Exception as exc:
            messagebox.showerror("Erro de conexão", str(exc))

    def _iniciar(self):
        if not self.codigos:
            self._analisar()
            if not self.codigos:
                return
        if not self.automacao or not self.automacao.page:
            messagebox.showwarning("Atenção", "Conecte ao Chrome primeiro.")
            return

        self.parar_evento.clear()
        self.progresso["maximum"] = len(self.codigos)
        self.progresso["value"] = 0

        thread = threading.Thread(target=self._executar_downloads, daemon=True)
        thread.start()

    def _parar(self):
        self.parar_evento.set()
        self._log("Solicitação de parada registrada. O programa parará após o código atual.")

    def _executar_downloads(self):
        pasta = Path(self.caminho_pasta.get())
        controle = ControleExecucao(pasta)
        processados = controle.carregar_processados()
        modo_completo = self.modo.get() == "completo"

        try:
            for indice, codigo in enumerate(self.codigos, start=1):
                if self.parar_evento.is_set():
                    break

                chave = codigo.upper()
                vigencias = self.xml_existentes.get(chave, set())

                if self.modo.get() == "rapido" and chave in self.xml_existentes:
                    self._log(f"{codigo}: ignorado, já existe na pasta.")
                    processados.add(chave)
                    controle.salvar_estado(processados, codigo)
                    self.fila.put(("progresso", indice))
                    continue

                if chave in processados:
                    self._log(f"{codigo}: já marcado como processado.")
                    self.fila.put(("progresso", indice))
                    continue

                self._log(f"{codigo}: pesquisando...")
                try:
                    resultados = self.automacao.consultar_e_baixar(
                        codigo=codigo,
                        pasta_destino=pasta,
                        vigencias_locais=vigencias,
                        modo_completo=modo_completo,
                    )
                    for vigencia, status, arquivo in resultados:
                        controle.registrar(codigo, vigencia, status, arquivo)
                        self._log(f"{codigo} | {vigencia or '-'} | {status}")

                    processados.add(chave)
                    controle.salvar_estado(processados, codigo)
                except Exception as exc:
                    controle.registrar(codigo, "", "erro", observacao=str(exc))
                    self._log(f"{codigo}: ERRO - {exc}")

                self.fila.put(("progresso", indice))

            self._log("Execução encerrada.")
            self.fila.put(("fim", None))
        except Exception as exc:
            self._log(f"Falha geral: {exc}")
            self.fila.put(("fim", None))

    def _processar_fila(self):
        try:
            while True:
                tipo, valor = self.fila.get_nowait()
                if tipo == "log":
                    self.log.insert("end", valor + "\n")
                    self.log.see("end")
                elif tipo == "progresso":
                    self.progresso["value"] = valor
                elif tipo == "fim":
                    messagebox.showinfo("Concluído", "Processamento encerrado.")
        except queue.Empty:
            pass
        self.root.after(150, self._processar_fila)


if __name__ == "__main__":
    root = tk.Tk()
    app = Aplicacao(root)
    root.mainloop()
