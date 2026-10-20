# Especificação — perfil

## Rota, acesso e navegação

- `/profile` é privada, nível 2, e aparece como **My profile** no dashboard. A página retorna ao dashboard.
- A página apresenta nome e e-mail da sessão autenticada Google.

## Preferência do marcador

- O usuário escolhe o ícone de localização entre 16 opções: pin, pessoa, carro, bicicleta, casa, estrela, cão, ônibus, motocicleta, barco, avião, caminhando, correndo, cadeira de rodas, barraca e bandeira.
- A preferência é carregada de `GET /api/location/status` e gravada por `POST /api/location/map-icon`. API requer sessão, valida contra a whitelist do serviço e salva em `users.map_icon` pelo `sub` do Google.
- Um preview mostra o ícone selecionado. A preferência se aplica ao marcador do proprietário e é retornada junto das localizações para solicitantes autorizados.
- Falha ao carregar ou persistir a preferência aparece como mensagem na interface; a opção não é enviada a usuários que não tenham autorização para a localização.

## Arquivos relacionados

`app/main/routes.py`, `app/services/location_sharing.py`, `app/templates/profile.html`, `app/templates/dashboard.html`, `app/templates/location_map.html`.
