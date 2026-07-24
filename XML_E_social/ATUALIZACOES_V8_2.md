# Atualizações V8.2 — Engine V2

## Nova experiência de entrada

- Entradas separadas para **Arquivos principais** e **Complementação opcional — Recibos S-1010**.
- Um único botão **Gerar Relatório**.
- Sem recibos: gera o relatório preliminar normalmente.
- Com recibos: incorpora automaticamente os eventos S-1010 antes de montar o relatório e o levantamento.

## Conferência dos recibos

Após o processamento, o aplicativo informa:

- quantidade total de XMLs localizados nos arquivos enviados como recibos;
- quantidade de recibos S-1010 reconhecidos;
- quantidade de outros eventos ignorados na complementação.

## Compatibilidade de entrada

- Upload de ZIP e XML individual.
- Caminho local de ZIP, XML ou pasta, com pesquisa recursiva.
- Mantidos spool temporário em disco, duas passagens e leitura de um XML por vez.

## Fluxo recomendado

1. Gere o relatório usando somente os arquivos principais.
2. Consulte as abas `05_sem_s1010` e `05_busca_recibos`.
3. Baixe somente os recibos necessários.
4. Reabra o aplicativo, informe novamente os arquivos principais e adicione os recibos na área opcional.
5. Clique em **Gerar Relatório**.
