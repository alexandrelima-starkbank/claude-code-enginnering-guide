import os
import json
import sqlite3
import tempfile
import subprocess
from unittest import TestCase, skipUnless

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
HOOK = os.path.join(PROJECT_ROOT, ".claude", "hooks", "check-scope.sh")

HAS_JQ = subprocess.run(["which", "jq"], capture_output=True).returncode == 0
HAS_SQLITE3 = subprocess.run(["which", "sqlite3"], capture_output=True).returncode == 0


def makeDb(tmpdir, filePath, components):
    dbPath = os.path.join(tmpdir, "pipeline.db")
    conn = sqlite3.connect(dbPath)
    conn.executescript("""
        CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, phase TEXT);
        CREATE TABLE planArtifacts (id TEXT, taskId TEXT, approved INTEGER);
        CREATE TABLE planScope (taskId TEXT, planId TEXT, filePath TEXT, components TEXT);
    """)
    conn.execute("INSERT INTO tasks VALUES ('T01', 'em andamento', 'implementation')")
    conn.execute("INSERT INTO planArtifacts VALUES ('P01', 'T01', 1)")
    conn.execute(
        "INSERT INTO planScope VALUES ('T01', 'P01', ?, ?)",
        (filePath, json.dumps(components)),
    )
    conn.commit()
    conn.close()
    return dbPath


def makeEmptyDb(tmpdir):
    dbPath = os.path.join(tmpdir, "pipeline.db")
    conn = sqlite3.connect(dbPath)
    conn.executescript("""
        CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, phase TEXT);
        CREATE TABLE planArtifacts (id TEXT, taskId TEXT, approved INTEGER);
        CREATE TABLE planScope (taskId TEXT, planId TEXT, filePath TEXT, components TEXT);
    """)
    conn.commit()
    conn.close()
    return dbPath


def runHook(payload, dbPath):
    env = {**os.environ, "PIPELINE_DB_PATH": dbPath}
    return subprocess.run(
        ["bash", HOOK],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


@skipUnless(HAS_JQ and HAS_SQLITE3, "jq or sqlite3 not installed")
class CheckScopeTest(TestCase):

    def testCheckScope_Write_OutOfScopeComponent_Blocks(self):
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            dbPath = makeDb(tmpdir, "handlers/itemHandler.py", ["createItem"])
            payload = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "handlers/itemHandler.py",
                    "content": "def createItem():\n    pass\n\ndef deleteItem():\n    pass\n",
                },
            }

            # Act
            result = runHook(payload, dbPath)

        # Assert
        self.assertEqual(result.returncode, 2)
        self.assertIn("deleteItem", result.stderr)

    def testCheckScope_Write_InScopeComponent_Allows(self):
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            dbPath = makeDb(tmpdir, "handlers/itemHandler.py", ["createItem"])
            payload = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "handlers/itemHandler.py",
                    "content": "def createItem():\n    pass\n",
                },
            }

            # Act
            result = runHook(payload, dbPath)

        # Assert
        self.assertEqual(result.returncode, 0)

    def testCheckScope_Edit_NewOutOfScopeComponent_Blocks(self):
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            dbPath = makeDb(tmpdir, "handlers/itemHandler.py", ["createItem"])
            payload = {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "handlers/itemHandler.py",
                    "old_string": "def createItem():\n    pass\n",
                    "new_string": "def createItem():\n    pass\n\ndef deleteItem():\n    pass\n",
                },
            }

            # Act
            result = runHook(payload, dbPath)

        # Assert
        self.assertEqual(result.returncode, 2)
        self.assertIn("deleteItem", result.stderr)

    def testCheckScope_Edit_NoNewComponents_Allows(self):
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            dbPath = makeDb(tmpdir, "handlers/itemHandler.py", ["createItem"])
            payload = {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "handlers/itemHandler.py",
                    "old_string": "def createItem():\n    pass\n",
                    "new_string": "def createItem():\n    return {}\n",
                },
            }

            # Act
            result = runHook(payload, dbPath)

        # Assert
        self.assertEqual(result.returncode, 0)

    def testCheckScope_FileNotInScope_Blocks(self):
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            dbPath = makeDb(tmpdir, "handlers/itemHandler.py", ["createItem"])
            payload = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "utils/helper.py",
                    "content": "def helper():\n    pass\n",
                },
            }

            # Act
            result = runHook(payload, dbPath)

        # Assert
        self.assertEqual(result.returncode, 2)
        self.assertIn("utils/helper.py", result.stderr)

    def testCheckScope_NoPlan_Allows(self):
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            dbPath = makeEmptyDb(tmpdir)
            payload = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "any/file.py",
                    "content": "def anything():\n    pass\n",
                },
            }

            # Act
            result = runHook(payload, dbPath)

        # Assert
        self.assertEqual(result.returncode, 0)

    def testCheckScope_NonPythonFile_AllowsWithWarning(self):
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            dbPath = makeDb(tmpdir, "config.yaml", ["database"])
            payload = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "config.yaml",
                    "content": "database:\n  host: localhost\n",
                },
            }

            # Act
            result = runHook(payload, dbPath)

        # Assert
        self.assertEqual(result.returncode, 0)
        self.assertIn("AVISO", result.stderr)
