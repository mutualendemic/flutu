# Especificação — perfil

## Rota, acesso e navegação

- `/profile` é privada, nível 2, e aparece como **My profile** no dashboard. A página retorna ao dashboard.
- A página apresenta nome e e-mail da sessão autenticada Google.

## Foto de perfil no mapa

- Não há opção para selecionar o marcador. A foto fornecida pelo perfil Google autenticado é usada para representar o usuário no mapa; quando indisponível ou não carregável, são exibidas as iniciais do nome.
- A página continua apresentando nome e e-mail associados à sessão, e esclarece o uso da foto no mapa.
- A foto é incluída nos dados de localização apenas para relacionamentos com consentimento aceito; não é compartilhada com usuários sem autorização.

## Arquivos relacionados

`app/main/routes.py`, `app/services/location_sharing.py`, `app/templates/profile.html`, `app/templates/dashboard.html`, `app/templates/location_map.html`.
