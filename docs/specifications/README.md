# Especificações de implementação

Este diretório registra decisões implementadas no código atual. Não é uma proposta de funcionalidades futuras. Atualize a especificação afetada no mesmo commit que mudar o comportamento e confira os links e rotas contra o código.

## Especificações transversais

- [Arquitetura e decisões compartilhadas](architecture.md)

## Páginas

| Página | Rota | Especificação |
| --- | --- | --- |
| Entrada e autenticação | `/`, `/auth/*` | [login.md](pages/login.md) |
| Dashboard | `/dashboard` | [dashboard.md](pages/dashboard.md) |
| Contatos | `/contacts` | [contacts.md](pages/contacts.md) |
| Mapa e compartilhamento | `/map` | [location-map.md](pages/location-map.md) |
| Escolha de direção | `/decision` | [decision.md](pages/decision.md) |
| Informações sobre a decisão | `/decision/info` | [quantum-info.md](pages/quantum-info.md) |

Toda nova página precisa de uma especificação própria e de uma entrada nesta tabela. APIs sem uma página dedicada e decisões comuns a mais de uma página pertencem a [architecture.md](architecture.md).
