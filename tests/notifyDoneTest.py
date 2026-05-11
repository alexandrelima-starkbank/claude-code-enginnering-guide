import os
import sqlite3
import tempfile
import subprocess
from unittest import TestCase, skipUnless

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
HOOK = os.path.join(PROJECT_ROOT, ".claude", "hooks", "notify-done.sh")

HAS_SQLITE3 = subprocess.run(["which", "sqlite3"], capture_output=True).returncode == 0


def makeDb(tmpdir, tasks):
    dbPath = os.path.join(tmpdir, "pipeline.db")
    conn = sqlite3.connect(dbPath)
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, phase TEXT)"
    )
    for taskId, status in tasks:
        conn.execute("INSERT INTO tasks VALUES (?, ?, 'implementation')", (taskId, status))
    conn.commit()
    conn.close()
    return dbPath


def makeFakeClaude(tmpdir, exitCode=0, invokedPath=None):
    fakeBin = os.path.join(tmpdir, "_bin")
    os.makedirs(fakeBin, exist_ok=True)
    fakeClaude = os.path.join(fakeBin, "claude")
    script = "#!/bin/bash\nexit {0}\n".format(exitCode)
    if invokedPath:
        script = "#!/bin/bash\ntouch {0}\nexit {1}\n".format(invokedPath, exitCode)
    with open(fakeClaude, "w") as f:
        f.write(script)
    os.chmod(fakeClaude, 0o755)
    return fakeBin


def runHook(dbPath, fakeBin=None):
    env = {**os.environ, "PIPELINE_DB_PATH": dbPath}
    if fakeBin:
        env["PATH"] = fakeBin + ":" + env.get("PATH", "")
    return subprocess.run(
        ["bash", HOOK],
        capture_output=True,
        text=True,
        env=env,
    )


@skipUnless(HAS_SQLITE3, "sqlite3 not installed")
class NotifyDoneTest(TestCase):

    def testStopHook_ActiveTasks_InvokesAgent(self):
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            dbPath = makeDb(tmpdir, [("T01", "em andamento")])
            invokedPath = os.path.join(tmpdir, "invoked")
            fakeBin = makeFakeClaude(tmpdir, exitCode=0, invokedPath=invokedPath)

            # Act
            result = runHook(dbPath, fakeBin)

            # Assert
            self.assertEqual(result.returncode, 0)
            self.assertTrue(os.path.exists(invokedPath), "claude was not invoked")

    def testStopHook_NoTasksToMaintain_SilentExit(self):
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            dbPath = makeDb(tmpdir, [])
            invokedPath = os.path.join(tmpdir, "invoked")
            fakeBin = makeFakeClaude(tmpdir, exitCode=0, invokedPath=invokedPath)

            # Act
            result = runHook(dbPath, fakeBin)

            # Assert
            self.assertEqual(result.returncode, 0)
            self.assertFalse(os.path.exists(invokedPath), "claude should not have been invoked")
            self.assertEqual(result.stdout.strip(), "")

    def testStopHook_CliFails_WarnsAndExitsZero(self):
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            dbPath = makeDb(tmpdir, [("T01", "em andamento")])
            fakeBin = makeFakeClaude(tmpdir, exitCode=1)

            # Act
            result = runHook(dbPath, fakeBin)

            # Assert
            self.assertEqual(result.returncode, 0)
            self.assertIn("AVISO", result.stderr)
