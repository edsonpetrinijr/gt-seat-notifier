# GT Seat Notifier

Monitora vagas em cursos do Georgia Tech e manda push no celular via [ntfy.sh](https://ntfy.sh) quando abre vaga ou fila. Um arquivo Python (só stdlib) e uma página HTML.

## Setup

1. Instala o app **ntfy** ([iOS](https://apps.apple.com/us/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)), toca **+** e assina um tópico com nome único (ex: `gt-alerts-seunome`).
2. `cp config.json.example config.json` e coloca seu tópico em `ntfy_topic`.
3. Roda:

```bash
python3 server.py
```

4. Abre http://localhost:8080 para ver as turmas e adicionar ou remover cursos.

## config.json

| Campo | Descrição |
|---|---|
| `ntfy_topic` | Tópico ntfy (o mesmo do app). Vazio = sem notificação |
| `term` | Semestre `YYYYSS`: `02` Spring, `05` Summer, `08` Fall. Ex: `202702` = Spring 2027 |
| `courses` | Lista no formato `"DEPT 1234"`. A página edita isso por você |
| `interval` | Segundos entre checagens (padrão 60) |
| `ntfy_server` | Padrão `https://ntfy.sh` |

## Notificações

- Turma passa de cheia para **vaga aberta**: prioridade urgent.
- Turma passa de cheia para **fila aberta**: prioridade high.
- A primeira checagem só registra o estado. Você recebe aviso quando algo muda, não uma lista de tudo que já está aberto.
- Vaga que abre e fecha várias vezes seguidas manda um aviso só. A turma precisa ficar 10 min pior antes de poder avisar de novo.
- Reiniciar o servidor não repete aviso (o estado fica em `state.json`). Se o ntfy falhar, o aviso é reenviado na próxima checagem.

## Como funciona por dentro

| Problema | Solução no `server.py` |
|---|---|
| Proxy do GT trava com muita requisição em paralelo | `Limiter`: AIMD (sobe +1 após respostas boas, corta pela metade em timeout/429/5xx) e retry com backoff exponencial com jitter |
| Proxy responde 200 com página de erro | `parse_seats` recusa página sem números, em vez de ler zeros e gerar aviso falso |
| Duas checagens ao mesmo tempo | Uma thread só faz checagens; adicionar curso só acorda ela |
| Dois pedidos adicionando o mesmo curso | Checagem dupla sob lock em `add_course` |
| Curso removido no meio de uma checagem | `record` ignora resultado de curso que saiu da lista |
| `config.json`/`state.json` corrompidos por crash | `save_json`: arquivo temporário + `fsync` + `os.replace` |
| Aviso perdido se o processo cai ou o ntfy falha | Entrega at-least-once: disco guarda o estado anterior até o ntfy confirmar; falha faz rollback |
| Atraso entre vaga abrir e aviso chegar | Turmas cheias checadas primeiro, cada resultado tratado assim que chega, envio numa thread própria, página atualiza ao vivo por SSE |

## Testes

```bash
python3 -m unittest -v test_server
```

Os testes sobem um GT Scheduler e um ntfy falsos (`FakeGT`) que simulam limite de paralelismo, timeout, página quebrada e ntfy fora do ar.

## Rodar em background

```bash
nohup python3 server.py > notifier.log 2>&1 &
```

Dados de [GT Scheduler](https://gt-scheduler.github.io/).
