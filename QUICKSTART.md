# Guia de Uso Rápido

## Instalação

```bash
rm -rf /tmp/cce-guide && git clone --depth 1 https://github.com/alexandrelima-starkbank/claude-code-engineering-guide.git /tmp/cce-guide && bash /tmp/cce-guide/install.sh
```

Executa uma vez por projeto. Idempotente — pode re-executar para atualizar.

---

## Como funciona

**Você não precisa saber nenhum comando.** Descreva o que precisa em linguagem natural.
O modelo classifica a intenção, consulta o histórico do projeto, faz as perguntas
necessárias para eliminar ambiguidade e conduz o processo internamente.

```
Você:    "preciso validar CPF antes de criar um cartão"
Modelo:  classifica como `feature` → entrevista → produz EARS → conduz toda a pipeline
```

---

## A Pipeline (EBTM)

Todo trabalho passa por estas fases **em ordem** — nenhuma pode ser pulada:

| Fase | O que acontece |
|------|---------------|
| `requirements` | Requisitos EARS elicitados, aprovados e avaliados por quality scoring |
| `spec` | Cenários Given/When/Then derivados dos EARS e aprovados |
| `plan` | Escopo técnico: arquivos e componentes aprovados pelo engenheiro |
| `tests` | Testes escritos (falham primeiro), qualidade avaliada |
| `implementation` | Código mínimo para os testes passarem (scope enforcement ativo) |
| `mutation` | Mutation score 100% — sem gaps de teste |
| `done` | Auditoria READY, tarefa concluída |

O banco de dados registra cada transição com timestamp. Nada é perdido.

---

## Comandos úteis

### Visão geral do dia
```
/daily
```
Um bullet por tarefa — o que está em andamento, pendente e o que foi concluído ontem.

### Estado detalhado de uma tarefa
```
/pipeline-audit T1
```
Mostra cada gate (PASS/FAIL), matriz de rastreabilidade EARS→teste→resultado e histórico de fases.

### Iniciar uma feature do zero
```
/feature adicionar suporte a cartão virtual
```

### Ciclo TDD a partir de uma spec aprovada
```
/tdd T3
```

### Code review
```
/review
```

### Verificar antes de mergear
```
/verify-delivery
```

---

## Comandos da pipeline (quando necessário)

O modelo executa estes automaticamente. Use diretamente só se precisar inspecionar ou corrigir.

```bash
pipeline task list                          # todas as tarefas
pipeline task show T1                       # detalhes + matriz de rastreabilidade
pipeline audit T1                           # gates PASS/FAIL
pipeline ears list T1                       # requisitos EARS
pipeline criterion list T1                  # critérios de aceite
pipeline context search "autenticação"      # busca semântica no histórico
pipeline export metrics                     # métricas agregadas de todos os projetos
```

---

## Fluxo típico de uma feature

```
1. Engenheiro descreve a necessidade em linguagem natural
2. Modelo conduz Intake Protocol → cria tarefa no banco
3. Modelo elicita EARS → avalia quality scores → engenheiro aprova
4. Modelo deriva spec BDD → engenheiro aprova
5. Modelo propõe plano técnico (arquivos + componentes) → engenheiro aprova
6. Modelo escreve testes (falham) → avalia qualidade
7. Modelo implementa o mínimo → testes passam (scope enforcement ativo)
8. Modelo roda mutmut → 100% score
9. /pipeline-audit T<N> → READY ✓ → merge
```

Resultados de pytest e mutmut são registrados automaticamente no banco pelos hooks.
O TASKS.md é regenerado após cada operação — não edite diretamente.

---

## O que o ambiente garante automaticamente

| Situação | O que acontece |
|----------|---------------|
| Nenhuma tarefa ativa | Modelo executa Intake Protocol antes de qualquer trabalho |
| Tentativa de implementar sem EARS aprovados | Hook bloqueia e redireciona |
| Tentativa de escrever testes sem critérios aprovados | Hook bloqueia e redireciona |
| `pytest` executado | Resultados registrados no banco automaticamente |
| `mutmut` executado | Score registrado no banco automaticamente |
| Resposta concluída com tarefa ativa | Modelo é lembrado de atualizar o status |
| Avanço `tests → implementation` | Gate verifica qualidade dos testes (ACCEPTABLE/STRONG) |

---

## Dúvidas e inspeção

```bash
pipeline audit          # audita todas as tarefas do projeto
/pipeline-audit T1      # auditoria detalhada de uma tarefa específica
```

Para qualquer dúvida sobre o ambiente, pergunte diretamente ao modelo — ele conhece
o estado atual via banco de dados e o contexto semântico via ChromaDB.
