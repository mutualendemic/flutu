# Arquitetura — decisões atuais

Esta especificação descreve as decisões compartilhadas entre páginas e APIs, conforme a implementação existente.

## Aplicação e organização

- Flask usa a factory `create_app()` em `app/__init__.py`. A entrada de desenvolvimento é `run.py`; configuração baseada em ambiente fica em `app/config.py`.
- Autenticação/OAuth está no Blueprint `auth`; páginas gerais e APIs estão no Blueprint `main`. Templates Jinja ficam em `app/templates/`, CSS/JavaScript/imagens em `app/static/`, e integrações/regra de negócio em `app/services/`.
- O servidor local usa `127.0.0.1:8000`. O container de produção usa Gunicorn em `0.0.0.0` e a porta definida em `PORT`; o comportamento local não deve ser exposto à rede sem requisito explícito.
- Vercel publica a aplicação pelo adaptador `api/index.py` e `vercel.json`.
- A versão apresentada no login usa o SHA do build injetado no ambiente (`FLUTU_BUILD_COMMIT`, `VERCEL_GIT_COMMIT_SHA`, `GITHUB_SHA`, `SOURCE_VERSION`), truncado em 12 caracteres; sem SHA de build, a configuração tenta obter o commit Git local e usa `unknown` se não conseguir.

## Sessão e identidade

- Google OAuth é o único método de login. O OAuth usa `state` aleatório armazenado na sessão e valida a identidade pelo userinfo confiável do Google. Não existe cadastro local por senha.
- O cookie de sessão Flask é assinado pelo `SECRET_KEY`/`FLASK_SECRET_KEY`, marcado HttpOnly e SameSite=Lax, com validade permanente de sete dias; `FLASK_SESSION_COOKIE_SECURE=true` deve ser usado com HTTPS.
- A sessão contém os dados do usuário, incluindo `sub` estável do Google, e-mail em minúsculas, nome e foto. Operações persistentes usam o `sub` para escopo/identidade; nunca confiar em ID de proprietário enviado pelo navegador.
- Não é mantido registro de visitas anônimas. Um perfil na coleção MongoDB `users` é atualizado após autenticação quando MongoDB está configurado; falha nessa indexação é registrada e não impede o login.
- `login_required` protege no servidor: páginas HTML sem sessão redirecionam para `/` (que encaminha ao login); `/api/*` retorna JSON 401. Controles de interface não substituem a proteção de rotas.

## Configuração e integrações

- Variáveis principais: `FLUTU_GOOGLE_CLIENT_ID`, `FLUTU_GOOGLE_CLIENT_SECRET`, `FLUTU_GOOGLE_REDIRECT_URI`, `FLASK_SECRET_KEY`, `FLASK_SESSION_COOKIE_SECURE`, `MONGODB_URI`, `MONGODB_DATABASE` e, em ambientes sem configuração DNS do sistema, `MONGODB_DNS_NAMESERVERS`. Há aliases padrão do Google/Vercel para credenciais/URI/segredo.
- Callback de desenvolvimento: `http://127.0.0.1:8000/auth/google/callback`. O callback público deve ser HTTPS e ter a mesma URL autorizada no Google; a mesma configuração é usada em autorização e troca do código OAuth.
- MongoDB é acessado sob demanda por `app/services/mongodb.py`; configuração ausente causa indisponibilidade explícita das funções que precisam de banco. Coleções atuais: `contacts`, `users`, `location_shares`, `locations`.
- O serviço de decisão consulta o gerador de permutações quânticas da ANU em cada pedido. A aplicação não persiste o resultado.
- Mapas usam Leaflet carregado do CDN unpkg e tiles do serviço público OpenStreetMap. A página identifica a atribuição de copyright; respeitar a política de uso dos tiles. Geolocalização do navegador exige contexto seguro (HTTPS, exceto localhost).

## Dados pessoais e localização

- Contatos têm `owner_id` igual ao `sub` Google, nome, telefone, e-mail e data de criação. Endpoints sempre escopam operações ao proprietário autenticado.
- No login, o diretório `users` é atualizado por `sub` e contém email normalizado e nome para resolver solicitações de compartilhamento. A busca de conta é por e-mail, mas a identidade/persistência é pelo `sub` Google.
- Cada relação de compartilhamento em `location_shares` liga requester a recipient com estados `pending`, `accepted`, `declined`, `cancelled` ou `revoked`. Só o destinatário aceita/recusa e só o remetente cancela pendências. Aceitar adiciona o solicitante à lista de contatos do destinatário, se ainda não estiver presente.
- O destinatário concede consentimento em cada solicitação. O proprietário da localização também precisa habilitar explicitamente atualizações e permitir geolocalização no browser. O opt-in fica em `users.location_sharing_enabled` e pode ser pausado na página de mapa.
- Uma localização é um ponto GeoJSON e precisão em um documento por usuário, upsert por `owner_id` único. Atualizações são feitas a cada ~30 segundos enquanto qualquer página autenticada está visível. Um estado de aba oculta pausa o envio; ao retornar ao primeiro plano a localização é solicitada imediatamente.
- Exclusivamente na página `/map`, o navegador também lê a posição a cada ~30 segundos para desenhar um marcador azul local do dispositivo, iniciando ao abrir a página. Sem opt-in, essas coordenadas existem apenas na memória/página do navegador: não são enviadas à API nem persistidas. Com opt-in ativo, o marcador usa o ponto recente retornado pelo servidor.
- Ao ativar o compartilhamento no mapa, a geolocalização é solicitada diretamente no clique do usuário antes de salvar o opt-in, permitindo ao browser apresentar a solicitação de permissão. Erros de permissão negada, GPS indisponível/timeout e falta de HTTPS são apresentados na interface. O indicador global mostra falhas recentes de obtenção/envio da localização.
- Apenas solicitantes com compartilhamento `accepted` veem um ponto. O proprietário autenticado também pode ver seu próprio ponto recente enquanto o opt-in estiver ligado. Localizações sem atualização há pelo menos 120 segundos não são incluídas na API; índice TTL remove documentos após 180 segundos de inatividade. Pausar opt-in ou revogar a última autorização remove o documento imediatamente. Revogar um dos vários compartilhamentos mantém a localização disponível aos demais autorizados.
- Localizações não são histórico/trilha. O comportamento é best-effort no navegador; geolocalização pode ser recusada/indisponível e páginas fechadas não enviam atualizações.

## Navegação, erros e documentação

- `/dashboard` é nível 1. Páginas linkadas nele são nível 2 e voltam ao dashboard. A página informativa é nível 3 e volta à decisão que a abriu.
- APIs protegidas retornam códigos HTTP apropriados e mensagens JSON; indisponibilidade MongoDB é reportada como 503. APIs de localização validam coordenadas no servidor e não aceitam identidade de usuário fornecida pelo cliente.
- Cada página tem especificação em `docs/specifications/pages/`; esta especificação contém apenas decisões transversais. O README descreve configuração e execução; ambos devem ser atualizados junto a mudanças relevantes.
