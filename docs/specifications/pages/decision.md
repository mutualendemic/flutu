# Especificação — escolha de direção

## Rota e acesso

- `/decision` é privada, nível 2, linkada no dashboard e retorna ao dashboard.
- `POST /api/decision` requer sessão. A rota invoca serviço ANU; falha externa/formato inválido retorna JSON 502.

## Comportamento

- A interface oferece o botão “Choose for me”. Cada clique faz uma nova requisição; o controle fica desabilitado durante a solicitação e mostra o resultado ou erro.
- O servidor consulta o gerador de permutações aleatórias da ANU e interpreta o último valor da permutação de 1 e 2 para indicar esquerda/direita. A permutação não é exibida nem persistida.
- A página inclui link externo para a fonte ANU e link filho para `/decision/info`.

## Arquivos relacionados

`app/main/routes.py`, `app/services/quantum_random.py`, `app/templates/decision.html`.
