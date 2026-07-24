# XML eSocial v8.1 — Engine V2

## Núcleo de processamento
- Spool temporário em disco para XMLs extraídos dos ZIPs.
- Extração em blocos, sem carregar cada membro inteiro do ZIP na RAM.
- ZIP principal materializado uma única vez e reutilizado em duas passagens.
- Primeira passagem: inventário, empresa, S-1010 e S-3000.
- Segunda passagem: S-1200, S-5001 e S-5011.
- Leitura de um XML por vez.
- Suporte a ZIP dentro de ZIP, com limite de profundidade e tamanho individual.
- Retorno do caminho do workspace temporário para auditoria técnica.

## Fluxo de recibos
1. Processar o download principal.
2. Gerar relatório preliminar.
3. Exibir somente as rubricas sem S-1010.
4. Baixar os recibos necessários.
5. Inserir ZIPs de recibos por upload ou caminho local.
6. Aplicar recibos e recalcular incidência e levantamento.

O reconhecimento do recibo é feito pelo conteúdo interno `evtTabRubrica`, não pelo nome do arquivo.

## Excel
- Mantida a aba `05_sem_s1010`.
- Adicionada a aba `05_busca_recibos`, consolidada por código/tabela/descrição.
- Mantidos os relatórios e fluxos existentes da v7.6/v8.0.

## Observação de escala
A Engine V2 reduz principalmente o pico de RAM causado pela descompactação e releitura dos ZIPs/XMLs. Os DataFrames analíticos finais ainda ocupam memória proporcional ao número de movimentos, pois a interface e os relatórios atuais dependem deles. Para cargas extremas, use caminhos locais e exportação sem movimentos detalhados.
