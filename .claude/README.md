# Ambiente Claude Code

Este diretório configura o Claude Code para o projeto. Ao abrir o Claude Code
na raiz do repositório, tudo aqui é carregado automaticamente — sem configuração
manual.

---

## Como funciona

```
.claude/
├── settings.json     — hooks ativos (carregado automaticamente)
├── hooks/            — scripts executados em eventos do ciclo de vida
├── agents/           — subagentes especializados (contexto isolado)
├── commands/         — slash commands reutilizáveis (/nome)
└── skills/           — skills multi-fase reutilizáveis (/skill-name)
```

O arquivo `settings.local.json` é pessoal e está no `.gitignore` — cada
desenvolvedor pode ter suas próprias permissões sem afetar o time.

---

## Hooks

Comportamentos **garantidos** — executam independentemente do que Claude decidir.

### `SessionStart` → `inject-git-context.sh`

Injeta automaticamente no início de cada sessão:
- Branch atual
- Últimos 5 commits
- Arquivos modificados (não commitados)

Claude começa cada sessão com contexto git sem precisar perguntar.

### `UserPromptSubmit` → `inject-tasks-context.sh`

Em cada prompt, injeta o estado atual das tarefas ativas do banco de dados.
Claude sempre sabe quais tarefas estão em andamento sem precisar ler o arquivo.

Adicionalmente, classifica o prompt via Claude Haiku para decidir se uma busca
semântica no histórico do projeto é relevante. Se sim, executa `pipeline context search`
automaticamente e injeta o resultado como "Contexto relevante" antes do prompt.

Degrada silenciosamente se o banco ou a API key não estiverem disponíveis.

### `UserPromptSubmit` → `validate-requirements.sh`

Em cada prompt com intenção de implementação, verifica se a tarefa ativa possui
**Requisitos EARS** preenchidos. Se não tiver, injeta alerta bloqueando geração
de código e redirecionando para `/requirements`.

Detecta intenção de implementação por palavras-chave (PT e EN): implementar, criar,
escrever, adicionar, build, write, desenvolver, codificar, etc.

Degrada silenciosamente se `TASKS.md` não existir ou se não houver tarefas em andamento.

### `PreToolUse/Edit|Write|MultiEdit` → `check-scope.sh`

Intercepta edições e criações de arquivos durante a fase `implementation`.
Verifica dois níveis:

1. **Arquivo** — o arquivo modificado deve estar no escopo do plan aprovado
2. **Componente** — funções e classes introduzidas no `new_string` (Edit) ou `content` (Write)
   devem estar listadas nos `components` do planScope para aquele arquivo

Bloqueia com `exit 2` e identifica o componente fora do escopo pelo nome.
Para arquivos não-Python, passa com aviso (sem análise de componentes).
Degrada silenciosamente se não houver task ativa em `implementation` com plan aprovado.

### `PreToolUse/Bash` → `pre-commit-gate.sh`

Intercepta qualquer `git commit` e roda a suite de testes antes de permitir.
Se os testes falharem, o commit é bloqueado com `exit 2`.

Detecta automaticamente a raiz do projeto (pytest.ini, pyproject.toml ou Pipfile)
e o runner Python disponível (.venv ou python3 do sistema).
Degrada silenciosamente se nenhum Python for encontrado.

### `PreToolUse/Bash` → `validate-destructive.sh`

Bloqueia antes de executar:

| Comando | Motivo |
|---------|--------|
| `rm -rf` (e variantes com `sudo`) | Deleção irreversível |
| `git push --force` / `--force-with-lease` | Reescrita de histórico publicado |
| `git reset --hard` | Descarta commits locais |
| `git checkout -- .` / `git restore` | Descarta alterações não commitadas |
| `git clean -f` | Descarta arquivos não rastreados |
| `git stash drop` / `git stash clear` | Descarta stashes irreversivelmente |
| `DROP TABLE` / `TRUNCATE TABLE` | DDL destrutivo |

O hook retorna `exit 2`, que o Claude Code interpreta como bloqueio. Claude não executa
o comando — reporta o bloqueio ao usuário para que ele decida como prosseguir.

> **Limitação:** a validação é baseada em texto. Comandos compostos via `eval`, `bash -c`
> ou variáveis indiretas não são interceptados. O hook é uma camada de proteção
> contra erros acidentais, não um controle de segurança rígido.

### `PostToolUse/Edit|Write|MultiEdit` → `sort-imports-on-edit.sh`

Após qualquer edição em arquivos `.py`, reordena automaticamente os imports
em ordem alfabética dentro de cada grupo (stdlib → externo → local).
Invoca `sortImports.py` que analisa o AST e reescreve o arquivo in-place.

### `PostToolUse/Edit|Write|MultiEdit` → `check-bash-syntax.sh`

Após qualquer edição em arquivos `.sh` ou `.bash`:
1. `bash -n` — verificação de sintaxe
2. `shellcheck` — análise estática profunda (se disponível)

Retorna feedback para Claude corrigir antes de continuar.

### `PostToolUse/Edit|Write|MultiEdit` → `check-python-style.sh`

Após qualquer edição em arquivos `.py`, detecta violações das convenções:

| Violação | Padrão esperado |
|----------|-----------------|
| f-strings | Use `.format()` |
| blocos `else` | Use early return |
| type hints em funções | Sem type hints |
| docstrings | Sem docstrings |

Retorna `{"decision":"block","reason":"..."}` com a lista de violações.

### `Stop` → `notify-done.sh`

Notificação macOS quando Claude termina uma tarefa longa. Silencioso em
ambientes sem `osascript` (Linux/CI).

Adicionalmente, verifica o banco de dados ao final de cada sessão. Se houver
tarefas `em andamento` ou `concluído` que precisam de manutenção, invoca
`tasks-maintainer` via `claude` CLI para atualizar TASKS.md automaticamente.
Falha do CLI é não-bloqueante — emite aviso e continua.

---

## Subagentes

Instâncias isoladas de Claude com ferramentas e modelo próprios. Úteis para
tarefas que geram muito output sem poluir o contexto principal.

### `support-investigator` (sonnet)

Investiga incidentes de produção cross-service. Rastreia fluxos de dados, forma no mínimo
3 hipóteses rankeadas por plausibilidade, coleta evidências para cada uma e determina o
root cause com nível de confiança (alta/média/baixa).

Invocado pelo `/support` na Fase 2 — não é chamado diretamente pelo usuário.
Nunca modifica arquivos.

**Output estruturado:**
- Hipóteses investigadas com evidências (`arquivo:linha`)
- Root cause com confiança e condição de ativação
- Commits relevantes (se houver)
- Recomendação: resolução N3 disponível ou requer N4

---

### `requirements-analyst` (sonnet)

Analisa descrições de features, identifica gaps de informação e valida requisitos
no formato EARS antes de `/spec`.

Para cada análise reporta:
- **GAPS IDENTIFICADOS**: o que está faltando e perguntas objetivas para elicitar
- **REQUISITOS EARS**: ubíquos, orientados a evento, orientados a estado, comportamentos indesejados, features opcionais
- **AVALIAÇÃO**: completo, ambíguos, não-testáveis

Não escreve código, spec ou testes.

**Como usar:**
```
Use the requirements-analyst agent to analyze: sistema de rate limiting por usuário
```

---

### `service-impact-analyzer` (sonnet)

Varre um único serviço em busca de referências a um alvo (campo, enum, função, contrato).
Invocado pelo `/blast-radius` em paralelo — uma instância por serviço.
Retorna um bloco estruturado de impacto. Nunca sintetiza nem determina ordem de deploy.

---

### `tasks-maintainer` (haiku)

Mantém `TASKS.md` de forma autônoma. Recebe uma descrição do trabalho concluído,
lê o estado atual de TASKS.md e aplica as atualizações necessárias:
atualiza status, move tasks concluídas para `## Histórico`.

Invocado pelo modelo principal ao final de qualquer trabalho concreto — sem pedido
do usuário. Também invocado automaticamente pelo Stop hook ao detectar tarefas que
precisam de manutenção no banco. Não executa código, não lê outros arquivos além de TASKS.md.

**Como usar (invocado pelo modelo, não pelo usuário):**
```
Use the tasks-maintainer agent to update TASKS.md: task T2 was completed — all hooks verified and pushed.
```

---

### `code-reviewer` (sonnet)

Revisão de código em três tiers: **MUST FIX** / **SHOULD FIX** / **NITPICK**.

Para arquivos de teste (`*Test.py`), avalia adicionalmente:
- Assertions triviais que passariam mesmo com implementação errada
- Testes excessivamente mockados
- Cenários ausentes (empty, None, boundary values)
- Rastreabilidade para critérios de aceite

**Como usar:**
```
Use the code-reviewer agent to review my changes in src/auth/
```

### `test-reviewer` (sonnet)

Avalia **qualidade de assertions** — não apenas cobertura. Para cada método de
teste reporta: `WEAK` / `ACCEPTABLE` / `STRONG` com justificativa.

Não executa testes. Não escreve código.

**Como usar:**
```
Use the test-reviewer agent to evaluate tests/parserTest.py
```

### `test-runner` (haiku)

Roda a suite de testes e reporta apenas falhas. Detecta o test runner do
projeto (pytest, jest, go test, etc.) automaticamente.

**Como usar:**
```
Use the test-runner agent to check if the tests pass
```

---

## Slash Commands

Invocados com `/nome` no prompt do Claude Code.

### `/requirements <descrição>`

Elicita e documenta requisitos no formato **EARS** (Easy Approach to Requirements Syntax).
Produz requisitos sem ambiguidade, testáveis e aprovados pelo usuário antes de qualquer
spec ou código.

Processo: lê contexto do projeto → identifica gaps → elicita informações faltantes →
gera requisitos nos 5 padrões EARS → valida completude → aguarda aprovação → registra em TASKS.md.

Não gera spec, testes ou código.

```
/requirements endpoint de criação de item com validação de duplicatas
/requirements sistema de rate limiting por usuário autenticado
```

### `/spec <descrição>`

Gera critérios de aceite no formato Dado/Quando/Então para uma funcionalidade.
Cada "Então" mapeia para exatamente um método de teste (`test<Cenário>_<Condição>`).

Quando chamado após `/requirements`, deriva os cenários dos requisitos EARS aprovados
mantendo rastreabilidade entre requisito e cenário.

Cobre: caminho feliz, inputs inválidos, valores de fronteira, erros esperados,
edge cases de autorização.

```
/spec endpoint de criação de item com validação de duplicatas
```

### `/review [branch ou commit]`

Revisão de changes recentes: corretude, segurança e cobertura de testes.

```
/review
/review main..feat/oauth
/review HEAD~3
```

Retorna: `MUST FIX | SHOULD FIX | NITPICK` com `file:line` e correção sugerida.

### `/security-review [branch ou path]`

Revisão focada em vulnerabilidades OWASP: injection, XSS, auth gaps, secrets
expostos, input validation, uso inseguro de `eval`/`exec`/`shell=True`.

```
/security-review
/security-review src/api/
```

Retorna: `file:line | HIGH/MEDIUM/LOW | issue | fix sugerido`.

### `/mutation-test [path]`

Executa `mutmut` no path especificado, mostra resultados e diagnostica cada
mutante sobrevivente como lacuna de teste ou mutante equivalente.

Meta: 100% de score. Mutantes equivalentes devem ser justificados com
`# pragma: no mutate`.

```
/mutation-test src/parser.py
```

### `/blast-radius <alvo>`

Analisa o impacto de mudar um campo, enum, função ou contrato em todos os
serviços da plataforma. Usa `SERVICE_MAP.md` para descobrir serviços e regras
de deploy.

```
/blast-radius CardStatus enum
/blast-radius campo purchase_amount no modelo Purchase
```

Retorna: serviços afetados, risco (LOW/MEDIUM/HIGH/CRITICAL) e ordem de deploy.

### `/investigate <problema>`

Investiga um bug ou comportamento inesperado rastreando o fluxo de dados
através dos serviços conforme o pipeline em `SERVICE_MAP.md`.

```
/investigate autorização falhando para cartões pré-pagos
/investigate saldo não atualiza após pagamento de fatura
```

Apresenta o que está acontecendo, por quê, quais arquivos, impacto cross-service
e sugestão de fix — sem implementar.

---

## Skills

Skills são workflows multi-fase com pontos de verificação explícitos.

### `/support`

Ciclo N3 completo para incidentes de produção em 4 fases:

| Fase | O que acontece |
|------|----------------|
| 1. Intake | Coleta estruturada do incidente (sintoma, impacto, timeline) |
| 2. Investigação | Invoca `support-investigator` para análise cross-service |
| 3. Gate | Apresenta root cause — decide N3-fix ou escalação N4 |
| 4a. Resolução N3 | Documenta workaround/rollback, fecha como concluído |
| 4b. Escalação N4 | Gera EARS do bug, registra em TASKS.md, indica `/bugfix` |

```
/support pagamentos falhando para cartões pré-pagos desde 14h
/support saldo não atualiza após pagamento de fatura
```

### `/bugfix`

Ciclo N4 completo para correção de bugs em 7 fases. A ordem é fixa:
**reproduzir antes de corrigir** — o teste de regressão deve falhar antes da implementação.

| Fase | O que acontece |
|------|----------------|
| 0. Root cause | Lê escalação do `/support` ou coleta diretamente |
| 1. Regressão | Escreve teste que **reproduz o bug e falha** |
| 2. EARS | Requisitos do fix (lê de TASKS.md ou deriva do root cause) |
| 3. Spec | Given/When/Then derivado dos EARS |
| 4. Implementação | Código mínimo para o teste de regressão passar |
| 5. Mutação | `mutmut` — 100% exigido |
| 6. Blast radius | `/blast-radius` antes do merge |
| 7. Checklist | Rastreabilidade, convenções, commit |

```
/bugfix T12 — saldo não atualiza após pagamento de fatura
/bugfix validação de duplicata falhando no endpoint de criação
```

### `/verify-delivery`

Checklist pré-merge em 7 passos. Obrigatório antes de declarar qualquer tarefa concluída.

| Passo | O que verifica |
|-------|----------------|
| 1. Mudanças | `git diff --name-only` |
| 2. Convenções | `verify.py --git` — f-strings, else, naming, trailing comma, forbidden files |
| 3. Estrutura | Arquitetura, padrões, cross-service (julgamento) |
| 4. Testes | Suite completa + cobertura de novos comportamentos |
| 5. Cobertura | `--cov` conforme configuração do projeto |
| 6. Security | `security-review` agent em paralelo — HIGH findings bloqueiam o VERDICT |
| 7. Git hygiene | Mensagem de commit, arquivos proibidos, nome do branch |

Saída: `READY` ou `NOT READY` — nunca `READY` com qualquer check falhando ou HIGH security finding.

```
/verify-delivery
```

### `/feature`

Workflow end-to-end para features novas em 5 fases, com rastreabilidade total:

| Fase | O que acontece |
|------|----------------|
| 0. Requirements | Requisitos EARS (aguarda aprovação) |
| 1. Spec | Deriva Given/When/Then dos requisitos (aguarda aprovação) |
| 2. Testes | Escreve testes que **devem falhar** |
| 3. Implementação | Código mínimo para passar os testes |
| 4. Mutação | `mutmut` — 100% exigido |
| 5. Checklist | Verifica convenções e rastreabilidade |

Use `/feature` como ponto de entrada para qualquer feature nova.
Use `/tdd` quando requisitos e spec já existem e aprovados.

```
/feature endpoint de criação de item com validação de duplicatas
```

### `/tdd`

Workflow TDD completo em 5 fases. Assume que requisitos EARS e spec já existem
e foram aprovados — inicia diretamente na geração de critérios de aceite.

| Fase | O que acontece |
|------|----------------|
| 1. Spec | Gera critérios de aceite (aguarda aprovação) |
| 2. Testes | Escreve testes que **devem falhar** |
| 3. Implementação | Código mínimo para passar os testes |
| 4. Mutação | `mutmut` — 100% exigido |
| 5. Checklist | Verifica convenções antes de commitar |

```
/tdd endpoint de criação de item
```

### `/cross-service-analysis`

Análise completa de impacto cross-service em 5 passos: identifica o alvo,
busca referências em todos os serviços, classifica cada hit por criticidade,
determina ordem de deploy e apresenta o resultado estruturado.

Requer `SERVICE_MAP.md` preenchido com os serviços da plataforma.

```
/cross-service-analysis remover campo legacy_id do modelo Card
```

---

## Configuração Cross-Service

Para projetos com múltiplos serviços, preencha
`.claude/skills/cross-service-analysis/SERVICE_MAP.md` com:

- Lista de serviços e seus diretórios
- Grafo de dependências (qual serviço chama qual)
- Contratos compartilhados (enums, mensagens de fila, schemas de API)
- Regras de deploy específicas da plataforma

Sem esse arquivo preenchido, os comandos `/blast-radius`, `/investigate` e a
skill `/cross-service-analysis` operam sem contexto da plataforma.

---

## Instalação

### 1. Instalar dependências

```bash
./setup.sh
```

Verifica e instala as dependências, torna os hooks executáveis e reporta o que
está faltando. É idempotente — pode rodar múltiplas vezes.

### 2. Configurar o projeto

```bash
./configure.sh
```

Script interativo que preenche os placeholders nos arquivos de configuração.
Faz 4 perguntas:

| Pergunta | Arquivo | Campo |
|----------|---------|-------|
| Pacotes locais do projeto | `pyproject.toml` | `known-first-party` |
| Diretório do código-fonte | `mutmut.toml` | `paths_to_mutate` |
| Diretório de testes | `mutmut.toml` | `tests_dir` |
| Serviços da plataforma (opcional) | `SERVICE_MAP.md` | serviços e diretórios |

Idempotente — ao re-executar, mostra o valor atual e permite manter ou sobrescrever.
Ao finalizar, executa `./setup.sh` automaticamente para confirmar que a configuração passou.

### Dependências

| Ferramenta | Obrigatório | Usado em | Instalação |
|------------|-------------|----------|------------|
| `git` | sim | `inject-git-context.sh` | https://git-scm.com |
| `python3` | sim | testes e linting | `brew install python3` |
| `jq` | sim | hooks (parse JSON) | `brew install jq` |
| `shellcheck` | não | `check-bash-syntax.sh` | `brew install shellcheck` |
| `ruff` | não | `check-python-style.sh` | `pip3 install ruff` |
| `mutmut` | não | `/mutation-test`, `/tdd` | `pip3 install mutmut` |
| `osascript` | não | `notify-done.sh` | nativo macOS |

---

## Adicionando ao seu projeto

Para usar este ambiente em outro projeto:

```bash
cp -r .claude/ /caminho/do/seu-projeto/
cp setup.sh configure.sh mutmut.toml pyproject.toml /caminho/do/seu-projeto/
echo ".claude/settings.local.json" >> /caminho/do/seu-projeto/.gitignore
cd /caminho/do/seu-projeto
./setup.sh
./configure.sh
```

Os hooks usam caminhos relativos e funcionam de qualquer projeto.
