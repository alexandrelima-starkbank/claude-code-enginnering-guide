# Catálogo de Capacidades

Consulte este catálogo para selecionar autonomamente o entry point correto para cada contexto.
Cada entry point tem responsabilidade única — escolha o mais específico para o problema em mãos.

---

## Intake

O engenheiro descreve em linguagem natural. O modelo classifica, consulta ChromaDB,
entrevista e roteia. Slash commands são internos — nunca exigidos do engenheiro.

Protocolo completo: `CLAUDE.md → Intake Protocol`

---

## Planejamento

| Entry point | Quando usar | Precisa de | Produz |
|---|---|---|---|
| `/requirements` | Problema em linguagem natural, sem requisitos formalizados | Descrição do problema | Requisitos EARS gravados no DB + quality scores + fase avançada para spec |
| `/spec` | EARS aprovados no DB, falta critério de aceite | Task com EARS aprovados | Cenários Given/When/Then gravados no DB + fase avançada para plan |
| `/pipeline-audit` | Verificar estado completo de uma tarefa | Task ID | PASS/FAIL por gate + rastreabilidade + métricas |

---

## Desenvolvimento

| Entry point | Quando usar | Precisa de | Produz |
|---|---|---|---|
| `/feature` | Feature nova do zero, sem requisitos definidos | Descrição da feature | EARS + spec + testes + código implementado |
| `/tdd` | Spec aprovada em TASKS.md, implementação não iniciada | Spec em TASKS.md | Código testado com mutation score 100% |
| `/verify-delivery` | Antes de qualquer merge ou declaração de conclusão | Mudanças locais | Checklist READY / NOT READY (inclui security-review em paralelo) |

---

## Qualidade

| Entry point | Quando usar | Precisa de | Produz |
|---|---|---|---|
| `/review` | Code review de changes específicas | Branch ou commit | MUST FIX / SHOULD FIX / NITPICK por arquivo:linha |
| `/security-review` | Auditoria focada em vulnerabilidades | Branch ou path | HIGH / MEDIUM / LOW com arquivo:linha e fix |
| `/mutation-test` | Diagnóstico de mutantes sobreviventes | Arquivo Python | Score + classificação de cada sobrevivente |

---

## Suporte (N3/N4)

| Entry point | Quando usar | Precisa de | Produz |
|---|---|---|---|
| `/support` | Sintoma de produção, root cause desconhecido | Descrição do sintoma | Root cause + decisão N3/N4 + EARS do bug |
| `/bugfix` | Root cause conhecido, fix de código necessário | Root cause + EARS em TASKS.md | Fix com teste de regressão + checklist de deploy |

---

## Análise de Impacto

| Entry point | Quando usar | Precisa de | Produz |
|---|---|---|---|
| `/blast-radius` | Avaliar impacto pontual de uma mudança | Alvo (campo, enum, função) | Serviços afetados, risco e ordem de deploy — **fan-out paralelo por serviço** |
| `/investigate` | Rastrear a causa de um comportamento específico | Descrição do problema | Fluxo de dados, arquivos envolvidos, sugestão de fix |
| `/cross-service-analysis` | Análise completa de impacto cross-service | Descrição da mudança | Análise detalhada + plano de deploy coordenado |

---

## Busca e Exploração de Código

Quatro mecanismos complementares — escolha pelo tipo de pergunta:

| Mecanismo | Quando usar | Comando |
|---|---|---|
| `pipeline search` | Busca semântica: "o que faz X?", "onde está Y?" — retorna arquivos por similaridade de embedding | `pipeline search "<termo>" --n 15` |
| `pipeline context search` | Buscar decisões arquiteturais e EARS anteriores | `pipeline context search "<decisão>"` |
| `codegraph` MCP | Análise estrutural: grafo de chamadas, dependências, impacto de função, entrypoints — usa análise sintática (AST), não semântica | `codegraph_search`, `codegraph_dependencies`, `codegraph_impact` |
| `semanticode` MCP | Busca semântica avançada direta no servidor local (alternativa ao `pipeline search` quando ChromaDB está ativo) | `semanticode_analyze` |
| `grep` / Bash | Busca exata: string literal, nome de função, import específico — mais rápido quando o alvo é conhecido | `grep -r "nomeDaFuncao" .` |

**Regra de escolha:** se você sabe o nome exato → grep. Se quer entender o que algo faz ou encontrar implementações similares → `pipeline search`. Se quer traçar o grafo de chamadas ou dependências estruturais → `codegraph`. Se quer cruzar com decisões anteriores → `pipeline context search`.

---

## Agentes disponíveis (invocados internamente)

| Agente | Invocado por | Responsabilidade |
|---|---|---|
| `requirements-analyst` | `/requirements` em casos complexos | Valida completude e ambiguidade de requisitos EARS |
| `support-investigator` | `/support` Fase 2 | Investigação cross-service, root cause com confiança |
| `code-reviewer` | `/review`, `/verify-delivery` — em paralelo com `test-runner` | Review em 3 tiers: MUST / SHOULD / NITPICK |
| `test-runner` | `/verify-delivery` — em paralelo com `code-reviewer` | Executa suite e reporta falhas de forma concisa |
| `service-impact-analyzer` | `/blast-radius` — N instâncias em paralelo, uma por serviço | Varre um serviço e retorna bloco estruturado de impacto |
| `test-reviewer` | Antes de concluir qualquer tarefa | Avalia qualidade de assertions: WEAK / ACCEPTABLE / STRONG |
| `tasks-maintainer` | Final de sessão (Stop hook) ou conclusão de tarefa | Atualiza TASKS.md e move concluídos para HISTORY_TASKS.md |
| `adversarial-reviewer` | `pipeline phase advance` para `plan`, `implementation`, `mutation` | Identifica pontos de decisão genuínos (>1 solução válida sem convenção); apresenta opções com argumentos neutros e bloqueia avanço até resolução pelo engenheiro |
| `static-analysis` (gate, não agente) | `pipeline phase advance` para `static-analysis` | Auto-invoca ruff, bandit, vulture, pylint, radon (CC + MI) sobre arquivos do diff; bloqueia avanço se thresholds violados (0 violações para os primeiros, CC ≤ 10, MI ≥ 65) |
