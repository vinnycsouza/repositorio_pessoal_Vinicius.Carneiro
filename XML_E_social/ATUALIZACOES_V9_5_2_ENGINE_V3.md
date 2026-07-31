# V9.5.2 - Gerenciamento do Workspace Atual

## Interface

- O botão `Limpar temporários antigos` foi removido da interface.
- O novo botão `Gerenciar Workspace Atual` atua exclusivamente sobre o
  Workspace carregado na sessão.
- O painel informa empresa, CNPJ, nome, caminho, status, tamanho total e tamanho
  do `processamento.db`.

## Ações

- `Abrir Workspace` abre a pasta no Explorador de Arquivos do Windows.
- `Enviar Workspace para a Lixeira` exige confirmação com identificação da
  empresa e espaço ocupado.
- A remoção usa `send2trash`; não há exclusão definitiva nessa funcionalidade.
- Um Workspace identificado como em processamento não pode ser enviado para a
  Lixeira pela interface.

## Compatibilidade

As operações de sistema foram isoladas em `modules/workspace_manager.py`. A
abertura usa o Explorador no Windows e mantém alternativas para macOS e Linux.

Não foram alterados processamento, criação de Workspace, SQLite, parser,
classificação tributária ou exportações.
