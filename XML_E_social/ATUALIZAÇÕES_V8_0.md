# Atualizações — v8.0

## Processamento de arquivos grandes

- Processamento dos ZIPs em duas passagens.
- A primeira passagem cria inventário, lê empresa, S-1010 e S-3000.
- A segunda passagem lê S-1200, S-5001 e S-5011 usando o catálogo completo de rubricas.
- As árvores XML deixam de ser acumuladas em memória.
- Os ZIPs são processados separadamente, sem criar um novo ZIP agregado em RAM.
- Suporte a caminho local de arquivo ou pasta, recomendado para pacotes de vários GB.
- Pastas locais são pesquisadas recursivamente por arquivos ZIP.
- ZIP dentro de ZIP continua suportado.

## Recibos de rubricas

- `retornoEventoCompleto` com `evtTabRubrica` é reconhecido como S-1010.
- S-1010 proveniente de recibo entra automaticamente no catálogo de rubricas.
- A origem fica registrada nas colunas `fonte_dados` e `arquivo_origem`.
- Movimentos S-1200 passam a registrar `fonte_s1010` e `arquivo_s1010`.
- Em caso de empate entre registros equivalentes, o S-1010 do download principal tem prioridade sobre o recibo.
- O recibo continua servindo para preencher lacunas e ampliar o histórico de vigências.

## Segurança e estabilidade

- Limite de profundidade para ZIP aninhado.
- Proteção para XML individual excessivamente grande.
- XML vazio ou inválido é registrado na aba de erros.
- Compatibilidade mantida com o fluxo de Excel consolidado.

## Observação importante

A v8.0 reduz fortemente o consumo causado pelo acúmulo de XMLs e pela criação de um ZIP agregado. Entretanto, as tabelas analíticas finais ainda são montadas em DataFrames para manter compatibilidade com o relatório atual. Para bases extremas, prefira o modo de caminho local e desative exportações detalhadas quando não forem necessárias.
