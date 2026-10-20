# Especificação — dashboard

## Rota, acesso e posição

- `/dashboard` é privado, nível 1 e raiz da área autenticada. Sem sessão válida a requisição volta à entrada.
- Exibe nome/e-mail do usuário da sessão e ação para encerrar sessão.
- Navega para as páginas nível 2: **Choose a path** (`/decision`), **My contacts** (`/contacts`) e **Location map** (`/map`). Não mostra links de páginas privadas antes da autenticação.

## Indicador de compartilhamento

- O dashboard apresenta um indicador acessível atualizado pelo script global `location-sharing.js`.
- Estados: compartilhamento ativo com número de destinatários, permissões existentes mas atualizações pausadas, sem compartilhamento ativo, ou estado indisponível.
- O indicador informa estado de consentimento/opt-in, não confirma sozinho que uma leitura recente de GPS teve sucesso.

## Arquivos relacionados

`app/main/routes.py` (`dashboard`), `app/templates/dashboard.html`, `app/templates/base.html`, `app/static/location-sharing.js`.
