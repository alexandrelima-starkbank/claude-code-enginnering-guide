import os
import json
import shutil
import tempfile
import subprocess
from unittest import TestCase, main

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SETUP = os.path.join(PROJECT_ROOT, "setup.sh")


def makeWorkdir(pyproject="", mutmut=""):
    d = tempfile.mkdtemp()
    if pyproject:
        with open(os.path.join(d, "pyproject.toml"), "w") as f:
            f.write(pyproject)
    if mutmut:
        with open(os.path.join(d, "mutmut.toml"), "w") as f:
            f.write(mutmut)
    hooks_dir = os.path.join(d, ".claude", "hooks")
    os.makedirs(hooks_dir)
    # chmod +x .claude/hooks/*.sh requer ao menos um arquivo .sh
    stub = os.path.join(hooks_dir, "stub.sh")
    with open(stub, "w") as f:
        f.write("#!/bin/bash\n")
    return d


def runSetup(workdir):
    return subprocess.run(
        ["bash", SETUP],
        capture_output=True,
        text=True,
        cwd=workdir,
    )


class PlaceholderValidationTest(TestCase):

    def setUp(self):
        self.workdir = makeWorkdir(
            mutmut="[mutmut]\npaths_to_mutate = \"myapp/\"\n",
        )

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def testValidConfig_exits0(self):
        result = runSetup(self.workdir)
        self.assertEqual(result.returncode, 0)

    def testPathsToMutatePlaceholder_exits1(self):
        with open(os.path.join(self.workdir, "mutmut.toml"), "w") as f:
            f.write('[mutmut]\npaths_to_mutate = "src/"\n')
        result = runSetup(self.workdir)
        self.assertEqual(result.returncode, 1)
        self.assertIn("paths_to_mutate", result.stdout)

    def testPathsToMutatePlaceholder_suggestsConfigureSh(self):
        with open(os.path.join(self.workdir, "mutmut.toml"), "w") as f:
            f.write('[mutmut]\npaths_to_mutate = "src/"\n')
        result = runSetup(self.workdir)
        self.assertIn("configure.sh", result.stdout)


class NoPyprojectTest(TestCase):

    def setUp(self):
        self.workdir = makeWorkdir()

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def testNoPyproject_exits0(self):
        result = runSetup(self.workdir)
        self.assertEqual(result.returncode, 0)

    def testNoMutmut_exits0(self):
        result = runSetup(self.workdir)
        self.assertEqual(result.returncode, 0)


class SortImportsCopyTest(TestCase):

    def setUp(self):
        self.workdir = makeWorkdir()
        hooks_dir = os.path.join(self.workdir, ".claude", "hooks")
        with open(os.path.join(hooks_dir, "sortImports.py"), "w") as f:
            f.write("# sortImports placeholder\n")

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def testSetup_copiesSortImports(self):
        with tempfile.TemporaryDirectory() as fakeHome:
            result = subprocess.run(
                ["bash", SETUP],
                capture_output=True,
                text=True,
                cwd=self.workdir,
                env={**os.environ, "HOME": fakeHome},
            )
            dest = os.path.join(fakeHome, ".config", "sortImports.py")
            self.assertTrue(os.path.exists(dest))


class PermissionsTest(TestCase):

    def setUp(self):
        self.workdir = makeWorkdir()
        stub = os.path.join(self.workdir, ".claude", "hooks", "stub.sh")
        os.chmod(stub, 0o644)

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def testHooks_madeExecutable(self):
        runSetup(self.workdir)
        stub = os.path.join(self.workdir, ".claude", "hooks", "stub.sh")
        self.assertTrue(os.access(stub, os.X_OK))


class ClaudeHooksDirTest(TestCase):

    def setUp(self):
        self.workdir = makeWorkdir()

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def testSetup_writesClaudeHooksDirToSettingsLocal(self):
        # Arrange
        settingsLocal = os.path.join(self.workdir, ".claude", "settings.local.json")

        # Act
        runSetup(self.workdir)

        # Assert
        self.assertTrue(os.path.exists(settingsLocal))
        with open(settingsLocal) as f:
            data = json.loads(f.read())
        expectedPath = os.path.realpath(os.path.join(self.workdir, ".claude", "hooks"))
        self.assertEqual(data["env"]["CLAUDE_HOOKS_DIR"], expectedPath)

    def testSetup_preservesExistingSettingsLocalContent(self):
        # Arrange
        settingsLocal = os.path.join(self.workdir, ".claude", "settings.local.json")
        existing = {"permissions": {"allow": ["WebFetch(domain:docs.anthropic.com)"]}}
        with open(settingsLocal, "w") as f:
            f.write(json.dumps(existing))

        # Act
        runSetup(self.workdir)

        # Assert
        with open(settingsLocal) as f:
            data = json.loads(f.read())
        self.assertIn("permissions", data)
        self.assertIn("CLAUDE_HOOKS_DIR", data.get("env", {}))

    def testSetup_updatesStaleClaudeHooksDir(self):
        # Arrange
        settingsLocal = os.path.join(self.workdir, ".claude", "settings.local.json")
        with open(settingsLocal, "w") as f:
            f.write(json.dumps({"env": {"CLAUDE_HOOKS_DIR": "/old/stale/path"}}))

        # Act
        runSetup(self.workdir)

        # Assert
        with open(settingsLocal) as f:
            data = json.loads(f.read())
        expectedPath = os.path.realpath(os.path.join(self.workdir, ".claude", "hooks"))
        self.assertEqual(data["env"]["CLAUDE_HOOKS_DIR"], expectedPath)

    def testHookCommand_usesClaudeHooksDirVar(self):
        # Arrange
        settingsPath = os.path.join(
            os.path.dirname(__file__), "..", ".claude", "settings.json"
        )

        # Act
        with open(settingsPath) as f:
            content = f.read()

        # Assert - no hook command references .claude/hooks/ as a relative path
        self.assertNotIn("bash .claude/hooks/", content)
        self.assertIn("CLAUDE_HOOKS_DIR", content)

    def testHookCommand_blocksWhenClaudeHooksDirUnset(self):
        # Arrange
        settingsPath = os.path.join(
            os.path.dirname(__file__), "..", ".claude", "settings.json"
        )
        with open(settingsPath) as f:
            data = json.loads(f.read())
        cmd = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_HOOKS_DIR"}

        # Act
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)

        # Assert
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("setup.sh", result.stderr + result.stdout)

    def testHookCommand_blocksWhenClaudeHooksDirInvalid(self):
        # Arrange
        settingsPath = os.path.join(
            os.path.dirname(__file__), "..", ".claude", "settings.json"
        )
        with open(settingsPath) as f:
            data = json.loads(f.read())
        cmd = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        env = {**os.environ, "CLAUDE_HOOKS_DIR": "/nonexistent/path"}

        # Act
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)

        # Assert
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("setup.sh", result.stderr + result.stdout)


if __name__ == "__main__":
    main()
