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

PROJECT_ROOT="${CLAUDE_HOOKS_DIR%/.claude/hooks}"
if [[ "$FILE_PATH" == "$PROJECT_ROOT/"* ]]; then
    FILE_PATH="${FILE_PATH#$PROJECT_ROOT/}"
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

COMPONENTS_JSON=$(sqlite3 "$DB_PATH" \
    "SELECT components FROM planScope WHERE taskId = '${ACTIVE_TASK}' AND planId = '${PLAN_ID}' AND filePath = '${FILE_PATH}'" \
    2>/dev/null)

if [ -z "$COMPONENTS_JSON" ] || [ "$COMPONENTS_JSON" = "[]" ]; then
    exit 0
fi

if [[ "$FILE_PATH" != *.py ]]; then
    echo "AVISO: verificação de componentes ignorada para arquivo não-Python: ${FILE_PATH}" >&2
    exit 0
fi

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)

if [ "$TOOL_NAME" = "Write" ]; then
    CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty' 2>/dev/null)
    NEW_COMPONENTS=$(echo "$CONTENT" | grep -E '^(def |class )' | sed -E 's/^(def |class )([a-zA-Z_][a-zA-Z0-9_]*).*/\2/')
else
    NEW_STR=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty' 2>/dev/null)
    OLD_STR=$(echo "$INPUT" | jq -r '.tool_input.old_string // empty' 2>/dev/null)
    NEW_IN_NEW=$(echo "$NEW_STR" | grep -E '^(def |class )' | sed -E 's/^(def |class )([a-zA-Z_][a-zA-Z0-9_]*).*/\2/' | sort)
    NEW_IN_OLD=$(echo "$OLD_STR" | grep -E '^(def |class )' | sed -E 's/^(def |class )([a-zA-Z_][a-zA-Z0-9_]*).*/\2/' | sort)
    NEW_COMPONENTS=$(comm -23 <(echo "$NEW_IN_NEW") <(echo "$NEW_IN_OLD"))
fi

if [ -z "$NEW_COMPONENTS" ]; then
    exit 0
fi

while IFS= read -r COMP; do
    [ -z "$COMP" ] && continue
    IN_PLAN=$(echo "$COMPONENTS_JSON" | jq --arg c "$COMP" 'map(select(. == $c)) | length' 2>/dev/null)
    if [ "${IN_PLAN}" = "0" ]; then
        echo "BLOQUEADO: componente '${COMP}' em '${FILE_PATH}' fora do escopo do plan aprovado (task ${ACTIVE_TASK}). Adicione ao plan antes de implementar." >&2
        exit 2
    fi
done <<< "$NEW_COMPONENTS"

exit 0
