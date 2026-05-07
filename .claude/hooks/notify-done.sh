#!/bin/bash
# Stop — notificação macOS quando Claude termina uma tarefa.
# Silencioso em ambientes sem osascript (CI/Linux).

if command -v osascript &>/dev/null; then
    osascript -e 'display notification "Tarefa concluída" with title "Claude Code" sound name "Glass"' 2>/dev/null
fi

DB_PATH="${PIPELINE_DB_PATH:-$HOME/.claude/pipeline/pipeline.db}"

if [ ! -f "$DB_PATH" ] || ! command -v sqlite3 &>/dev/null; then
    exit 0
fi

NEEDS_MAINTENANCE=$(sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) FROM tasks WHERE status IN ('em andamento', 'concluído')" \
    2>/dev/null)

if [ -z "$NEEDS_MAINTENANCE" ] || [ "$NEEDS_MAINTENANCE" = "0" ]; then
    exit 0
fi

if ! command -v claude &>/dev/null; then
    echo "AVISO: claude CLI indisponível — tasks-maintainer não invocado" >&2
    exit 0
fi

claude --agent tasks-maintainer -p "Verifique e atualize TASKS.md: mova tarefas concluídas para HISTORY_TASKS.md e atualize status das tarefas ativas." 2>/dev/null
if [ $? -ne 0 ]; then
    echo "AVISO: tasks-maintainer falhou — TASKS.md pode estar desatualizado" >&2
fi

exit 0
