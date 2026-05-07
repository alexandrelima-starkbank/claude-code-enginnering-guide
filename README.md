# Claude Code Engineering Environment

Ambiente de desenvolvimento para times Python que usam Claude Code como agente de implementação. Resolve o problema central do desenvolvimento com LLMs: **o modelo age antes de entender, implementa sem critérios claros e deriva do escopo sem que ninguém perceba**.

O ambiente não acelera a digitação de código — ele impõe um processo que garante que o código produzido por agentes seja correto, rastreável e dentro do escopo combinado.

---

## Por que este ambiente existe

Agentes LLM cometem erros diferentes dos humanos: assumem sem verificar, não buscam clarificação, inflam abstrações, alteram código ortogonal à tarefa e implementam sem critérios de aceite definidos. Essas falhas são difíceis de detectar porque o código produzido parece correto sintaticamente.

Este ambiente endereça cada um desses pontos com mecanismos concretos — hooks, gates de fase, análise estática e um segundo modelo avaliando a qualidade dos requisitos — antes que qualquer linha de código seja escrita.

---

## O que este ambiente é

- Um **processo de desenvolvimento estruturado** para trabalho com agentes LLM
- Uma **pipeline de qualidade** com gates obrigatórios entre fases (EARS → spec → plan → tests → implementation → mutation → done)
- Um **conjunto de guardrails ativos** que bloqueiam em tempo real ações fora do escopo, convenções violadas e avanços prematuros
- Uma **base de rastreabilidade** que conecta cada linha de código a um requisito aprovado

## O que este ambiente não é

- Um substituto para revisão humana de código
- Um framework de observabilidade de runtime (logs, traces, erros de produção)
- Um ambiente de execução isolado (sandbox, containers)
- Uma ferramenta genérica — é opinado e projetado para times que adotam TDD rigoroso com convenções explícitas

---

## Quick Start

```bash
rm -rf /tmp/cce-guide \
  && git clone --depth 1 https://github.com/alexandrelima-starkbank/claude-code-engineering-guide.git /tmp/cce-guide \
  && bash /tmp/cce-guide/install.sh
```

Detecta o contexto (projeto único ou workspace), instala dependências, configura `pyproject.toml` e `mutmut.toml` e ativa os hooks. Idempotente — seguro de rodar múltiplas vezes.

Para atualizar um ambiente já instalado: `/update`

---

## Pipeline de desenvolvimento

O ambiente impõe um ciclo de vida obrigatório para qualquer feature, bug ou refactor:

```
Linguagem natural
  → Intake (classificação + entrevista)
  → EARS (requisitos formais)          ← quality score por segundo modelo
  → Spec (critérios BDD + testMethod)
  → Plan (escopo de arquivos + componentes)
  → Tests (falham antes da implementação)
  → Implementation                      ← scope enforcement em tempo real
  → Mutation testing (100% obrigatório)
  → Done
```

Cada transição de fase é bloqueada por gates verificáveis. Nenhuma fase pode ser pulada.

---

## Aspectos fortes

**Requisitos antes de código.** O `enforce-intake-protocol.sh` impede que o modelo escreva qualquer código sem EARS aprovados. Um segundo modelo (`evaluateQuality`) avalia os requisitos em 8 dimensões antes da aprovação.

**Scope enforcement em tempo real.** O `check-scope.sh` bloqueia edições em arquivos fora do plano aprovado durante a implementação. Deriva de escopo é detectada antes do merge, não depois.

**Test-first enforçado.** O modelo não avança para implementation sem testes passando. Mutation testing com 100% de score obrigatório garante que os testes detectariam bugs reais.

**Anti-bloat estático.** `checkUntracedSymbols` flagra classes sem rastreabilidade a nenhum EARS. `checkDeadAbstractions` flagra funções e classes definidas mas não referenciadas no codebase.

**Convenções ativas, não passivas.** Hooks PostToolUse rejeitam violações das convenções do time em tempo real — não em PR review. As convenções são configuráveis via `CONVENTIONS.starkbank.md` e `check-python-style.sh`.

**Rastreabilidade completa.** Pipeline DB SQLite conecta cada critério de aceite ao seu EARS, ao seu teste e ao mutation score. `pipeline audit T<N>` exibe o estado completo de qualquer tarefa.

---

## O que está incluído

### Hooks

Executam automaticamente em resposta a eventos do Claude Code. Não requerem interação do engenheiro.

**Intake e processo**

| Hook | Evento | Função |
|------|--------|--------|
| `enforce-intake-protocol.sh` | UserPromptSubmit | Bloqueia o modelo de agir sem tarefa ativa e EARS aprovados |
| `validate-requirements.sh` | UserPromptSubmit | Rejeita EARS ambíguos antes de gravar no banco |
| `inject-tasks-context.sh` | UserPromptSubmit | Injeta tarefas ativas no contexto da sessão |
| `inject-git-context.sh` | SessionStart | Injeta branch, commits recentes e arquivos modificados |
| `check-for-update.sh` | SessionStart | Notifica quando há nova versão do ambiente disponível |

**Qualidade e convenções**

| Hook | Evento | Função |
|------|--------|--------|
| `check-python-style.sh` | PostToolUse (Edit/Write) | Rejeita violações das convenções do time em tempo real |
| `sort-imports-on-edit.sh` | PostToolUse (Edit/Write) | Ordena imports automaticamente após cada edição |
| `check-bash-syntax.sh` | PostToolUse (Edit/Write) | Valida sintaxe de scripts Bash após cada edição |
| `check-scope.sh` | PreToolUse (Edit/Write) | Bloqueia edições em arquivos fora do plano aprovado |
| `validate-destructive.sh` | PreToolUse (Bash) | Intercepta comandos destrutivos e exige confirmação |
| `pre-commit-gate.sh` | PreToolUse (Bash) | Executa checklist de qualidade antes de qualquer commit |

**Integração com pipeline**

| Hook | Evento | Função |
|------|--------|--------|
| `record-test-results.sh` | PostToolUse (Bash) | Detecta resultados de pytest e grava no banco automaticamente |
| `record-mutation-results.sh` | PostToolUse (Bash) | Detecta scores de mutmut e grava no banco automaticamente |
| `notify-done.sh` | Stop | Notifica ao fim de cada sessão |
| `mark-session-start.sh` | SessionStart | Registra início de sessão no banco |

---

### Agentes

Subagentes especializados invocados internamente por skills e slash commands. Nunca modificam arquivos — apenas leem, analisam e reportam.

| Agente | Responsabilidade |
|--------|-----------------|
| `requirements-analyst` | Valida completude e ausência de ambiguidade em requisitos EARS |
| `code-reviewer` | Review em 3 tiers: MUST FIX / SHOULD FIX / NITPICK, por arquivo:linha |
| `test-reviewer` | Avalia força das assertions: WEAK / ACCEPTABLE / STRONG — não se os testes passam, mas se detectariam bugs reais |
| `test-runner` | Executa a suite de testes e reporta apenas falhas, preservando o contexto principal |
| `tasks-maintainer` | Atualiza TASKS.md e move tarefas concluídas para HISTORY_TASKS.md |
| `support-investigator` | Investiga incidentes cross-service, rastreia fluxos de dados e determina root cause com nível de confiança |
| `service-impact-analyzer` | Varre um serviço em busca de referências a um alvo — invocado em paralelo, uma instância por serviço |

---

### Slash Commands

Entry points para fluxos de trabalho invocados pelo engenheiro em linguagem natural.

**Planejamento e requisitos**

| Comando | Quando usar |
|---------|------------|
| `/requirements` | Elicitar e formalizar requisitos EARS a partir de uma descrição em linguagem natural |
| `/spec` | Gerar critérios de aceite BDD (Given/When/Then) a partir de EARS aprovados |
| `/pipeline-audit` | Auditar estado completo de uma tarefa — gates, rastreabilidade, métricas |

**Desenvolvimento**

| Comando | Quando usar |
|---------|------------|
| `/feature` | Desenvolvimento end-to-end de uma feature nova, do zero |
| `/tdd` | Ciclo TDD com spec aprovada — testes primeiro, depois implementação |
| `/verify-delivery` | Checklist pré-merge: convenções, review e testes em paralelo |

**Qualidade**

| Comando | Quando usar |
|---------|------------|
| `/review` | Code review de mudanças recentes em 3 tiers |
| `/security-review` | Auditoria focada em vulnerabilidades com severidade e localização |
| `/mutation-test` | Diagnóstico de mutantes sobreviventes com classificação e sugestão de fix |

**Suporte e análise**

| Comando | Quando usar |
|---------|------------|
| `/support` | Ciclo N3/N4 para incidentes de produção com root cause e decisão de escalada |
| `/blast-radius` | Avaliar impacto cross-service de uma mudança em campo, enum ou função |
| `/investigate` | Rastrear a causa de um comportamento inesperado sem implementar |

**Operacional**

| Comando | Quando usar |
|---------|------------|
| `/daily` | Resumo das tarefas ativas e concluídas nas últimas 24h |
| `/my_tasks` | Listar tarefas com filtros de status, limite e ordem |
| `/update` | Atualizar o ambiente para a versão mais recente do repositório |

---

### Skills

Workflows completos que orquestram múltiplos agentes, comandos e gates de fase.

| Skill | Função |
|-------|--------|
| `feature` | EARS → spec → plan → testes → implementação — orquestração end-to-end |
| `tdd` | Ciclo TDD completo: testes falham primeiro, implementação, mutation 100% |
| `verify-delivery` | Code review + execução de testes em paralelo, resultado READY / NOT READY |
| `bugfix` | Reproduz o bug, escreve teste de regressão, implementa fix, verifica mutation |
| `support` | Investigação cross-service com hipóteses rankeadas e decisão N3/N4 |
| `cross-service-analysis` | Análise detalhada de impacto com plano de deploy coordenado |

---

### Pipeline CLI

Interface de linha de comando para gerenciar o ciclo de vida completo de tarefas. Banco SQLite local em `~/.claude/pipeline/pipeline.db`.

| Grupo | Subcomandos | Função |
|-------|------------|--------|
| `pipeline task` | `create`, `update`, `list`, `show` | Criar e gerenciar tarefas |
| `pipeline ears` | `add`, `approve`, `list` | Registrar e aprovar requisitos EARS |
| `pipeline criterion` | `add`, `approve`, `list`, `set-quality` | Critérios de aceite BDD |
| `pipeline plan` | `create`, `approve`, `show` | Artefatos de planejamento com escopo e quality scores |
| `pipeline phase` | `advance`, `check` | Avançar fases com validação de gates |
| `pipeline test` | `record`, `list` | Registrar resultados de testes |
| `pipeline mutation` | `record` | Registrar scores de mutation testing |
| `pipeline search` | — | Busca semântica no código via embeddings |
| `pipeline context` | `add`, `search` | Decisões arquiteturais persistidas entre sessões |
| `pipeline audit` | — | Auditoria completa de uma tarefa |
| `pipeline export` | — | Exportar dados do banco |

---

## Guia de Claude Code para Engenharia

Filosofia, setup, CLAUDE.md, hooks, prompt engineering, fluxo agêntico, MCP, tool use, otimização e referência de modelos:

**[GUIDE.md](GUIDE.md)**

---

## Arquitetura

Diagramas visuais do ambiente — componentes, hooks, pipeline, fluxos:

**[ARCHITECTURE.md](ARCHITECTURE.md)**

---

## Documentação do Ambiente

Documentação detalhada de cada hook, agente, comando e skill:

**[.claude/README.md](.claude/README.md)**

---

## Licença

[Apache 2.0](LICENSE)
