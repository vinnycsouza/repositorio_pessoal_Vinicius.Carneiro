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
