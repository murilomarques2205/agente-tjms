#!/usr/bin/env bash
# Wrapper invocado pelo Windows Task Scheduler para rodar o agente-tjms via WSL.
#
# Uso:  run-via-task-scheduler.sh <subcomando> [args...]
# Ex.:  run-via-task-scheduler.sh coletar
#       run-via-task-scheduler.sh rastrear-acordaos
#       run-via-task-scheduler.sh relatorio --telegram
#
# Comportamento:
#   - Carrega ~/.config/agente-tjms/agente-tjms.env (token Telegram etc.).
#   - Roda o agente-tjms; stdout/stderr vão pra logs/task-scheduler.log.
#   - Em caso de exit != 0, dispara alerta no Telegram com a cauda do log.
#   - Propaga o código de saída pro Task Scheduler.

set -uo pipefail

REPO="$HOME/projetos/agente-tjms"
LOG="$REPO/logs/task-scheduler.log"
mkdir -p "$(dirname "$LOG")"

set -a
# shellcheck disable=SC1090
source "$HOME/.config/agente-tjms/agente-tjms.env" 2>/dev/null || true
set +a

cd "$REPO"

exit_code=0
{
    echo
    echo "=== $(date -Iseconds) agente-tjms $* ==="
    "$REPO/.venv/bin/agente-tjms" "$@"
    exit_code=$?
    echo "=== exit=$exit_code ==="
} >> "$LOG" 2>&1

if [ "$exit_code" -ne 0 ] \
    && [ -n "${AGENTE_TJMS_TG_TOKEN:-}" ] \
    && [ -n "${AGENTE_TJMS_TG_CHAT_ID:-}" ]; then
    HOST=$(hostname)
    NOW=$(date -Iseconds)
    TAIL=$(tail -n 25 "$LOG" 2>/dev/null || true)
    MSG="🚨 agente-tjms: 'agente-tjms $*' falhou (exit=$exit_code)
host: $HOST   horário: $NOW

[últimas 25 linhas do log]
$TAIL"
    MSG="${MSG:0:3500}"
    curl -sS --max-time 10 -X POST \
        "https://api.telegram.org/bot${AGENTE_TJMS_TG_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${AGENTE_TJMS_TG_CHAT_ID}" \
        --data-urlencode "text=${MSG}" \
        > /dev/null || true
fi

exit "$exit_code"
