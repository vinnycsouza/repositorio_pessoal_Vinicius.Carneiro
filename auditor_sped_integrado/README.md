# Auditor SPED integrado — versão inicial

Projeto local para organizar análises de possíveis recuperações tributárias com trilha de evidências. Reaproveita o formato dos Excel C170 usado em `projeto_icms_piscofins` e substitui o cruzamento por chave da nota por **chave da NF-e + item**, com bloqueio de pares ambíguos.

## Entradas

- Excel `.xlsx` ou `.xlsm` do Sysconv para EFD ICMS/IPI, EFD-Contribuições, ECD e ECF: hash SHA-256 e contagem de linhas por aba;
- Abas C170 dos Excel de EFD ICMS/IPI e EFD-Contribuições: triagem fiscal em nível de item.

Os quatro Excel são selecionados pelo navegador e processados em memória. A triagem usa as abas C170 dos dois primeiros. ECD e ECF ainda não têm interpretação contábil automática nesta versão. A contagem do inventário considera a primeira linha preenchida de cada aba como cabeçalho.

## Saídas e segurança jurídica

- Indício de possível ICMS próprio não excluído da base de PIS/COFINS (Tema 69);
- Item com ICMS-ST sinalizado para verificar a situação do substituído e o Tema 1125;
- Conciliação ambígua quando há mais de uma linha para a mesma NF-e e item;
- Hashes e linhas das planilhas de origem; decisão e justificativa do analista exportáveis em CSV;
- Catálogo de hipóteses futuras com fontes oficiais e tratamento ainda pendente.

Nenhuma linha é declarada crédito validado pelo motor. Base de ICMS igual à base de PIS/COFINS é apenas um **sinal de revisão**: a base de ICMS não é necessariamente a receita tributável. É obrigatório confrontar documentos, apuração e valores pagos, além de verificar período, condição do contribuinte e uso prévio do crédito. O catálogo foi pesquisado em 21/10/2026 e deve ser versionado quando as regras mudarem.

O modelo de `sped_credito_app/calculos.py` não foi incorporado como cálculo de crédito porque subtrai ICMS-ST/DIFAL e estima PIS/COFINS por dentro sem verificar, por operação, o direito, a apuração nem o pagamento. Ele permanece referência para futuros cenários, sujeitos a validação jurídica.

## Executar

```powershell
python -m pip install -r auditor_sped_integrado/requirements.txt
streamlit run auditor_sped_integrado/app.py
```

Não coloque planilhas de clientes ou relatórios com dados fiscais sob controle de versão. A aplicação recebe arquivos pelo navegador, processa-os localmente em memória, não os envia para serviços externos e só exporta resultados quando o usuário aciona o botão de download.

## Próximas integrações

1. Mapeamento versionado por ano das abas e colunas geradas pelo Sysconv para as quatro escriturações.
2. Conciliação EFD-Contribuições × EFD ICMS/IPI × ECD × ECF e apurações declaradas.
3. Pacotes de regras separados para União e cada UF, com vigência, precedentes, exceções e testes de regressão.
4. Cálculo condicionado à evidência de recolhimento e à inexistência de aproveitamento anterior.

Fontes: [jurisprudência vinculante RFB](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/legislacao/jurisprudencia-vinculante/pis-cofins), [LC 87/1996](https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp87.htm), [orientações RFB sobre créditos de PIS/COFINS](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/conformidade-tributaria/Creditos-Indevidos-de-PIS-Pasep-Cofins-Setor-Supermercadista), [IPI](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/creditos/ipi/conceito%20e%20prazos) e [IRPJ/CSLL](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/creditos/sneg).

