# Especificação — mapa e compartilhamento

## Rota e interface

- `/map` é privada, nível 2, ligada ao dashboard e fornece retorno ao dashboard.
- O mapa usa Leaflet e tiles OpenStreetMap, e exibe somente os últimos pontos compartilhados com o usuário atual. Quando o próprio usuário habilitou o envio, também mostra um marcador azul do próprio aparelho e o horário/precisão do último ponto recebido pelo servidor.
- A tela lista solicitações recebidas, solicitações pendentes enviadas e pessoas que autorizaram compartilhar com o usuário. Permite pedir localização a um contato com e-mail, aceitar/recusar/cancelar pedidos, revogar uma permissão ou revogar todas.

## Fluxo e consentimento

1. O remetente escolhe um contato salvo. O servidor confirma que esse contato pertence à conta autenticada e resolve sua conta pelo e-mail normalizado do diretório Flutu.
2. Se a conta já entrou via Google, o servidor cria uma solicitação `pending`, identificada por IDs de conta Google (`sub`). Solicitações são internas ao app; não há envio de e-mail/push.
3. O destinatário decide aceitar ou recusar. Aceitar adiciona o solicitante à lista de contatos do destinatário, se o e-mail ainda não existir.
4. O proprietário da localização decide separadamente habilitar atualizações. Sem ao menos um pedido recebido aceito, o botão fica desativado; a interface explica que um contato deve solicitar a localização primeiro. Ao clicar para habilitar, a página solicita a posição imediatamente, no contexto direto da ação do usuário, para iniciar o prompt de permissão nativo do browser (não há uma página Flutu de autorização); só após obter posição grava o opt-in e envia o primeiro ponto. Se o browser já tiver uma decisão salva, ele não exibe novo prompt e segue essa decisão. Opt-in é persistido no perfil e pode ser pausado na página. Mensagens distinguem contexto sem HTTPS, permissão negada, GPS indisponível e timeout.
5. Se habilitado e houver ao menos um destinatário aceito, `location-sharing.js` consulta GPS e envia atualização aproximadamente a cada 30 s por qualquer rota autenticada visível. A página oculta suspende o ciclo e a volta ao primeiro plano solicita atualização. Página fechada não envia.

## Armazenamento e acesso

- Cada update faz upsert do ponto GeoJSON mais precisão e timestamp em um documento único com `owner_id` exclusivo. Não se guarda histórico.
- API de overview retorna localização apenas ao requester de uma relação `accepted`; dados com idade >=120 s são omitidos. TTL MongoDB remove pontos após 180 s de inatividade. Pausar opt-in ou revogar o último grant apaga imediatamente.
- Revogar um grant individual deixa os outros grants aceitos ativos. Remover último grant desabilita opt-in e remove o ponto.
- Rotas API privadas: `GET /api/location/overview`, `GET /api/location/status`, `POST /api/location/sharing`, `POST /api/location/requests`, `POST /api/location/requests/<id>/respond`, `POST /api/location/updates`, `DELETE /api/location/shares`, `DELETE /api/location/shares/<id>`. Validação, escopo e regras constam na especificação [arquitetural](../architecture.md).
- Localização é sensível. O uso depende de consentimento explícito, browser permitir GPS e contexto HTTPS fora de localhost. Os erros de GPS do atualizador global são apresentados na página de mapa e no indicador de compartilhamento do dashboard. Não usar esses dados como trilha/histórico.

## Arquivos relacionados

`app/main/routes.py`, `app/services/location_sharing.py`, `app/static/location-sharing.js`, `app/templates/location_map.html`, `app/templates/base.html`.
