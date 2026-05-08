# Pipeline de Engenharia — Metodologia Formal

## Nome

**EBTM** — Easy Requirements → Behavior-Driven → Test-Driven → Mutation Verified

---

## Fundamento

Toda entrega de software neste ambiente segue um pipeline com fases ordenadas, gates verificáveis
e rastreabilidade total entre requisito, cenário, teste e código. A pipeline é executada
pelo modelo, auditada via `pipeline audit`, e documentada automaticamente no banco de dados.

---

## Fases e Invariantes

```
requirements → spec → plan → tests → implementation → mutation → done
```

| Fase | Invariante para avançar | Métrica coletada |
|------|------------------------|-----------------|
| `requirements` | ≥1 EARS aprovado, quality scores registrados | N requisitos, N aprovados |
| `spec` | ≥1 cenário por EARS, todos aprovados, test method mapeado | N cenários, ratio por requisito |
| `plan` | plan aprovado com scope de arquivos e componentes | N arquivos, N componentes |
| `tests` | todos os métodos existem no código, todos falham antes da implementação | N testes, N falhando |
| `implementation` | todos os testes passam | N testes, N passando |
| `mutation` | mutation score 100% (exceto equivalentes justificados) | N mutantes, N mortos, score |
| `done` | todos os gates anteriores PASS, tarefa concluída | — |

---

## Papéis

| Quem | Responsabilidade |
|------|-----------------|
| **Engenheiro** | Descreve em linguagem natural. Aprova EARS. Aprova spec BDD. Decide mutantes sobreviventes. |
| **Modelo** | Classifica intent, entrevista, escreve no DB, implementa, avança fases, registra métricas. |
| **Ambiente** | Detecta execuções de pytest/mutmut e auto-registra resultados. Regenera TASKS.md após writes. |

Os únicos toques humanos obrigatórios são:
1. Aprovação dos EARS (gate requirements → spec)
2. Aprovação da spec BDD (gate spec → tests)
3. Decisão sobre mutantes sobreviventes (gap vs. equivalente)

---

## Gates

Transição de fase é irreversível via CLI. O comando `pipeline phase advance` rejeita saltos:

```
requirements → spec      requer: EARS aprovados + quality scores registrados
spec → plan              requer: critérios aprovados, test methods mapeados; adversarial-reviewer libera (gate spec_plan)
plan → tests             requer: plan aprovado (blast-radius advisory exibido)
tests → implementation   requer: testes executados; adversarial-reviewer libera (gate tests_impl)
implementation → mutation requer: todos os testes passando; adversarial-reviewer libera (gate impl_mutation)
mutation → static-analysis requer: mutation score = 100%; análise estática auto-invocada (ruff, bandit, vulture, pylint, radon CC + MI)
static-analysis → done   requer: ruff/bandit/vulture/pylint = 0 violações, CC ≤ 10, MI ≥ 36 — todos com run passing
```

### Static Analysis Gate

Ao avançar `mutation → static-analysis`, o sistema executa automaticamente análise sobre os arquivos
do diff `git diff development...HEAD` (excluindo arquivos de teste do CC). Thresholds:

| Ferramenta | Métrica | Threshold |
|---|---|---|
| ruff | violations | = 0 |
| bandit | violations | = 0 |
| vulture | dead code | = 0 |
| pylint | smells | = 0 |
| radon (CC) | máx por bloco | ≤ 10 |
| radon (MI) | mín por arquivo | ≥ 36 (calibrado para convenção sem comentários) |

Resultados persistidos em `staticAnalysisResults`. Divergência entre `git diff` e `planScope`
é exibida como advisory (não bloqueia).

Em cada um dos três gates de revisão adversarial (`spec_plan`, `tests_impl`, `impl_mutation`),
o agente `adversarial-reviewer` é invocado automaticamente. Se identificar pontos de decisão
genuínos (mais de uma solução válida sem convenção que defina o caminho), o gate bloqueia
até o engenheiro resolver via:

```bash
pipeline decision resolve T<N> --point D01 --choice "<texto>" --rationale "<justificativa>"
```

A decisão é persistida no ChromaDB como contexto arquitetural.

---

## Rastreabilidade

Cada artefato é vinculado ao anterior:

```
EARS R01
  └── Cenário C01 (earsId = R01)
        └── testCreate_Success (testMethod)
              └── Resultado: ✓ passou (testResults)
              └── Mutation: 5/5 mortos (mutationResults)
```

Verificar via: `pipeline audit T<N>`

---

## Métricas por Tarefa

Consultáveis a qualquer momento:

```bash
pipeline audit T<N>          # gates + rastreabilidade + histórico de fases
pipeline export metrics      # dashboard agregado por projeto
pipeline task show T<N>      # view completa com matriz de rastreabilidade
```

---

## Comandos CLI de Referência

```bash
# Ciclo completo de uma feature
pipeline task create --title "..." [--project "..."]   # → T<N>
pipeline ears add T<N> --pattern event --text "..."    # → R01
pipeline ears approve T<N> all
pipeline phase advance T<N> --to spec
pipeline criterion add T<N> --ears R01 --scenario "..." --then "..." --test "testXxx_Yyy"
pipeline criterion approve T<N> all
pipeline phase advance T<N> --to tests
# ... escrever testes, implementar ...
pipeline test record T<N> --method testXxx_Yyy --passed
pipeline phase advance T<N> --to implementation
pipeline phase advance T<N> --to mutation
pipeline mutation record T<N> --total 8 --killed 8
pipeline phase advance T<N> --to done
pipeline task update T<N> --status "concluído"

# Auditoria
pipeline audit T<N>
pipeline audit

# Contexto semântico
pipeline context add --text "decisão sobre autenticação..." --type decision --task T<N>
pipeline context search "autenticação jwt"
```

---

## Banco de Dados

- SQLite: `~/.claude/pipeline/pipeline.db` — estado estruturado, auditável
- ChromaDB: `~/.claude/pipeline/chroma/` — embeddings semânticos (opcional)

TASKS.md é uma **view gerada** do banco — não editar diretamente.
