#!/bin/bash
# setup.sh — configura o ambiente Claude Code para este projeto.
# Verifica dependências, instala o que falta (macOS/Linux) e torna hooks executáveis.
# Idempotente: pode rodar múltiplas vezes sem efeitos colaterais.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[ok]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[erro]${NC} $1"; FAILED=1; }

FAILED=0

echo "Configurando ambiente Claude Code..."
echo ""
echo "── Dependências obrigatórias ──────────────────────────────────────────────"

# ─── git ──────────────────────────────────────────────────────────────────────
# Usado em: inject-git-context.sh
if command -v git &>/dev/null; then
    ok "git $(git --version | awk '{print $3}')"
else
    fail "git não encontrado — instale em https://git-scm.com"
fi

# ─── python3 ──────────────────────────────────────────────────────────────────
# Necessário para executar código Python, testes e o linter de convenções (python_style_check.py)
# Versão mínima: 3.8 (ast.arg.posonlyargs introduzido no 3.8)
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version | awk '{print $2}')
    PY_MINOR=$(echo "$PY_VERSION" | awk -F. '{print $2}')
    PY_MAJOR=$(echo "$PY_VERSION" | awk -F. '{print $1}')
    if [ "$PY_MAJOR" -gt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 8 ]); then
        ok "python3 ${PY_VERSION}"
    else
        fail "python3 ${PY_VERSION} — versão mínima requerida: 3.8"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            warn "  → brew upgrade python3"
        else
            warn "  → sudo apt install python3.11   (Debian/Ubuntu)"
            warn "  → sudo dnf install python3.11   (Fedora/RHEL)"
        fi
    fi
else
    fail "python3 não encontrado"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        warn "  → brew install python3"
    else
        warn "  → sudo apt install python3   (Debian/Ubuntu)"
        warn "  → sudo dnf install python3   (Fedora/RHEL)"
    fi
fi

# ─── jq ───────────────────────────────────────────────────────────────────────
# Usado em: todos os hooks (parse de JSON via stdin/stdout)
if command -v jq &>/dev/null; then
    ok "jq $(jq --version)"
else
    warn "jq não encontrado — tentando instalar..."
    INSTALLED=0
    if [[ "$OSTYPE" == "darwin"* ]] && command -v brew &>/dev/null; then
        brew install jq && INSTALLED=1
    elif command -v apt-get &>/dev/null; then
        sudo apt-get install -y jq && INSTALLED=1
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y jq && INSTALLED=1
    fi

    if [ "$INSTALLED" -eq 1 ] && command -v jq &>/dev/null; then
        ok "jq instalado ($(jq --version))"
    else
        fail "jq não encontrado e instalação automática falhou"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            warn "  → brew install jq   (requer Homebrew: https://brew.sh)"
        else
            warn "  → sudo apt install jq   (Debian/Ubuntu)"
            warn "  → sudo dnf install jq   (Fedora/RHEL)"
        fi
    fi
fi

echo ""
echo "── Ferramentas de qualidade (opcionais — hooks degradam silenciosamente) ──"

# ─── shellcheck ───────────────────────────────────────────────────────────────
# Usado em: check-bash-syntax.sh (análise de qualidade de scripts shell)
if command -v shellcheck &>/dev/null; then
    ok "shellcheck $(shellcheck --version | awk '/version:/{print $2}')"
else
    warn "shellcheck não encontrado — análise de qualidade shell desabilitada"
    INSTALLED=0
    if [[ "$OSTYPE" == "darwin"* ]] && command -v brew &>/dev/null; then
        brew install shellcheck && INSTALLED=1
    elif command -v apt-get &>/dev/null; then
        sudo apt-get install -y shellcheck && INSTALLED=1
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y shellcheck && INSTALLED=1
    fi
    if [ "$INSTALLED" -eq 1 ] && command -v shellcheck &>/dev/null; then
        ok "shellcheck instalado"
    else
        warn "  → brew install shellcheck  (macOS)"
        warn "  → sudo apt install shellcheck  (Debian/Ubuntu)"
    fi
fi

# ─── ruff ─────────────────────────────────────────────────────────────────────
# Linter Python — configurado em pyproject.toml (ignora regras de nomenclatura)
if command -v ruff &>/dev/null; then
    ok "ruff $(ruff --version)"
else
    warn "ruff não encontrado — linting Python desabilitado"
    if command -v pip3 &>/dev/null; then
        pip3 install ruff --quiet 2>/dev/null \
            || pip3 install ruff --quiet --user 2>/dev/null \
            && ok "ruff instalado" \
            || warn "  → pip3 install ruff --user"
    else
        if [[ "$OSTYPE" == "darwin"* ]] && command -v brew &>/dev/null; then
            brew install ruff --quiet && ok "ruff instalado" || warn "  → brew install ruff"
        else
            warn "  → pip3 install ruff   (ou: brew install ruff no macOS)"
        fi
    fi
fi

# ─── mutmut ───────────────────────────────────────────────────────────────────
# Mutation testing — usado em /mutation-test e /tdd (gate de qualidade)
if command -v mutmut &>/dev/null; then
    ok "mutmut $(mutmut --version 2>/dev/null | head -1)"
else
    warn "mutmut não encontrado — mutation testing desabilitado"
    if command -v pip3 &>/dev/null; then
        pip3 install mutmut --quiet 2>/dev/null \
            || pip3 install mutmut --quiet --user 2>/dev/null \
            && ok "mutmut instalado" \
            || warn "  → pip3 install mutmut --user"
    else
        warn "  → pip3 install mutmut   (ou: brew install mutmut no macOS)"
    fi
fi

# ─── mutmut.toml — paths_to_mutate ───────────────────────────────────────────
# Ignorado em workspace: mutmut.toml na raiz é irrelevante quando há sub-repos.
_WORKSPACE_COUNT=0
for _d in */; do
    [ -d "$_d" ] || continue
    [[ "${_d%/}" == .* ]] && continue
    find "$_d" -maxdepth 3 -name '__init__.py' ! -path '*/.venv/*' 2>/dev/null | grep -q . && _WORKSPACE_COUNT=$((_WORKSPACE_COUNT + 1))
    [ "$_WORKSPACE_COUNT" -gt 1 ] && break
done
if [ "$_WORKSPACE_COUNT" -le 1 ]; then
    if [ -f "mutmut.toml" ] && grep -q 'paths_to_mutate = "src/"' mutmut.toml; then
        fail "mutmut.toml: paths_to_mutate aponta para 'src/' (placeholder)"
        warn "  → Execute ./configure.sh — detecta diretório automaticamente"
    fi
fi

# ─── pipeline CLI ─────────────────────────────────────────────────────────────
# Banco de dados + CLI da pipeline EBTM — essencial para auditabilidade e rastreabilidade
echo ""
echo "── Pipeline CLI ─────────────────────────────────────────────────────────────"

PIPELINE_DEST="${HOME}/.claude/pipeline"
PIP3_CMD=""
for _pip in pip3 pip; do
    if command -v "$_pip" &>/dev/null; then
        PIP3_CMD="$_pip"
        break
    fi
done
if [ -z "$PIP3_CMD" ] && python3 -m pip --version &>/dev/null 2>&1; then
    PIP3_CMD="python3 -m pip"
fi

if command -v pipeline &>/dev/null; then
    ok "pipeline CLI disponível"
else
    warn "pipeline CLI não encontrado — tentando instalar..."
    if [ -d "$PIPELINE_DEST" ] && [ -n "$PIP3_CMD" ]; then
        $PIP3_CMD install -e "$PIPELINE_DEST" --quiet 2>/dev/null \
            && ok "pipeline CLI instalado" \
            || fail "pipeline CLI — falha na instalação (tente: pip3 install -e ${PIPELINE_DEST})"
    elif [ ! -d "$PIPELINE_DEST" ]; then
        fail "pipeline CLI — ${PIPELINE_DEST} não encontrado"
        warn "  → rode install.sh para provisionar o ambiente completo"
    else
        fail "pipeline CLI — pip3 não disponível"
        warn "  → instale python3/pip3 e rode: pip3 install -e ${PIPELINE_DEST}"
    fi
fi

# ChromaDB (obrigatório — contexto semântico do Intake Protocol)
if python3 -c "import chromadb" &>/dev/null 2>&1; then
    ok "chromadb — contexto semântico habilitado"
else
    fail "chromadb não instalado — Intake Protocol sem contexto semântico"
    if [ -n "$PIP3_CMD" ]; then
        $PIP3_CMD install chromadb --quiet 2>/dev/null \
            && ok "chromadb instalado" \
            || warn "  → pip3 install chromadb"
    else
        warn "  → pip3 install chromadb"
    fi
fi

# ─── osascript ────────────────────────────────────────────────────────────────
# Usado em: notify-done.sh (notificação macOS ao terminar tarefa)
# Opcional — o hook degrada silenciosamente se ausente.
if command -v osascript &>/dev/null; then
    ok "osascript (notificações macOS habilitadas)"
else
    ok "osascript não disponível — notificações desabilitadas (normal em Linux/CI)"
fi

# ─── sortImports.py ───────────────────────────────────────────────────────────
# Organizador de imports Python — copia para ~/.config/ para uso pelo hook sort-imports-on-edit.sh
if [ -f ".claude/hooks/sortImports.py" ]; then
    mkdir -p "$HOME/.config"
    cp ".claude/hooks/sortImports.py" "$HOME/.config/sortImports.py"
    ok "sortImports.py instalado em ~/.config/"
fi

# ─── hooks executáveis ────────────────────────────────────────────────────────
echo ""
echo "── Permissões ──────────────────────────────────────────────────────────────"
if chmod +x .claude/hooks/*.sh 2>/dev/null; then
    ok "permissões aplicadas em .claude/hooks/"
else
    fail "não foi possível aplicar permissões em .claude/hooks/ — rode a partir da raiz do projeto"
fi

# ─── CLAUDE_HOOKS_DIR — portabilidade dos hooks ───────────────────────────────
if command -v jq &>/dev/null && [ -d ".claude/hooks" ]; then
    HOOKS_ABS="$(pwd)/.claude/hooks"
    SETTINGS_LOCAL=".claude/settings.local.json"
    if [ -f "$SETTINGS_LOCAL" ]; then
        TMP=$(jq --arg d "$HOOKS_ABS" '.env.CLAUDE_HOOKS_DIR = $d' "$SETTINGS_LOCAL")
    else
        TMP=$(jq -n --arg d "$HOOKS_ABS" '{"env":{"CLAUDE_HOOKS_DIR":$d}}')
    fi
    echo "$TMP" > "$SETTINGS_LOCAL"
    ok "CLAUDE_HOOKS_DIR configurado em .claude/settings.local.json"
fi

# ─── resultado ────────────────────────────────────────────────────────────────
echo ""
if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}Ambiente pronto.${NC} Abra o Claude Code na raiz do projeto:"
    echo "  claude"
else
    echo -e "${RED}Setup incompleto.${NC} Corrija os erros acima e rode novamente."
    exit 1
fi
