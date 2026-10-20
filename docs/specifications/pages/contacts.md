# Especificação — contatos

## Rota e acesso

- `/contacts` é privada, nível 2, ligada ao dashboard e contém link de retorno ao dashboard.
- APIs relacionadas: `GET /api/contacts`, `POST /api/contacts`, `DELETE /api/contacts`, `DELETE /api/contacts/<contact_id>`. Todas exigem sessão e usam `session.user.sub` como proprietário.

## Comportamento atual

- A lista persistida é específica à conta Google e está disponível entre sessões/dispositivos quando MongoDB está configurado.
- Permite adicionar contato manualmente, pesquisar, excluir um contato e limpar todos.
- Importa pelo Contact Picker quando navegador e contexto seguro suportam. Alternativamente lê arquivo `.vcf` até 5 MiB, interpreta dados localmente e limita a 100 registros por chamada ao servidor.
- Campos aceitos: nome obrigatório (até 120), telefone opcional (até 80), e-mail opcional (até 254); pelo menos telefone ou e-mail deve existir. A API retorna 400 para payload inválido e 503 quando MongoDB não está disponível.
- Dedupe de importação compara e-mail em minúsculas e telefone sem espaços entre os contatos já carregados na página. A persistência não impõe unicidade global de contatos.

## Arquivos relacionados

`app/main/routes.py`, `app/services/contacts.py`, `app/templates/contacts.html`.
