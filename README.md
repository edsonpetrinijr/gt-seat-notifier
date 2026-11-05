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

## Rodar em background

```bash
nohup python3 server.py > notifier.log 2>&1 &
```

Dados de [GT Scheduler](https://gt-scheduler.github.io/).
