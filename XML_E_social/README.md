# Composição da Incidência CP — eSocial v8.0

Aplicativo Streamlit para leitura e cruzamento de eventos do eSocial.

## Principais módulos

- Relatório de Incidência CP
- Levantamento de Verbas

## Entradas

- Upload de um ou mais ZIPs pelo navegador
- Arquivos ou pasta local, recomendado para arquivos grandes
- Excel consolidado no módulo de levantamento

## Eventos principais

- S-1010
- S-1200
- S-5001
- S-5011
- S-3000

Recibos `retornoEventoCompleto` que contenham `evtTabRubrica` são utilizados como fonte complementar de S-1010.

## Execução

```bash
pip install -r requirements.txt
streamlit run app.py
```

Consulte `ATUALIZACOES_V8_0.md` para detalhes técnicos e regras de prioridade.
