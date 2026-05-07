import os
import json
import tempfile
import subprocess
from unittest import TestCase, main, skipUnless

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
HOOK = os.path.join(PROJECT_ROOT, ".claude", "hooks", "inject-tasks-context.sh")

HAS_JQ = subprocess.run(["which", "jq"], capture_output=True).returncode == 0

TASKS_EMPTY = """\
# TASKS.md

## Tarefas Ativas

_Nenhuma tarefa ativa no momento._

## Histórico

_Nenhuma tarefa concluída ainda._
"""

TASKS_WITH_ACTIVE = """\
# TASKS.md

## Tarefas Ativas

### T1 — Implementar parser

- **Projeto:** core
- **Status:** em andamento
- **Descrição:** Implementar parser de JSON

## Histórico

_Nenhuma tarefa concluída ainda._
"""

TASKS_WITH_STALE = """\
# TASKS.md

## Tarefas Ativas

### T1 — Fix linter

- **Projeto:** core
- **Status:** concluído
- **Descrição:** Corrigir linter

## Histórico

_Nenhuma tarefa concluída ainda._
"""

TASKS_WITH_CANCELLED = """\
# TASKS.md

## Tarefas Ativas

### T2 — Spike de migração

- **Projeto:** core
- **Status:** cancelado
- **Descrição:** Avaliar migração

## Histórico

_Nenhuma tarefa concluída ainda._
"""


def makeFakePipeline(tmpdir):
    fakeBin = os.path.join(tmpdir, "_bin")
    os.makedirs(fakeBin, exist_ok=True)
    fakePipeline = os.path.join(fakeBin, "pipeline")
    with open(fakePipeline, "w") as f:
        f.write("#!/bin/bash\nexit 1\n")
    os.chmod(fakePipeline, 0o755)
    return fakeBin


def makeFakePipelineWithSearch(tmpdir, searchOutput="Resultado semantico: feature encontrada"):
    fakeBin = os.path.join(tmpdir, "_bin")
    os.makedirs(fakeBin, exist_ok=True)
    fakePipeline = os.path.join(fakeBin, "pipeline")
    with open(fakePipeline, "w") as f:
        f.write(
            "#!/bin/bash\n"
            'if [ "$1" = "task" ] && [ "$2" = "list" ]; then\n'
            '    echo "T1 | Test task | implementation | em andamento"\n'
            '    exit 0\n'
            'fi\n'
            'if [ "$1" = "context" ] && [ "$2" = "search" ]; then\n'
            '    echo "{out}"\n'
            '    exit 0\n'
            'fi\n'
            'exit 1\n'.format(out=searchOutput)
        )
    os.chmod(fakePipeline, 0o755)
    return fakeBin


_CLASSIFY_TEMPLATES = {
    "error": "#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n",
    "invalid": "#!/usr/bin/env python3\nprint('not valid json')\n",
}


_CLASSIFY_SEARCH_TRUE = (
    "#!/usr/bin/env python3\n"
    "import json\n"
    'print(json.dumps({{"search": True, "query": "{q}"}}))\n'
)


def _classifyContent(returnSearch, query, failWithError, invalidJson):
    if failWithError:
        return _CLASSIFY_TEMPLATES["error"]
    if invalidJson:
        return _CLASSIFY_TEMPLATES["invalid"]
    if not returnSearch:
        return "#!/usr/bin/env python3\nimport json\nprint(json.dumps({'search': False, 'query': ''}))\n"
    return _CLASSIFY_SEARCH_TRUE.format(q=query)


def makeClassifyScript(hooksDir, returnSearch=True, query="cartao validade", failWithError=False, invalidJson=False):
    scriptPath = os.path.join(hooksDir, "classifySearch.py")
    content = _classifyContent(returnSearch, query, failWithError, invalidJson)
    with open(scriptPath, "w") as f:
        f.write(content)
    os.chmod(scriptPath, 0o755)
    return scriptPath


def runWithSearch(userMessage, hooksDir, fakeBin, searchFails=False):
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        env = {**os.environ}
        env["PATH"] = fakeBin + ":" + env.get("PATH", "")
        env["CLAUDE_HOOKS_DIR"] = hooksDir
        env["ANTHROPIC_API_KEY"] = "test-key"
        payload = json.dumps({"prompt": userMessage})
        result = subprocess.run(
            ["bash", HOOK],
            input=payload,
            capture_output=True,
            text=True,
            cwd=tmpdir,
            env=env,
        )
        return result


def run(tasksContent):
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        fakeBin = makeFakePipeline(tmpdir)
        tasks_path = os.path.join(tmpdir, "TASKS.md")
        with open(tasks_path, "w", encoding="utf-8") as f:
            f.write(tasksContent)

        env = {**os.environ, "HOME": os.environ.get("HOME", "/tmp")}
        env["PATH"] = fakeBin + ":" + env.get("PATH", "")
        payload = json.dumps({"prompt": "test"})
        result = subprocess.run(
            ["bash", HOOK],
            input=payload,
            capture_output=True,
            text=True,
            cwd=tmpdir,
            env=env,
        )
        return result


@skipUnless(HAS_JQ, "jq not installed")
class TasksContextTest(TestCase):

    def testNoTasksFile_silentExit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            fakeBin = makeFakePipeline(tmpdir)
            env = {**os.environ}
            env["PATH"] = fakeBin + ":" + env.get("PATH", "")
            payload = json.dumps({"prompt": "test"})
            result = subprocess.run(
                ["bash", HOOK],
                input=payload,
                capture_output=True,
                text=True,
                cwd=tmpdir,
                env=env,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")

    def testEmptyActiveTasks_silentExit(self):
        result = run(TASKS_EMPTY)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def testActiveTasks_contextInjected(self):
        result = run(TASKS_WITH_ACTIVE)
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("T1", context)
        self.assertIn("em andamento", context)

    def testStaleConcluido_urgentAlertInjected(self):
        result = run(TASKS_WITH_STALE)
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ACAO OBRIGATORIA", context)
        self.assertIn("T1", context)

    def testStaleCancelado_urgentAlertInjected(self):
        result = run(TASKS_WITH_CANCELLED)
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ACAO OBRIGATORIA", context)


@skipUnless(HAS_JQ, "jq not installed")
class SemanticSearchTest(TestCase):

    def testInjectHook_SemanticSearchTriggered_WhenHaikuReturnsTrue(self):
        # Arrange
        with tempfile.TemporaryDirectory() as hooksDir:
            makeClassifyScript(hooksDir, returnSearch=True, query="cartao validade")
            with tempfile.TemporaryDirectory() as tmpdir:
                subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
                fakeBin = makeFakePipelineWithSearch(tmpdir)
                env = {**os.environ, "CLAUDE_HOOKS_DIR": hooksDir, "ANTHROPIC_API_KEY": "test-key"}
                env["PATH"] = fakeBin + ":" + env.get("PATH", "")
                payload = json.dumps({"prompt": "preciso adicionar campo de validade no cartao"})

                # Act
                result = subprocess.run(
                    ["bash", HOOK], input=payload, capture_output=True, text=True, cwd=tmpdir, env=env,
                )

        # Assert
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Contexto relevante", context)

    def testInjectHook_SemanticSearchSkipped_WhenHaikuReturnsFalse(self):
        # Arrange
        with tempfile.TemporaryDirectory() as hooksDir:
            makeClassifyScript(hooksDir, returnSearch=False)
            with tempfile.TemporaryDirectory() as tmpdir:
                subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
                fakeBin = makeFakePipelineWithSearch(tmpdir)
                env = {**os.environ, "CLAUDE_HOOKS_DIR": hooksDir, "ANTHROPIC_API_KEY": "test-key"}
                env["PATH"] = fakeBin + ":" + env.get("PATH", "")
                payload = json.dumps({"prompt": "qual o status do ambiente?"})

                # Act
                result = subprocess.run(
                    ["bash", HOOK], input=payload, capture_output=True, text=True, cwd=tmpdir, env=env,
                )

        # Assert
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("Contexto relevante", context)

    def testInjectHook_HaikuFailure_PrintsWarningAndContinues(self):
        # Arrange
        with tempfile.TemporaryDirectory() as hooksDir:
            makeClassifyScript(hooksDir, failWithError=True)
            with tempfile.TemporaryDirectory() as tmpdir:
                subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
                fakeBin = makeFakePipelineWithSearch(tmpdir)
                env = {**os.environ, "CLAUDE_HOOKS_DIR": hooksDir, "ANTHROPIC_API_KEY": "test-key"}
                env["PATH"] = fakeBin + ":" + env.get("PATH", "")
                payload = json.dumps({"prompt": "alguma tarefa ativa?"})

                # Act
                result = subprocess.run(
                    ["bash", HOOK], input=payload, capture_output=True, text=True, cwd=tmpdir, env=env,
                )

        # Assert
        self.assertEqual(result.returncode, 0)
        self.assertIn("AVISO", result.stderr)

    def testInjectHook_ContextSearchFails_ContinuesNormally(self):
        # Arrange
        with tempfile.TemporaryDirectory() as hooksDir:
            makeClassifyScript(hooksDir, returnSearch=True, query="cartao validade")
            with tempfile.TemporaryDirectory() as tmpdir:
                subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
                # pipeline that returns tasks but fails on context search
                fakeBin = os.path.join(tmpdir, "_bin")
                os.makedirs(fakeBin, exist_ok=True)
                fakePipeline = os.path.join(fakeBin, "pipeline")
                with open(fakePipeline, "w") as f:
                    f.write(
                        "#!/bin/bash\n"
                        'if [ "$1" = "task" ] && [ "$2" = "list" ]; then\n'
                        '    echo "T1 | Test task | implementation | em andamento"\n'
                        '    exit 0\n'
                        'fi\n'
                        'exit 1\n'
                    )
                os.chmod(fakePipeline, 0o755)
                env = {**os.environ, "CLAUDE_HOOKS_DIR": hooksDir, "ANTHROPIC_API_KEY": "test-key"}
                env["PATH"] = fakeBin + ":" + env.get("PATH", "")
                payload = json.dumps({"prompt": "preciso implementar algo"})

                # Act
                result = subprocess.run(
                    ["bash", HOOK], input=payload, capture_output=True, text=True, cwd=tmpdir, env=env,
                )

        # Assert
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertIn("hookSpecificOutput", output)


if __name__ == "__main__":
    main()
