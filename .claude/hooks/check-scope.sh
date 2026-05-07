#!/bin/bash
# PreToolUse/Edit|Write|MultiEdit — blocks edits to files outside the active
# task's approved plan scope. Degrades silently when no active task or no plan.

if ! command -v jq &>/dev/null; then
    exit 0
fi

if ! command -v sqlite3 &>/dev/null; then
    exit 0
fi

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.path // .tool_input.file_path // empty' 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

DB_PATH="${PIPELINE_DB_PATH:-$HOME/.claude/pipeline/pipeline.db}"

if [ ! -f "$DB_PATH" ]; then
    exit 0
fi

ACTIVE_TASK=$(sqlite3 "$DB_PATH" \
    "SELECT id FROM tasks WHERE status = 'em andamento' AND phase = 'implementation' LIMIT 1" \
    2>/dev/null)

if [ -z "$ACTIVE_TASK" ]; then
    exit 0
fi

PLAN_ID=$(sqlite3 "$DB_PATH" \
    "SELECT id FROM planArtifacts WHERE taskId = '${ACTIVE_TASK}' AND approved = 1 ORDER BY id DESC LIMIT 1" \
    2>/dev/null)

if [ -z "$PLAN_ID" ]; then
    exit 0
fi

IN_SCOPE=$(sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) FROM planScope WHERE taskId = '${ACTIVE_TASK}' AND planId = '${PLAN_ID}' AND filePath = '${FILE_PATH}'" \
    2>/dev/null)

if [ "${IN_SCOPE}" = "0" ]; then
    echo "BLOQUEADO: '${FILE_PATH}' fora do escopo do plan aprovado (task ${ACTIVE_TASK}). Atualize o plan antes de editar." >&2
    exit 2
fi

exit 0
