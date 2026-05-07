---
description: Inicializa documentação do projeto sem sobrescrever o ambiente instalado.
allowed-tools: Bash, Read, Write
---

# Init

Este projeto usa o **Claude Code Engineering Environment** — um ambiente com processo, hooks e pipeline instalados. O `CLAUDE.md` na raiz é prescritivo e não deve ser gerado automaticamente.

Rodar o `/init` nativo sobrescreveria as instruções de processo (Intake Protocol, pipeline de fases, guardrails) com uma descrição genérica do codebase, desativando todos os mecanismos de proteção do ambiente.

**Alternativas corretas:**

- Para anotar preferências pessoais ou contexto local: crie `CLAUDE.local.md` na raiz (já está no `.gitignore`)
- Para documentar um subprojeto específico: crie `<subprojeto>/CLAUDE.md` dentro da pasta do projeto
- Para entender o que o ambiente já configurou: leia `CLAUDE.md`, `.claude/CATALOG.md` e `.claude/PIPELINE.md`

Nenhuma ação foi executada. O `CLAUDE.md` existente está preservado.
