#!/bin/bash
# UserPromptSubmit — injeta contexto das tarefas ativas e busca semântica contextual.
# Tenta pipeline CLI primeiro; cai no TASKS.md como fallback.

if ! command -v jq &>/dev/null; then
    exit 0
fi

INPUT=$(cat)

SEARCH_CONTEXT=""

# --- Busca semântica contextual via Haiku ---
if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ -n "${CLAUDE_HOOKS_DIR:-}" ]; then
    CLASSIFY_SCRIPT="${CLAUDE_HOOKS_DIR}/classifySearch.py"
    USER_MESSAGE=$(echo "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)
    if [ -f "$CLASSIFY_SCRIPT" ] && [ -n "$USER_MESSAGE" ]; then
        RESULT=$(python3 "$CLASSIFY_SCRIPT" "$USER_MESSAGE" 2>/dev/null)
        if [ $? -ne 0 ] || [ -z "$RESULT" ]; then
            echo "AVISO: classificacao de busca semantica falhou — prosseguindo sem contexto" >&2
        else
            SHOULD_SEARCH=$(echo "$RESULT" | jq -r '.search // false' 2>/dev/null)
            SEARCH_QUERY=$(echo "$RESULT" | jq -r '.query // empty' 2>/dev/null)
            if [ "$SHOULD_SEARCH" = "true" ] && [ -n "$SEARCH_QUERY" ] && command -v pipeline &>/dev/null; then
                SEARCH_OUTPUT=$(pipeline context search "$SEARCH_QUERY" 2>/dev/null || true)
                if [ -n "$SEARCH_OUTPUT" ]; then
                    SEARCH_CONTEXT=$(printf "\nContexto relevante:\n%s" "$SEARCH_OUTPUT")
                fi
            fi
        fi
    fi
fi

MANDATORY="

GESTÃO DE TAREFAS — OBRIGATÓRIO:
Antes de finalizar esta resposta, verifique o status da tarefa ativa:
  • Trabalho completado nesta resposta → pipeline task update <ID> --status \"concluído\"
  • Fase concluída nesta resposta     → pipeline phase advance <ID> --to <próxima-fase>
  • Bloqueado                         → pipeline task update <ID> --status \"bloqueado\"
Nunca encerre uma resposta com trabalho concluído sem executar o comando acima."

CONTEXT=""

# --- Tentativa 1: pipeline CLI (fonte de verdade) ---
if command -v pipeline &>/dev/null; then
    ACTIVE=$(pipeline task list --status "em andamento" --format context 2>/dev/null)
    if [ -n "$ACTIVE" ]; then
        echo "[inject-tasks] source=pipeline-cli" >&2
        CONTEXT=$(printf "Tarefas ativas (pipeline DB):\n%s\n%s%s" "$ACTIVE" "$MANDATORY" "$SEARCH_CONTEXT")
        jq -n --arg ctx "$CONTEXT" '{
            hookSpecificOutput: {
                hookEventName: "UserPromptSubmit",
                additionalContext: $ctx
            }
        }'
        exit 0
    fi
fi

# --- Fallback: TASKS.md ---
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -n "$GIT_ROOT" ] && [ -f "${GIT_ROOT}/TASKS.md" ]; then
    TASKS_FILE="${GIT_ROOT}/TASKS.md"
elif [ -f "TASKS.md" ]; then
    TASKS_FILE="TASKS.md"
else
    exit 0
fi

ACTIVE=$(awk '/^## Tarefas Ativas/{found=1; next} /^## Histórico/{found=0} found' "$TASKS_FILE" \
    | grep -v '^_Nenhuma' \
    | grep -v '^# Gerado' \
    | sed '/^[[:space:]]*$/d')

if [ -z "$ACTIVE" ]; then
    echo "[inject-tasks] skip: no active tasks in TASKS.md" >&2
    exit 0
fi

echo "[inject-tasks] source=TASKS.md" >&2
STALE=$(echo "$ACTIVE" | grep -iE '\*\*Status:\*\*\s*(concluído|cancelado)')
CONTEXT=$(printf "Tarefas ativas (TASKS.md):\n%s\n%s%s" "$ACTIVE" "$MANDATORY" "$SEARCH_CONTEXT")

if [ -n "$STALE" ]; then
    CONTEXT=$(printf "ACAO OBRIGATORIA: tarefas concluídas ainda em Tarefas Ativas. Mova para Histórico ANTES de responder.\n\n%s" "$CONTEXT")
fi

jq -n --arg ctx "$CONTEXT" '{
    hookSpecificOutput: {
        hookEventName: "UserPromptSubmit",
        additionalContext: $ctx
    }
}'
