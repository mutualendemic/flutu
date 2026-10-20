# Especificação — mapa e compartilhamento

## Rota e interface

- `/map` é privada, nível 2, ligada ao dashboard e fornece retorno ao dashboard.
- Os botões para habilitar/pausar atualizações e interromper todos os compartilhamentos ficam desativados e visualmente esmaecidos quando não há permissões de compartilhamento aceitas.
- O mapa usa Leaflet e tiles OpenStreetMap e exibe os últimos pontos compartilhados com o usuário atual. Ao abrir o mapa, solicita a localização do próprio dispositivo e atualiza um marcador azul localmente a cada 30 segundos, mesmo sem nenhum compartilhamento aceito. Um botão permite tentar novamente após erro/permissão negada. No modo privado, o ponto próprio não é enviado nem salvo no servidor. Se o usuário habilitar compartilhamento, o marcador próprio passa a refletir o último ponto atualizado no servidor, que é entregue apenas aos destinatários autorizados.
- A tela lista solicitações recebidas, solicitações pendentes enviadas e pessoas que autorizaram compartilhar com o usuário. Permite pedir localização a um contato com e-mail, aceitar/recusar/cancelar pedidos, revogar uma permissão ou revogar todas.

## Fluxo e consentimento

1. O remetente escolhe um contato salvo. O servidor confirma que esse contato pertence à conta autenticada e resolve sua conta pelo e-mail normalizado do diretório Flutu.
2. Se a conta já entrou via Google, o servidor cria uma solicitação `pending`, identificada por IDs de conta Google (`sub`). Solicitações são internas ao app; não há envio de e-mail/push.
3. O destinatário decide aceitar ou recusar. Aceitar adiciona o solicitante à lista de contatos do destinatário, se o e-mail ainda não existir.
4. O proprietário da localização decide separadamente habilitar atualizações. Sem ao menos um pedido recebido aceito, o botão fica desativado; a interface explica que um contato deve solicitar a localização primeiro. Ao clicar para habilitar, a página solicita a posição imediatamente, no contexto direto da ação do usuário, para iniciar o prompt de permissão nativo do browser (não há uma página Flutu de autorização); só após obter posição grava o opt-in e envia o primeiro ponto. Se o browser já tiver uma decisão salva, ele não exibe novo prompt e segue essa decisão. Opt-in é persistido no perfil e pode ser pausado na página. Mensagens distinguem contexto sem HTTPS, permissão negada, GPS indisponível e timeout.
5. No mapa, localização local é obtida imediatamente e depois a cada ~30 s para mostrar apenas o marcador próprio; o evento de página oculta suspende as leituras, e voltar ao primeiro plano solicita uma leitura. Essas leituras privadas não gravam no servidor. Se compartilhamento estiver habilitado e houver ao menos um destinatário aceito, `location-sharing.js` também envia atualizações (~30 s) por qualquer rota autenticada visível. Página fechada não envia.

## Armazenamento e acesso

- Cada update faz upsert do ponto GeoJSON mais precisão e timestamp em um documento único com `owner_id` exclusivo. Não se guarda histórico.
- API de overview retorna localização apenas ao requester de uma relação `accepted`; dados com idade >=120 s são omitidos. TTL MongoDB remove pontos após 180 s de inatividade. Pausar opt-in ou revogar o último grant apaga imediatamente.
- Revogar um grant individual deixa os outros grants aceitos ativos. Remover último grant desabilita opt-in e remove o ponto.
- Rotas API privadas: `GET /api/location/overview`, `GET /api/location/status`, `POST /api/location/sharing`, `POST /api/location/requests`, `POST /api/location/requests/<id>/respond`, `POST /api/location/updates`, `DELETE /api/location/shares`, `DELETE /api/location/shares/<id>`. Validação, escopo e regras constam na especificação [arquitetural](../architecture.md).
- Localização é sensível. O uso depende de consentimento explícito, browser permitir GPS e contexto HTTPS fora de localhost. Os erros de GPS do atualizador global são apresentados na página de mapa e no indicador de compartilhamento do dashboard. Não usar esses dados como trilha/histórico.

## Arquivos relacionados

`app/main/routes.py`, `app/services/location_sharing.py`, `app/static/location-sharing.js`, `app/templates/location_map.html`, `app/templates/base.html`.
