#!/usr/bin/env bash
# Dispara alerta no Telegram quando um service do agente-tjms falha.
# Uso: alerta.sh <nome-do-job>     (ex.: alerta.sh coletor)
# Acionado via OnFailure=alerta@%N.service nos services do agente.
#
# Variáveis lidas do EnvironmentFile (~/.config/agente-tjms.env):
#   AGENTE_TJMS_HOME           path absoluto do repo
#   AGENTE_TJMS_TG_TOKEN       token do bot Telegram
#   AGENTE_TJMS_TG_CHAT_ID     chat ID destino

set -euo pipefail

UNIT="${1:?uso: $0 <unit-name-sem-extensao>}"

: "${AGENTE_TJMS_HOME:?AGENTE_TJMS_HOME nao definida (cheque ~/.config/agente-tjms.env)}"
: "${AGENTE_TJMS_TG_TOKEN:?AGENTE_TJMS_TG_TOKEN nao definida}"
: "${AGENTE_TJMS_TG_CHAT_ID:?AGENTE_TJMS_TG_CHAT_ID nao definida}"

HOST=$(hostname)
NOW=$(date -Iseconds)

# Última execução registrada no DB (via Python do venv pra evitar dependência de sqlite3 CLI)
EXEC_LINE=$(
    "${AGENTE_TJMS_HOME}/.venv/bin/python" - <<PYEOF 2>&1 || echo "(query falhou)"
import sqlite3, sys
from pathlib import Path
db = Path("${AGENTE_TJMS_HOME}") / "data" / "tjms.sqlite"
if not db.exists():
    print("(DB inexistente)")
    sys.exit(0)
con = sqlite3.connect(db)
r = con.execute(
    "SELECT modulo, status, COALESCE(mensagem, '(none)') "
    "FROM execucao ORDER BY id DESC LIMIT 1"
).fetchone()
print(f"modulo={r[0]} status={r[1]} mensagem={r[2]}" if r else "(nenhuma execucao registrada)")
PYEOF
)

# Últimas 15 linhas do journal do unit que falhou
JOURNAL=$(journalctl --user -u "${UNIT}.service" -n 15 --no-pager --output=cat 2>&1 \
          || echo "(journal indisponivel)")

MSG="🚨 agente-tjms: ${UNIT} falhou
host: ${HOST}   horário: ${NOW}

[última execucao no DB]
${EXEC_LINE}

[journal — últimas 15 linhas]
${JOURNAL}"

# Trunca a 3500 chars pra ter margem do limite de 4096 do Telegram
MSG="${MSG:0:3500}"

curl -sS --max-time 10 -X POST \
    "https://api.telegram.org/bot${AGENTE_TJMS_TG_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${AGENTE_TJMS_TG_CHAT_ID}" \
    --data-urlencode "text=${MSG}" \
    > /dev/null
