# XML eSocial v8.2 — Engine V2

Execute:

```bash
pip install -r requirements.txt
streamlit run app.py
```

Para bases grandes, use **Arquivos/pasta local** em vez do upload pelo navegador.

Fluxo recomendado:

1. Processar os ZIPs principais.
2. Consultar `05_busca_recibos` ou a lista exibida na tela.
3. Baixar apenas os recibos das rubricas sem S-1010.
4. Usar **Complementação opcional com recibos S-1010**.
5. Atualizar o relatório e seguir para o levantamento.

Consulte `ATUALIZACOES_V8_1_ENGINE_V2.md` para os detalhes técnicos.
