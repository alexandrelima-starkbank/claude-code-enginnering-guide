---
name: verify-delivery
description: Checklist pré-merge completo — convenções, estrutura, testes, segurança e git hygiene. Use após qualquer implementação, antes de commitar ou declarar a tarefa concluída.
---

# Verify Delivery

Checklist pré-merge. Obrigatório antes de declarar qualquer tarefa concluída.

---

## Passo 1 — Identificar o que mudou

```bash
git diff --name-only
```

---

## Passo 2 — Verificação de convenções (determinística)

Rodar o verificador em todos os arquivos Python modificados:

```bash
python3 .claude/skills/verify-delivery/scripts/verify.py --git
```

Checks executados pelo script:

| Regra | O que detecta |
|-------|---------------|
| `NO-FSTRING` | f-strings — usar `.format()` |
| `NO-ELSE` | blocos `else` — usar early return |
| `NAMING` | funções em snake_case — usar camelCase |
| `TRAILING-COMMA` | vírgula ausente no último argumento de multilinha |
| `FORBIDDEN-FILE` | arquivo que não deve ser commitado |

Se houver violações, corrigir antes de continuar.

---

## Passo 3 — Verificação estrutural (julgamento)

Para cada arquivo alterado, verificar:

**Arquitetura:**
- A responsabilidade do arquivo está correta dentro da estrutura do projeto?
- Nenhuma lógica de negócio em camada errada?
- Nenhum código de debug ou script local commitado?

**Convenções não cobertas pelo script:**
- Imports na ordem correta: stdlib → externo → local?
- Nenhum type hint em funções?
- Nenhuma docstring?

**Cross-service (se aplicável):**
- Mudanças em enums, contratos de queue ou campos compartilhados verificadas em todos os serviços afetados?
- Ordem de deploy documentada se mudança for multi-serviço?

---

## Passo 4 — Testes

```bash
python3 -m pytest -v
```

Verificar:
- Todos os testes passam
- Nenhum teste existente foi modificado para acomodar o novo comportamento
- Código novo ou alterado tem cobertura de teste correspondente
- Nomenclatura correta: arquivo `<Domínio>Test.py`, classe `<Domínio>Test`, método `test<Cenário>_<Condição>`

Se testes falharem, corrigir a implementação — nunca os testes.

---

## Passo 5 — Cobertura (se configurado)

```bash
python3 -m pytest --cov=<módulos-do-projeto>
```

O comando exato está em `pyproject.toml` ou no `CLAUDE.md` do projeto.
Pular este passo se cobertura não estiver configurada.

---

## Passo 6 — Security review (paralelo)

Invocar o agente `security-review` em paralelo com os agentes `code-reviewer` e `test-runner` do Passo 4.
Não aguardar o resultado do security-review para iniciar os outros agentes.

Interpretar o resultado:

| Resultado | Ação |
|-----------|------|
| Nenhum finding | SECURITY: PASS |
| Somente MEDIUM e/ou LOW | SECURITY: lista os findings — não bloqueia o VERDICT |
| Pelo menos um HIGH | SECURITY: lista os findings — VERDICT obrigatoriamente NOT READY |
| Agente falha ou não responde | SECURITY: SKIPPED — não bloqueia o VERDICT |

---

## Passo 7 — Git hygiene

- Mensagem de commit: verbo imperativo, capitalizado, sem ponto final, sem emoji, sem `Co-Authored-By`
- Nenhum arquivo proibido: `main_local.py`, `query_dev.py`, `test_local.sh`, `it_tests/`
- Nome do branch descritivo: `feat/`, `fix/`, `chore/`

---

## Formato de saída

```
VERIFY DELIVERY
Task: <descrição>

CONVENTIONS:
  Script: PASS | N violation(s)
  Details: <lista se houver>

STRUCTURE:
  Architecture: PASS | FAIL — <motivo>
  Conventions: PASS | FAIL — <motivo>
  Cross-service: PASS | N/A

TESTS:
  Suite: PASS | FAIL — X passed, Y failed
  New tests added: yes | no

SECURITY:
  Findings: PASS | N HIGH, M MEDIUM, K LOW | SKIPPED
  Details: <lista de findings HIGH se houver>

GIT:
  Commit message: PASS | FAIL
  Forbidden files: PASS | FAIL

VERDICT: READY | NOT READY
```

Nunca reportar `READY` se qualquer check estiver `FAIL` ou se SECURITY tiver pelo menos um HIGH finding.
