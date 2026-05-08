import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from unittest import TestCase, main

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline-cli"))

from pipeline import db


from contextlib import contextmanager


@contextmanager
def useTempDb():
    tmpDir = tempfile.mkdtemp()
    tmpPath = Path(tmpDir) / "test_pipeline.db"
    db.closeConn()
    with patch.object(db, "DB_PATH", tmpPath):
        try:
            yield
        finally:
            db.closeConn()


class InitDbTest(TestCase):

    def testInitDb_CreatesAllTables(self):
        with useTempDb():
            db.initDb()
            conn = db.getConn()
            tables = [
                row[0] for row in
                conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            ]
            conn.close()
            for expected in ("projects", "tasks", "phaseTransitions", "earsRequirements",
                             "acceptanceCriteria", "testResults", "mutationResults", "incidents"):
                self.assertIn(expected, tables)

    def testInitDb_Idempotent(self):
        with useTempDb():
            db.initDb()
            db.initDb()
            conn = db.getConn()
            tables = [
                row[0] for row in
                conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            ]
            conn.close()
            self.assertIn("tasks", tables)


class ProjectTest(TestCase):

    def testEnsureProject_CreatesNew(self):
        with useTempDb():
            db.initDb()
            projectId = db.ensureProject("My Project", "/tmp/my-project")
            self.assertEqual(projectId, "my-project")
            projects = db.listProjects()
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["name"], "My Project")
            self.assertEqual(projects[0]["path"], "/tmp/my-project")

    def testEnsureProject_IdempotentSameProject(self):
        with useTempDb():
            db.initDb()
            id1 = db.ensureProject("My Project", "/tmp/my-project")
            id2 = db.ensureProject("My Project", "/tmp/my-project")
            self.assertEqual(id1, id2)
            self.assertEqual(len(db.listProjects()), 1)

    def testEnsureProject_NormalizesName(self):
        with useTempDb():
            db.initDb()
            projectId = db.ensureProject("My Cool Project")
            self.assertEqual(projectId, "my-cool-project")

    def testEnsureProject_NormalizesSlashes(self):
        with useTempDb():
            db.initDb()
            projectId = db.ensureProject("org/repo")
            self.assertEqual(projectId, "org-repo")

    def testListProjects_Empty(self):
        with useTempDb():
            db.initDb()
            self.assertEqual(db.listProjects(), [])


class TaskTest(TestCase):

    def testCreateTask_ReturnsSequentialId(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            t1 = db.createTask("proj", "First task")
            t2 = db.createTask("proj", "Second task")
            self.assertEqual(t1, "T1")
            self.assertEqual(t2, "T2")

    def testCreateTask_DefaultValues(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "My task")
            task = db.getTask(taskId)
            self.assertEqual(task["title"], "My task")
            self.assertEqual(task["status"], "pendente")
            self.assertEqual(task["phase"], "requirements")
            self.assertEqual(task["type"], "feature")

    def testCreateTask_WithTypeAndDescription(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Fix bug", "A description", "bug")
            task = db.getTask(taskId)
            self.assertEqual(task["type"], "bug")
            self.assertEqual(task["description"], "A description")

    def testCreateTask_RecordsInitialPhaseTransition(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "My task")
            history = db.getPhaseHistory(taskId)
            self.assertEqual(len(history), 1)
            self.assertIsNone(history[0]["fromPhase"])
            self.assertEqual(history[0]["toPhase"], "requirements")

    def testGetTask_NotFound(self):
        with useTempDb():
            db.initDb()
            self.assertIsNone(db.getTask("T999"))

    def testListTasks_FilterByProject(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj-a")
            db.ensureProject("proj-b")
            db.createTask("proj-a", "Task A")
            db.createTask("proj-b", "Task B")
            tasksA = db.listTasks(projectId="proj-a")
            self.assertEqual(len(tasksA), 1)
            self.assertEqual(tasksA[0]["title"], "Task A")

    def testListTasks_FilterByStatus(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            t1 = db.createTask("proj", "Task 1")
            db.createTask("proj", "Task 2")
            db.updateTask(t1, status="concluído")
            active = db.listTasks(status="pendente")
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["title"], "Task 2")

    def testListTasks_FilterByPhase(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            db.createTask("proj", "Task 1")
            tasks = db.listTasks(phase="requirements")
            self.assertEqual(len(tasks), 1)
            empty = db.listTasks(phase="done")
            self.assertEqual(len(empty), 0)

    def testUpdateTask_Status(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "My task")
            db.updateTask(taskId, status="em andamento")
            task = db.getTask(taskId)
            self.assertEqual(task["status"], "em andamento")

    def testUpdateTask_Title(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Old title")
            db.updateTask(taskId, title="New title")
            task = db.getTask(taskId)
            self.assertEqual(task["title"], "New title")

    def testUpdateTask_IgnoresUnknownFields(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "My task")
            db.updateTask(taskId, unknown="value")
            task = db.getTask(taskId)
            self.assertEqual(task["title"], "My task")

    def testUpdateTask_NoChanges(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "My task")
            db.updateTask(taskId)
            task = db.getTask(taskId)
            self.assertEqual(task["title"], "My task")


class PhaseAdvanceTest(TestCase):

    def _createTask(self):
        db.ensureProject("proj")
        return db.createTask("proj", "Test task")

    def testAdvancePhase_RequirementsToSpec(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.advancePhase(taskId, "spec")
            task = db.getTask(taskId)
            self.assertEqual(task["phase"], "spec")

    def testAdvancePhase_RecordsTransition(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.advancePhase(taskId, "spec", reason="EARS approved")
            history = db.getPhaseHistory(taskId)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[1]["fromPhase"], "requirements")
            self.assertEqual(history[1]["toPhase"], "spec")
            self.assertEqual(history[1]["reason"], "EARS approved")

    def testAdvancePhase_RejectsSkippingPhase(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "tests")
            self.assertIn("spec", str(ctx.exception))

    def testAdvancePhase_RejectsInvalidPhase(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            with self.assertRaises(ValueError):
                db.advancePhase(taskId, "invalid_phase")

    def testAdvancePhase_RejectsNonexistentTask(self):
        with useTempDb():
            db.initDb()
            with self.assertRaises(ValueError):
                db.advancePhase("T999", "spec")

    def testAdvancePhase_FullPipelineSequence(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.advancePhase(taskId, "spec")
            db.advancePhase(taskId, "plan")
            planId = db.createPlan(taskId, "test plan")
            db.approvePlan(taskId, planId)
            db.advancePhase(taskId, "tests")
            db.addCriterion(taskId, "R01", "scenario", "then text",
                            testMethod="testSomething")
            db.setTestQuality(taskId, "C01", "ACCEPTABLE")
            db.recordTest(taskId, "testSomething", True)
            db.advancePhase(taskId, "implementation")
            db.advancePhase(taskId, "mutation")
            db.recordMutation(taskId, 1, 1)
            db.advancePhase(taskId, "static-analysis")
            for tool in ("ruff", "bandit", "vulture", "pylint", "radon_cc", "radon_mi"):
                db.addStaticAnalysisResult(taskId, tool, "metric", 0, 0, True, [])
            db.advancePhase(taskId, "done")
            task = db.getTask(taskId)
            self.assertEqual(task["phase"], "done")
            history = db.getPhaseHistory(taskId)
            self.assertEqual(len(history), 8)

    def testAdvancePhase_TestsToImplementation_RequiresTestQuality(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.advancePhase(taskId, "spec")
            db.advancePhase(taskId, "plan")
            planId = db.createPlan(taskId, "test plan")
            db.approvePlan(taskId, planId)
            db.advancePhase(taskId, "tests")
            db.addCriterion(taskId, "R01", "scenario", "then text",
                            testMethod="testSomething")
            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "implementation")
            self.assertIn("qualidade", str(ctx.exception))

    def testAdvancePhase_TestsToImplementation_AcceptsStrong(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.advancePhase(taskId, "spec")
            db.advancePhase(taskId, "plan")
            planId = db.createPlan(taskId, "test plan")
            db.approvePlan(taskId, planId)
            db.advancePhase(taskId, "tests")
            db.addCriterion(taskId, "R01", "scenario", "then text",
                            testMethod="testSomething")
            db.setTestQuality(taskId, "C01", "STRONG")
            db.recordTest(taskId, "testSomething", True)
            db.advancePhase(taskId, "implementation")
            task = db.getTask(taskId)
            self.assertEqual(task["phase"], "implementation")


class EarsTest(TestCase):

    def _createTask(self):
        db.ensureProject("proj")
        return db.createTask("proj", "Test task")

    def testAddEars_ReturnsSequentialIds(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            r1 = db.addEars(taskId, "event", "When user logs in")
            r2 = db.addEars(taskId, "ubiquitous", "System shall validate")
            self.assertEqual(r1, "R01")
            self.assertEqual(r2, "R02")

    def testListEars_ReturnsAll(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.addEars(taskId, "event", "When user logs in")
            db.addEars(taskId, "state", "While connected")
            ears = db.listEars(taskId)
            self.assertEqual(len(ears), 2)
            self.assertEqual(ears[0]["pattern"], "event")
            self.assertEqual(ears[1]["pattern"], "state")

    def testListEars_Empty(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            self.assertEqual(db.listEars(taskId), [])

    def testApproveEars_Single(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.addEars(taskId, "event", "When user logs in")
            db.approveEars(taskId, "R01")
            ears = db.listEars(taskId)
            self.assertTrue(ears[0]["approved"])
            self.assertIsNotNone(ears[0]["approvedAt"])

    def testApproveAllEars(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.addEars(taskId, "event", "Req 1")
            db.addEars(taskId, "state", "Req 2")
            db.approveAllEars(taskId)
            ears = db.listEars(taskId)
            self.assertTrue(all(r["approved"] for r in ears))

    def testApproveEars_DefaultNotApproved(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.addEars(taskId, "event", "Req 1")
            ears = db.listEars(taskId)
            self.assertFalse(ears[0]["approved"])


class CriterionTest(TestCase):

    def _createTask(self):
        db.ensureProject("proj")
        return db.createTask("proj", "Test task")

    def testAddCriterion_ReturnsSequentialIds(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            c1 = db.addCriterion(taskId, "R01", "Happy path", "item created")
            c2 = db.addCriterion(taskId, "R01", "Duplicate", "error returned")
            self.assertEqual(c1, "C01")
            self.assertEqual(c2, "C02")

    def testAddCriterion_WithAllFields(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.addCriterion(
                taskId, "R01", "Create item",
                "item persisted",
                givenText="valid payload",
                whenText="POST /items",
                testMethod="testCreate_ValidPayload",
            )
            criteria = db.listCriteria(taskId)
            self.assertEqual(len(criteria), 1)
            c = criteria[0]
            self.assertEqual(c["earsId"], "R01")
            self.assertEqual(c["scenarioName"], "Create item")
            self.assertEqual(c["givenText"], "valid payload")
            self.assertEqual(c["whenText"], "POST /items")
            self.assertEqual(c["thenText"], "item persisted")
            self.assertEqual(c["testMethod"], "testCreate_ValidPayload")

    def testListCriteria_Empty(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            self.assertEqual(db.listCriteria(taskId), [])

    def testApproveCriterion_Single(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.addCriterion(taskId, "R01", "Scenario", "then")
            db.approveCriterion(taskId, "C01")
            criteria = db.listCriteria(taskId)
            self.assertTrue(criteria[0]["approved"])

    def testApproveAllCriteria(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.addCriterion(taskId, "R01", "Scenario 1", "then 1")
            db.addCriterion(taskId, "R01", "Scenario 2", "then 2")
            db.approveAllCriteria(taskId)
            criteria = db.listCriteria(taskId)
            self.assertTrue(all(c["approved"] for c in criteria))

    def testSetTestQuality(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.addCriterion(taskId, "R01", "Scenario", "then",
                            testMethod="testSomething")
            db.setTestQuality(taskId, "C01", "STRONG")
            criteria = db.listCriteria(taskId)
            self.assertEqual(criteria[0]["testQuality"], "STRONG")
            self.assertIsNotNone(criteria[0]["reviewedAt"])


class TestResultTest(TestCase):

    def _createTask(self):
        db.ensureProject("proj")
        return db.createTask("proj", "Test task")

    def testRecordTest_Passed(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.recordTest(taskId, "testCreate_Valid", True)
            summary = db.getTestSummary(taskId)
            self.assertEqual(summary["total"], 1)
            self.assertEqual(summary["passed"], 1)
            self.assertEqual(summary["failed"], 0)

    def testRecordTest_Failed(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.recordTest(taskId, "testCreate_Valid", False)
            summary = db.getTestSummary(taskId)
            self.assertEqual(summary["total"], 1)
            self.assertEqual(summary["passed"], 0)
            self.assertEqual(summary["failed"], 1)

    def testRecordTest_LatestResultWins(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.recordTest(taskId, "testCreate_Valid", False)
            db.recordTest(taskId, "testCreate_Valid", True)
            summary = db.getTestSummary(taskId)
            self.assertEqual(summary["total"], 1)
            self.assertEqual(summary["passed"], 1)

    def testRecordTest_MultipleMethods(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.recordTest(taskId, "testCreate_Valid", True)
            db.recordTest(taskId, "testCreate_Duplicate", False)
            summary = db.getTestSummary(taskId)
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["passed"], 1)
            self.assertEqual(summary["failed"], 1)

    def testGetTestSummary_Empty(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            summary = db.getTestSummary(taskId)
            self.assertEqual(summary["total"], 0)

    def testGetLatestTestResult_Found(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.recordTest(taskId, "testCreate_Valid", True)
            result = db.getLatestTestResult(taskId, "testCreate_Valid")
            self.assertTrue(result)

    def testGetLatestTestResult_NotFound(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            result = db.getLatestTestResult(taskId, "testNonexistent")
            self.assertIsNone(result)

    def testGetLatestTestResult_NoneMethod(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            result = db.getLatestTestResult(taskId, None)
            self.assertIsNone(result)


class MutationResultTest(TestCase):

    def _createTask(self):
        db.ensureProject("proj")
        return db.createTask("proj", "Test task")

    def testRecordMutation_CalculatesScore(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.recordMutation(taskId, 10, 8)
            mutation = db.getLatestMutation(taskId)
            self.assertEqual(mutation["totalMutants"], 10)
            self.assertEqual(mutation["killed"], 8)
            self.assertAlmostEqual(mutation["score"], 80.0)

    def testRecordMutation_PerfectScore(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.recordMutation(taskId, 5, 5)
            mutation = db.getLatestMutation(taskId)
            self.assertAlmostEqual(mutation["score"], 100.0)

    def testRecordMutation_ZeroMutants(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.recordMutation(taskId, 0, 0)
            mutation = db.getLatestMutation(taskId)
            self.assertAlmostEqual(mutation["score"], 0.0)

    def testGetLatestMutation_ReturnsLatest(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.recordMutation(taskId, 10, 5)
            db.recordMutation(taskId, 10, 10)
            mutation = db.getLatestMutation(taskId)
            self.assertAlmostEqual(mutation["score"], 100.0)

    def testGetLatestMutation_NotFound(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            self.assertIsNone(db.getLatestMutation(taskId))


class IncidentTest(TestCase):

    def _createTask(self):
        db.ensureProject("proj")
        return db.createTask("proj", "Incident task", taskType="incident")

    def testCreateIncident(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.createIncident(taskId, "crítico", "N3", "service down", "service up")
            conn = db.getConn()
            row = conn.execute(
                "SELECT * FROM incidents WHERE taskId = ?", (taskId,),
            ).fetchone()
            conn.close()
            self.assertEqual(row["severity"], "crítico")
            self.assertEqual(row["level"], "N3")
            self.assertEqual(row["currentBehavior"], "service down")
            self.assertEqual(row["expectedBehavior"], "service up")

    def testUpdateIncident_RootCause(self):
        with useTempDb():
            db.initDb()
            taskId = self._createTask()
            db.createIncident(taskId, "alto", "N3")
            db.updateIncident(taskId, rootCause="null pointer", rootCauseConfidence="alta")
            conn = db.getConn()
            row = conn.execute(
                "SELECT * FROM incidents WHERE taskId = ?", (taskId,),
            ).fetchone()
            conn.close()
            self.assertEqual(row["rootCause"], "null pointer")
            self.assertEqual(row["rootCauseConfidence"], "alta")


class AuditTest(TestCase):

    def _createFullTask(self):
        db.ensureProject("proj")
        taskId = db.createTask("proj", "Audit task")
        db.addEars(taskId, "event", "When user creates item")
        db.approveAllEars(taskId)
        db.addCriterion(taskId, "R01", "Happy path", "item created",
                        testMethod="testCreate_Valid")
        db.approveAllCriteria(taskId)
        return taskId

    def testGetTaskAudit_AllGates(self):
        with useTempDb():
            db.initDb()
            taskId = self._createFullTask()
            db.setTestQuality(taskId, "C01", "STRONG")
            db.recordTest(taskId, "testCreate_Valid", True)
            db.recordMutation(taskId, 5, 5)
            audit = db.getTaskAudit(taskId)
            self.assertTrue(audit["gates"]["requirements"]["pass"])
            self.assertTrue(audit["gates"]["spec"]["pass"])
            self.assertTrue(audit["gates"]["traceability"]["pass"])
            self.assertTrue(audit["gates"]["tests"]["pass"])
            self.assertTrue(audit["gates"]["testQuality"]["pass"])
            self.assertTrue(audit["gates"]["mutation"]["pass"])

    def testGetTaskAudit_FailingGates(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Bare task")
            audit = db.getTaskAudit(taskId)
            self.assertFalse(audit["gates"]["requirements"]["pass"])
            self.assertFalse(audit["gates"]["spec"]["pass"])
            self.assertFalse(audit["gates"]["traceability"]["pass"])
            self.assertFalse(audit["gates"]["tests"]["pass"])
            self.assertFalse(audit["gates"]["mutation"]["pass"])

    def testGetTaskAudit_NotFound(self):
        with useTempDb():
            db.initDb()
            self.assertIsNone(db.getTaskAudit("T999"))

    def testGetTaskAudit_PartialEars_FailsRequirements(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Partial task")
            db.addEars(taskId, "event", "Req 1")
            db.addEars(taskId, "state", "Req 2")
            db.approveEars(taskId, "R01")
            audit = db.getTaskAudit(taskId)
            self.assertFalse(audit["gates"]["requirements"]["pass"])

    def testGetTaskAudit_TraceabilityFails_WhenEarsHasNoCriterion(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Task")
            db.addEars(taskId, "event", "Req 1")
            db.addEars(taskId, "state", "Req 2")
            db.approveAllEars(taskId)
            db.addCriterion(taskId, "R01", "Scenario", "then")
            db.approveAllCriteria(taskId)
            audit = db.getTaskAudit(taskId)
            self.assertFalse(audit["gates"]["traceability"]["pass"])

    def testGetTaskAudit_TestQuality_WeakFails(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Task")
            db.addCriterion(taskId, "R01", "Scenario", "then",
                            testMethod="testSomething")
            db.setTestQuality(taskId, "C01", "WEAK")
            audit = db.getTaskAudit(taskId)
            self.assertFalse(audit["gates"]["testQuality"]["pass"])

    def testGetTaskAudit_MutationFails_Below100(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Task")
            db.recordMutation(taskId, 10, 9)
            audit = db.getTaskAudit(taskId)
            self.assertFalse(audit["gates"]["mutation"]["pass"])


if __name__ == "__main__":
    main()
