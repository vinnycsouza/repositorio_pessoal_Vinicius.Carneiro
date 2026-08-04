# Plano de carga incremental de Workspace

## Diagnóstico do schema atual

- `fontes` materializa ZIP/XML e mantém checkpoint por membro (`ultimo_indice`).
- `eventos` cataloga cada XML e guarda o conteúdo comprimido para os eventos da segunda passagem.
- `objetos` persiste os resultados do parser por evento.
- `dados_*` materializa os objetos em tabelas relacionais.
- `rel_*` é reconstruído a partir das tabelas `dados_*`, reaplicando S-3000 e as regras existentes.
- A deduplicação atual usa somente `UNIQUE(arquivo)` e não protege contra o mesmo XML com outro nome.

## Arquivos previstos

- `modules/processador_zip.py`: migração do schema, SHA-256, histórico, checkpoints e API incremental.
- `modules/sqlite_relatorio.py`: reconstrução controlada das tabelas analíticas quando um novo S-1010 exigir reclassificar movimentos anteriores.
- `modules/workspace_manager.py`: período, quantidade de XMLs e histórico resumido do Workspace.
- `app.py`: ação adicional “Adicionar complementos ao Workspace”.
- `tests/test_carga_incremental.py`: cenários de carga nova, duplicidade, retomada, S-3000, S-1010 e relatórios.
- `README.md`: documentação do fluxo.

## Novas tabelas, colunas e índices

- `eventos.hash_conteudo`: SHA-256 do XML bruto.
- índice único parcial `ux_eventos_hash_conteudo` para hashes não vazios.
- `fontes.id_carga`: vínculo da fonte com a carga incremental.
- `historico_cargas`: início/fim, origem, assinatura, contadores, período, status e erro.
- metadados em `meta`: última atualização/consolidação, total de cargas/XMLs e contagens por tipo/período.

A migração será idempotente. Workspaces antigos serão aceitos. Hashes serão retropreenchidos quando o XML bruto estiver disponível no SQLite; eventos legados sem conteúdo bruto continuarão protegidos pelo nome lógico, enquanto todos os XMLs novos terão SHA-256 obrigatório.

## Deduplicação

1. Calcular SHA-256 em streaming/conteúdo bruto antes do parser.
2. Consultar/inserir por `hash_conteudo`, protegido também por índice único.
3. Só incrementar inventário e contagem quando a inserção for efetiva.
4. Registrar separadamente recebidos, novos, duplicados e erros.

## Transação e consistência

A ingestão bruta usa checkpoints em lotes para permitir retomada. Durante uma carga, as tabelas `rel_*` concluídas anteriormente permanecem disponíveis e coerentes. A nova versão só fica visível aos relatórios depois da segunda passagem e da reconsolidação completa. Em falha, a carga fica `interrompida`; os eventos brutos já confirmados são mantidos como checkpoint, sem substituir as consolidações válidas anteriores.

Essa estratégia oferece atomicidade lógica do relatório e retomada real, sem exigir uma transação SQLite aberta por horas ou dias.

## Retomada

- Uma carga `processando/interrompida` mantém `id_carga`, fontes e `ultimo_indice`.
- A retomada usa o mesmo Workspace e a mesma carga, sem rematerializar fontes.
- Eventos confirmados são ignorados pelo SHA-256.
- O histórico é concluído somente após a consolidação.

## Reprocessamento derivado

- XMLs antigos não são relidos dos arquivos originais.
- Se houver novo S-1010, os eventos S-1200 persistidos em `eventos.xml_zlib` serão reclassificados a partir do SQLite para aplicar vigências novas à base completa.
- S-3000 é reaplicado ao recriar `rel_movimentos_cp` e os resumos a partir das tabelas consolidadas.
- S-5001/S-5011 novos passam somente pelo parser incremental.
- As regras tributárias, classificação CP, parser e layouts existentes permanecem inalterados.

## Impacto em relatório e levantamento

Ambos continuam lendo o mesmo `processamento.db`. Ao concluir a carga, os caches da interface são invalidados pela alteração física do banco e os dados novos passam a ser usados automaticamente. ZIP/Excel, criação de Workspace, retomada anterior e exportações continuam compatíveis.

## Testes de aceite

- carga inicial sem regressão;
- complemento somente novo;
- complemento misto e XML igual com nome diferente;
- interrupção e retomada no mesmo `id_carga`;
- S-3000 excluindo evento anterior;
- S-1010 novo reclassificando S-1200 anterior;
- geração de relatório e levantamento após atualização;
- confirmação de que nenhum segundo Workspace foi criado.
