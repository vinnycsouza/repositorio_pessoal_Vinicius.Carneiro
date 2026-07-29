# V9.0 — Engine V3

- Estrutura funcional da V8.4 preservada.
- Um único `modules/processador_zip.py`.
- SQLite integrado pelo módulo padrão `sqlite3` do Python.
- Workspace persistente em `%LOCALAPPDATA%\XML_eSocial\workspaces` no Windows.
- Checkpoint transacional no arquivo `processamento.db`.
- Retomada automática ao selecionar novamente as mesmas fontes e clicar em **Gerar Relatório**.
- A primeira passagem cataloga todos os XMLs e guarda no banco apenas o XML compactado dos eventos necessários à segunda passagem: S-1200, S-5001 e S-5011.
- S-1010 e S-3000 são tratados durante a ingestão.
- ZIPs aninhados continuam suportados.
- Não existe pasta `test` nem arquivo duplicado de backup nesta entrega.

## Como retomar

Depois de uma interrupção, abra o aplicativo, informe os mesmos caminhos/arquivos e clique em **Gerar Relatório**. A assinatura das fontes localiza o workspace interrompido e continua do último lote confirmado.

