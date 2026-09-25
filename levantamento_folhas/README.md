# Levantamento de folhas — piloto Streamlit

Aplicativo local para resumos RH3. Relatórios gerados exclusivamente em Excel; os PDFs originais podem ser visualizados/baixados para conferência.

## Iniciar no Windows

Python 3.11 ou superior e o comando `tar` com suporte a RAR (incluído nas versões recentes do Windows).
Abra esta pasta no VS Code. Em um terminal:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Também é possível executar `iniciar.bat`. A instalação inicial requer internet. Não publique este aplicativo na internet sem adicionar autenticação e revisar limites de arquivos.

## Teste inicial

1. Crie uma análise e importe um PDF RH3 ou os ZIPs/RARs.
2. Na etapa 2, informe o caminho local do relatório XLSX de incidência. Para arquivos grandes, prefira caminho local ao upload.
3. Confira o cadastro por competência. O catálogo AJ não é aplicado à Adserv. A seleção inicial de códigos é apenas uma conveniência; revise-a. Nenhum rating é atribuído automaticamente.
4. Revise efeitos, bases e ratings com responsável e justificativa. Revisões têm escopo da empresa/competência/tipo/código/descrição/lado.
5. Consulte a conferência aritmética e a comparação das bases. Sugestões e pendências permanecem identificadas.
6. Prepare e baixe o Excel na etapa 4.

## Limites explícitos do piloto

- Não calcula crédito, juros, desoneração ou elegibilidade jurídica.
- Somente incidências comuns 00/11/12 com correspondência exata recebem sugestão; casos específicos e históricos ambíguos requerem revisão.
- O importador preserva registros S-1010, mas não resolve automaticamente retificações/exclusões ou conflitos de versões.
- Cadastramento manual do rating; o modelo final do cliente não é importado automaticamente nesta versão.
- Complementares e versões repetidas exigem revisão antes de consolidar. Remova da análise os documentos que não devem ser somados.
- Toda exportação é preliminar. Valores selecionados não são automaticamente valores de exclusão confirmada.
- Documentos sem total reconhecido ou com diferença devem ser revisados, mesmo quando há rubricas extraídas.
- O relatório de incidência não substitui a conferência do processamento original dos XMLs.

## Dados e portabilidade

Banco SQLite e PDFs preservados em `dados/`. Faça backup dessa pasta. Análises anteriores são carregadas pela barra lateral; cada salvamento registra histórico. Nenhum documento é enviado a um serviço externo. Arquivos de dependências e dados locais não devem ser incluídos em controle de versão.

## Testes

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```


## Fluxo simplificado — versão 0.3

- **Documentos e incidência:** importar folhas e cadastro S-1010.
- **Base do INSS empresa:** selecionar empresa, competência e folha. Ver base mensal/13º e os quatro totais previdenciários. A triagem separa possíveis acréscimos, reduções, fora da base segundo cadastro e não determinado.
- **Relatórios Excel:** cruzamento completo por folha, grupos separados, valores selecionados, resumos previdenciários e conferências.

Nenhuma rubrica é selecionada automaticamente pela lista de interesse. Selecionar uma linha não muda sua incidência nem seu grupo. Revisões manuais anteriores são preservadas. Novas seleções são salvas por documento. A reconstrução da base, o ajuste de correspondência/rating e a informação de desoneração são opcionais. Não há cálculo da alíquota de 20%.

Campos fora da vigência mostram a descrição e o código encontrados apenas como referência e permanecem não determinados. Descrições divergentes e versões ambíguas não são aceitas automaticamente. A apresentação dos valores na tela usa R$ 2.530.716,30; o Excel guarda números com formato monetário e separadores conforme a configuração regional do Excel.


## Projeção histórica — versão 0.4

A área Participação indicada pelo relatório de incidência agora projeta possíveis efeitos mesmo sem vigência contemporânea, quando empresa, código e descrição coincidem e o histórico disponível concorda quanto a tabela, tipo e incidência. Usa a referência temporal mais próxima e a identifica como Projeção pelo cadastro disponível. Não comprova o tratamento histórico.

Cadastros conflitantes e descrições divergentes não recebem efeito automático. Descrições semelhantes com códigos diferentes geram apenas sugestões de correspondência. Maternidade e códigos técnicos continuam com tratamento específico. A seleção não é necessária para ver a triagem e não altera a projeção. Referência, vigência e fonte são exportadas no Excel. As indicações de fora do período desta versão substituem o comportamento anterior que deixava todo o histórico antigo como não determinado.

### Versão 0.5.0 — grupos da base empresa
A consulta preserva a navegação e apresenta, por mensal e 13º, as bases vinculadas à alíquota expressa de 20%, à contribuição zerada, a outra alíquota e a linhas sem correspondência suficiente. O vínculo entre base e contribuição usa a mesma linha física do PDF. Quantidade é transcrita da coluna Qtd. da base, sem somar como pessoas únicas nem vincular rubricas a trabalhadores. Não se infere desoneração ou pagamento.

A conferência das rubricas continua comparando a projeção com a base total; as bases dos grupos são referências auxiliares. Os relatórios Excel incluem Grupos base empresa e Referencias base empresa, com origem, página, valores numéricos e quantidades. Documentos salvos são enriquecidos a partir dos PDFs preservados, sem alterar seleções ou decisões. Grupos não localizados permanecem sem valor, distintos de zero.


### Versão 0.6.0 — composição provável e validação dos grupos
A atualização mantém as abas e os quatro grupos de participação. Uniformiza espaços na comparação, preservando códigos, descrições originais e chaves das revisões. Variações de descrição só permitem projeção quando uma descrição corresponde à folha, há uma única tabela e todos os registros candidatos concordam em incidência e tipo. Divergências reais continuam pendentes. Códigos 31/32 (e 00 concorrente), com identidade e tipo de desconto compatíveis, ficam identificados como contribuição do segurado, fora da composição patronal.

Não há mais atribuição mensal automática quando a base é desconhecida. A consulta permite filtrar mensal, 13º, não determinada e não se aplica. O panorama compara a situação dos grupos entre competências do mesmo tipo no recorte consultado.

A conferência da composição detalha acréscimos, reduções, parcela explicada e saldo em relação à base total do PDF. Candidatas conflitantes ficam fora da parcela explicada: somente códigos 11/12 versus 00 com identidade, tabela e tipo compatíveis geram cenário separado. O cenário soma todas as candidatas daquela base, sem buscar subconjuntos que fechem o total. Fechamento condicionado não confirma incidência nem exclusão. Coincidência de valor e quantidade entre rubrica com indicação de acréscimo e grupo de 20% aparece apenas como indício.

Bases e contribuições são conferidas sem reordenar linhas: quantidades divergentes ou diferença acima de um centavo por quantidade suspendem os totais de distribuição daquele bloco mensal/13º. Esse limite é apenas triagem aritmética, não regra fiscal ou prova de arredondamento. Os valores originais permanecem no detalhamento; diferenças pequenas recebem ressalva. Validar a coerência da linha não identifica trabalhadores nem comprova recolhimento.

Esses cálculos são derivados em consulta, inclusive para análises antigas, sem reimportar PDFs ou alterar seleções. Excel inclui Memoria composicao, Indicios por quantidade e Panorama das bases, além de validações dos grupos. Nenhum relatório adicional é gerado automaticamente.


### Versão 0.7.0 — participação na base dos 20%
Bloco independente dentro de Participação indicada pelo relatório de incidência, com mensal/13º, base de referência, parcela projetada ou hipótese e saldo não identificado. Quando todo o bloco coerente pertence às linhas de 20%, utiliza a projeção assinada do cadastro. Nos grupos mistos não distribui valores integrais nem faz rateio: apresenta indícios de igualdade de valor e quantidade. Somente um indício único para um único grupo de 20%, cobrindo exatamente sua base, entra em hipótese expressamente condicionada. Indícios concorrentes não são somados. Referências inconsistentes e ausentes ficam indisponíveis; linhas sem base positiva dos 20% não recebem projeção. O Excel inclui Composicao dos 20 e Rubricas dos 20. Seleções manuais não comprovam atribuição a grupos.


### Versão 0.7.1 — candidatas com conflito no bloco dos 20%
Quando toda a base coerente do bloco corresponde às linhas de 20%, a consulta mostra candidatas conflitantes em cenário separado: seu valor não entra na parcela projetada, e o saldo condicionado considera todas as candidatas. Fechamento não confirma incidência nem altera seleção. Em grupos mistos não se atribui a candidata integralmente aos 20%. Mensagens distinguem referência suspensa, base não localizada, contribuição zerada, distribuição não identificada e falta de correspondência. Campos também seguem para o Excel.


### Versão 0.9.0 — Excel acompanha Base INSS empresa
O relatório principal começa com uma linha por PDF e segue para composição dos 20%, rubricas de suporte e simulação proporcional independente. Cruzamento por folha contém os quatro grupos com filtros, sem depender de seleção. Selecionadas preserva grupo, rating, base e justificativa e oferece observação livre no Excel. Conferências e origem completam a análise. Os consolidados e abas técnicas anteriores são opcionais.

Cabeçalhos legíveis, tabelas Excel, colunas identificadoras congeladas, valores numéricos e IDs de documento permitem aprofundar a análise sem perder a origem. A prévia da exportação mostra o recorte próprio do relatório. Critérios registra empresas, competências, tipos, filtro, versão e links internos. O arquivo é um retrato da análise, sem recálculo nem importação de revisões feitas no Excel. Nenhuma classificação, seleção ou análise salva é modificada pela exportação.


### Versão 0.10.0 — relatório simples por competência
O download passa a ter somente Composição dos 20% e Composição da base total. Consolidado e Por competência usam o mesmo layout em blocos cronológicos por empresa, documento, tipo de folha e mensal/13º. Bases, rubricas, critérios e diferenças ficam juntos. Hipóteses, candidatas e estimativas independentes têm seções separadas. Totais previdenciários aparecem uma vez por documento na aba de apoio; pendências sem atribuição ficam fora das somas. O relatório respeita o filtro previdenciário e os filtros próprios de exportação, sem alterar análises salvas.


### Versão 0.10.1 — cadastro sem 00_empresa
A identificação pode vir de 00_empresa ou da coluna cnpj_empregador das rubricas. Quando ausente, o usuário informa explicitamente o CNPJ ou raiz no formulário. O vínculo manual fica registrado e aparece no relatório simples. Não se deduz empresa pelo nome do arquivo ou pela folha aberta. Empresas conflitantes são rejeitadas e o bloqueio de cruzamento com outro CNPJ é preservado.


### Versão 0.10.2 — abas divididas e arquivos grandes
Reconhece todas as partes numeradas de 00_empresa, apoio_s1010 e 02_rubricas_cp. Valida a raiz de todos os registros de identificação, incluindo conflitos nas últimas partes. Prioriza o histórico apoio_s1010 sobre o resumo 02_rubricas_cp. A leitura seletiva do XLSX não carrega movimentos nem todos os textos compartilhados em memória. Mantém suporte a arquivos sem identificação mediante vínculo manual explícito.


### Versão 0.11.0 — simulação independente
Simulação proporcional passa a uma terceira aba. A composição dos 20% mantém apenas as hipóteses e evidências, com reduções e candidatas em seções próprias. A simulação continua disponível para grupos mistos válidos; quando existe indício específico por valor e quantidade, a aba explica que o rateio é uma alternativa. Não muda os cálculos nem as decisões. Cabeçalhos monetários identificam hipótese, estimativa ou candidata, e o período do recorte fica compacto. Consolidado e competência individual usam os mesmos blocos.
