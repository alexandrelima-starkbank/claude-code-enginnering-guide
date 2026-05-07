import os
import sys
import json
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager
from unittest import TestCase, skipUnless

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline-cli"))

from pipeline import db

HOOK = os.path.join(PROJECT_ROOT, ".claude", "hooks", "check-scope.sh")
HAS_JQ = subprocess.run(["which", "jq"], capture_output=True).returncode == 0


@contextmanager
def useTempDb():
    tmpDir = tempfile.mkdtemp()
    tmpPath = Path(tmpDir) / "test_pipeline.db"
    db.closeConn()
    with patch.object(db, "DB_PATH", tmpPath):
        try:
            yield tmpPath
        finally:
            db.closeConn()


def runHook(filePath, dbPath):
    payload = json.dumps({"tool_input": {"path": filePath}})
    env = os.environ.copy()
    env["PIPELINE_DB_PATH"] = str(dbPath)
    return subprocess.run(
        ["bash", HOOK],
        input=payload,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env=env,
    )


def blocked(result):
    return result.returncode == 2 and "BLOQUEADO" in result.stderr


def allowed(result):
    return result.returncode == 0


class ScopeHookTest(TestCase):

    def _setupTaskWithPlan(self, dbPath):
        db.initDb()
        db.ensureProject("proj")
        taskId = db.createTask("proj", "Test task")
        db.updateTask(taskId, status="em andamento")
        earsId = db.addEars(taskId, "event", "System SHALL do X")
        db.approveEars(taskId, earsId)
        db.addEarsQualityScores(taskId, [{"dimension": "Risco", "score": 8, "justification": "ok"}], earsId=earsId)
        db.advancePhase(taskId, "spec")
        cId = db.addCriterion(taskId, earsId, "Happy path", "item created", testMethod="testCreate_Valid")
        db.approveCriterion(taskId, cId)
        db.advancePhase(taskId, "plan")
        planId = db.createPlan(taskId, "Implement feature")
        db.addPlanFile(taskId, planId, "handlers/itemHandler.py", "modify", ["createItem"])
        db.addPlanFile(taskId, planId, "gateways/itemGateway.py", "create", ["ItemGateway"])
        db.approvePlan(taskId, planId)
        db.advancePhase(taskId, "tests")
        db.setTestQuality(taskId, cId, "STRONG")
        db.recordTest(taskId, "testCreate_Valid", True)
        db.advancePhase(taskId, "implementation")
        return taskId

    @skipUnless(HAS_JQ, "jq not installed")
    def testScopeHook_BlocksEditOnFileOutsideScope(self):
        # Arrange
        with useTempDb() as dbPath:
            self._setupTaskWithPlan(dbPath)

            # Act
            result = runHook("services/unrelatedService.py", dbPath)

            # Assert
            self.assertTrue(blocked(result))

    @skipUnless(HAS_JQ, "jq not installed")
    def testScopeHook_AllowsEditOnFileInScope(self):
        # Arrange
        with useTempDb() as dbPath:
            self._setupTaskWithPlan(dbPath)

            # Act
            result = runHook("handlers/itemHandler.py", dbPath)

            # Assert
            self.assertTrue(allowed(result))

    @skipUnless(HAS_JQ, "jq not installed")
    def testScopeHook_AllowsEditWhenNoActiveTask(self):
        # Arrange
        with useTempDb() as dbPath:
            db.initDb()

            # Act
            result = runHook("any/file.py", dbPath)

            # Assert
            self.assertTrue(allowed(result))

    @skipUnless(HAS_JQ, "jq not installed")
    def testScopeHook_AllowsEditWhenActiveTaskHasNoPlan(self):
        # Arrange
        with useTempDb() as dbPath:
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Task without plan")
            db.updateTask(taskId, status="em andamento")

            # Act
            result = runHook("any/file.py", dbPath)

            # Assert
            self.assertTrue(allowed(result))


class ScopeComparisonTest(TestCase):

    def _advanceToPlan(self, taskId):
        earsId = db.addEars(taskId, "event", "System SHALL do X")
        db.approveEars(taskId, earsId)
        db.addEarsQualityScores(taskId, [{"dimension": "Risco", "score": 8, "justification": "ok"}], earsId=earsId)
        db.advancePhase(taskId, "spec")
        cId = db.addCriterion(taskId, earsId, "Happy path", "item created", testMethod="testCreate_Valid")
        db.approveCriterion(taskId, cId)
        db.advancePhase(taskId, "plan")
        return earsId

    def testScopeComparison_DetectsMissingPlannedItem(self):
        # Arrange
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Test task")
            self._advanceToPlan(taskId)
            planId = db.createPlan(taskId, "Implement feature")
            db.addPlanFile(taskId, planId, "handlers/itemHandler.py", "modify", ["createItem", "validatePayload"])
            db.approvePlan(taskId, planId)
            implementedComponents = ["createItem"]

            # Act
            drift = db.compareScopeVsImplemented(taskId, planId, implementedComponents)

            # Assert
            self.assertIn("missingFromImpl", drift)
            self.assertIn("validatePayload", drift["missingFromImpl"])

    def testScopeComparison_DetectsUnplannedItem(self):
        # Arrange
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Test task")
            self._advanceToPlan(taskId)
            planId = db.createPlan(taskId, "Implement feature")
            db.addPlanFile(taskId, planId, "handlers/itemHandler.py", "modify", ["createItem"])
            db.approvePlan(taskId, planId)
            implementedComponents = ["createItem", "extraHelper"]

            # Act
            drift = db.compareScopeVsImplemented(taskId, planId, implementedComponents)

            # Assert
            self.assertIn("notInPlan", drift)
            self.assertIn("extraHelper", drift["notInPlan"])

    def testScopeComparison_NoDrift_WhenImplementedMatchesPlan(self):
        # Arrange
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Test task")
            self._advanceToPlan(taskId)
            planId = db.createPlan(taskId, "Implement feature")
            db.addPlanFile(taskId, planId, "handlers/itemHandler.py", "modify", ["createItem"])
            db.approvePlan(taskId, planId)
            implementedComponents = ["createItem"]

            # Act
            drift = db.compareScopeVsImplemented(taskId, planId, implementedComponents)

            # Assert
            self.assertEqual(drift["missingFromImpl"], [])
            self.assertEqual(drift["notInPlan"], [])
