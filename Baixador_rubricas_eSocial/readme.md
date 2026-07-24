# Baixador de Rubricas eSocial

Aplicação local em Python, Tkinter e Playwright para auxiliar o download de XMLs S-1010.

## O que esta versão faz

- lê códigos de TXT, CSV ou Excel;
- permite escolher a pasta dos XMLs;
- lê os XMLs já existentes e identifica códigos e vigências;
- conecta ao Chrome já autenticado pelo certificado digital;
- mantém controle em CSV e JSON;
- permite parar e continuar;
- possui modo rápido e modo completo;
- deixa os seletores do portal em `config.json`, porque o eSocial pode mudar a estrutura da página.

## Instalação

Abra o terminal do VS Code dentro desta pasta:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Uso

1. Execute `iniciar_chrome.bat`.
2. No Chrome aberto, entre no eSocial usando o certificado.
3. Informe o CNPJ e navegue até **Tabelas > Rubricas**.
4. Execute:

```bash
python app.py
```

5. Selecione a lista de códigos.
6. Selecione a pasta que já contém os XMLs.
7. Clique em **Analisar pasta**.
8. Clique em **Conectar ao Chrome**.
9. Clique em **Iniciar**.

## Lista de códigos

TXT:

```text
599FOLH
604FOLH
608PF13
```

CSV ou Excel:

- a primeira coluna não vazia é usada;
- cabeçalhos como `codigo`, `codRubr`, `rubrica` são reconhecidos.

## Configuração dos seletores

Preencha em `config.json`:

```json
{
  "seletores": {
    "campo_codigo_rubrica": "SELETOR",
    "botao_pesquisar": "SELETOR",
    "linhas_resultado": "SELETOR",
    "botao_download_na_linha": "SELETOR",
    "texto_cnpj_ou_empregador": "SELETOR"
  }
}
```

Os seletores precisam ser ajustados para a tela real do eSocial. A aplicação não armazena certificado ou PIN.
