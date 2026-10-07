# Conciliação de Salário-Família

Aplicação Streamlit independente para:

1. extrair salário-família de Declarações Completas da DCTFWeb em PDF/ZIP;
2. gerar um Excel consolidado;
3. comparar os valores com levantamentos MANAD, XML/eSocial ou planilhas padronizadas.

## Execução local

```powershell
python -m pip install -r requirements.txt
streamlit run app.py
```

Os uploads são processados em memória e não são persistidos pela aplicação.

## Modelos de levantamento aceitos

- MANAD: reconhecimento das abas `K300_FILTRADO` e `K150_SELECIONADAS`. A seleção de salário-família usa o cadastro de rubricas; os valores de `VLR_RUBR` e as competências `MMAAAA` são normalizados. Linhas repetidas são sinalizadas e preservadas.
- XML/eSocial: reconhecimento das abas `00_empresa` e `03_movimentos`. Usa `dsc_rubr`, `vr_rubr`, `per_apur` e o CNPJ completo de `nr_insc_estab`. A interface solicita a conferência da correspondência entre estabelecimento e DCTFWeb. Períodos anuais e inscrições incompatíveis nas linhas selecionadas impedem a comparação automática.
- Outras planilhas XLSX/CSV continuam disponíveis pelo mapeamento manual. Também é possível desativar a leitura automática dos modelos reconhecidos.

As abas de resumo não são somadas ao detalhe. Uma exportação sem salário-família não é tratada como zero. O comparativo dos modelos reconhecidos inclui uma aba de detalhe para rastreabilidade. Valores de períodos anteriores usam `per_apur`, preservando `per_ref` no detalhe para conferência.

As competências mensais são exibidas em `MM/AAAA` e ordenadas por ano e mês, em cada CNPJ, tanto na extração como na comparação. Para obter essa ordenação em arquivos antigos, gere novamente o Excel pela aplicação.

## Testes

```powershell
python -m unittest discover -s tests -v
```
