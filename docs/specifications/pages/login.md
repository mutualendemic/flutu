# Especificação — entrada e autenticação

## Rotas e estado

- `/` encaminha usuários com sessão para `/dashboard`; sem sessão, encaminha para `/auth/login`.
- `/auth/login` mostra a página pública com acesso Google quando as credenciais estão configuradas; sem configuração, exibe a mensagem e retorna 503.
- `/auth/google/login` inicia OAuth com state ligado à sessão. `/auth/google/callback` e `/auth/callback` processam o retorno; state ausente/divergente, erro Google, código ausente ou falha de validação retorna à tela de login sem autenticar.
- A identidade é validada com userinfo do Google. No sucesso, o callback substitui a sessão, marca-a permanente e guarda `sub`, e-mail normalizado, nome e foto. Com MongoDB configurado, também atualiza o perfil do usuário para a funcionalidade de compartilhamento.
- `/auth/logout` limpa a sessão e retorna ao login.

## Interface e acesso

- Login é público. Não há login por senha nem usuário local fixo.
- O link GitHub na interface aponta para `https://github.com/mutualendemic/flutu`, abre em nova aba e usa `rel="noopener noreferrer"`.
- Rotas privadas são protegidas no servidor pelo decorador `login_required`; ver a especificação transversal de [arquitetura](../architecture.md).

## Arquivos relacionados

`app/auth/routes.py`, `app/auth/decorators.py`, `app/services/google_oauth.py`, `app/templates/login.html`, `app/__init__.py`.
