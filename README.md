# GT Course Seat Notifier

Monitora vagas em cursos do Georgia Tech e envia notificações push via [ntfy.sh](https://ntfy.sh). Roda localmente, sem servidor, sem dependências externas.

---

## Como funciona

1. Lê `config.json` com os cursos desejados (ex: `"CS 1332"`)
2. Busca todas as sections disponíveis para cada curso no GT Scheduler
3. Verifica vagas em cada section a cada N segundos (padrão: 60s)
4. Notifica via ntfy.sh quando uma vaga ou vaga na fila abre

---

## Setup (menos de 5 minutos)

**1. Instala ntfy no celular**

- Android: [Google Play](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
- iOS: [App Store](https://apps.apple.com/us/app/ntfy/id1625396347)

Abre o app → toca **+** → coloca um nome único de tópico (ex: `gt-alerts-seunome`). Inscreve-se nele.

**2. Cria o config**

```bash
cp config.json.example config.json
```

Edita `config.json`:

```json
{
  "ntfy_topic": "gt-alerts-seunome",
  "ntfy_server": "https://ntfy.sh",
  "term": "202702",
  "courses": ["CS 1332", "CS 3510"],
  "interval": 60
}
```

**3. Roda**

```bash
python3 check_seats.py
```

---

## Campos do config.json

| Campo | Obrigatório | Descrição |
|---|---|---|
| `ntfy_topic` | ✅ | Nome do tópico ntfy (igual ao cadastrado no app) |
| `term` | ✅ | Código do semestre (ver abaixo) |
| `courses` | ✅ | Array de cursos no formato `"DEPT NNNN"` |
| `ntfy_server` | ❌ | URL do servidor ntfy. Padrão: `https://ntfy.sh` |
| `interval` | ❌ | Segundos entre checagens. Padrão: `60` |

**Código do term:** `YYYYSS` onde SS = `02` (Spring) / `05` (Summer) / `08` (Fall).  
Exemplo: `202702` = Spring 2027, `202608` = Fall 2026.

---

## Como achar o código do curso

Use exatamente o formato `DEPT NNNN` separado por espaço:

```
"CS 1332"   ✅
"MATH 1553" ✅
"CS1332"    ✅  (o script normaliza automaticamente)
```

Para confirmar o nome exato, veja em [gt-scheduler.github.io](https://gt-scheduler.github.io/).

---

## Comportamento das notificações

| Condição | Prioridade ntfy | Tags | Ação |
|---|---|---|---|
| Vagas abertas (`Enrollment Seats Available > 0`) | **urgent** | 🎉 tada, school | Notifica imediatamente |
| Fila disponível (`Waitlist Seats Available > 0`) | **high** | ⏳ hourglass, school | Notifica |
| Sem vagas e sem fila | — | — | Apenas loga, sem notificação |

O script não repete notificação para a mesma section enquanto a vaga ainda estiver aberta. Se a vaga fechar e reabrir, notifica novamente.

---

## Rodar em background (macOS)

### Opção 1 — Terminal em background

```bash
nohup python3 check_seats.py > notifier.log 2>&1 &
echo $! > notifier.pid
```

Para parar:
```bash
kill $(cat notifier.pid)
```

### Opção 2 — launchd (inicia com o Mac)

Cria o arquivo `~/Library/LaunchAgents/com.gt-notifier.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.gt-notifier</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/CAMINHO/ABSOLUTO/check_seats.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/CAMINHO/ABSOLUTO/</string>
  <key>StandardOutPath</key>
  <string>/tmp/gt-notifier.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/gt-notifier.log</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
```

Substitui `/CAMINHO/ABSOLUTO/` pelo diretório real. Depois:

```bash
launchctl load ~/Library/LaunchAgents/com.gt-notifier.plist

# Ver logs:
tail -f /tmp/gt-notifier.log

# Parar:
launchctl unload ~/Library/LaunchAgents/com.gt-notifier.plist
```

---

## Debug

Logs são impressos no stdout em tempo real:

```
[INFO] Term: 202702 | Courses: CS 1332, CS 3510
[INFO] CS 1332 (Data Structures and Algorithms): 12 section(s) found
[INFO] Monitoring 12 section(s) across 2 course(s)

[RUN #1] 2026-04-21 14:00:00
  CS 1332 §A (CRN 12345): enroll=24/25 (+1 avail)  wl=0/10 (+10 avail)
    ✅ SEAT OPEN — notifying (urgent)
    → Notification sent (HTTP 200)
```

Se um curso não for encontrado, o script lista cursos similares disponíveis no termo.
