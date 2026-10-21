# Implementation specifications

This directory records decisions implemented in the current code. It is not a proposal for future features. Update the affected specification in the same change as behavior changes, and verify links and routes against the code.

## Cross-cutting specifications

- [Architecture and shared decisions](architecture.md)

## Pages

| Page | Route | Specification |
| --- | --- | --- |
| Sign-in and authentication | `/`, `/auth/*` | [login.md](pages/login.md) |
| Dashboard | `/dashboard` | [dashboard.md](pages/dashboard.md) |
| Contacts | `/contacts` | [contacts.md](pages/contacts.md) |
| Map and sharing | `/map` | [location-map.md](pages/location-map.md) |
| Profile and preferences | `/profile` | [profile.md](pages/profile.md) |
| Direction choice | `/decision` | [decision.md](pages/decision.md) |
| Decision information | `/decision/info` | [quantum-info.md](pages/quantum-info.md) |
| Branching chat | `/chat/`, `/chat/<conversation_id>` | [branching-chat.md](pages/branching-chat.md) |

Every new page needs its own specification and an entry in this table. APIs without a dedicated page and decisions shared by multiple pages belong in [architecture.md](architecture.md).
