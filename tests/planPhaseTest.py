import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from contextlib import contextmanager

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline-cli"))

from pipeline import db
from unittest.mock import patch


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


class PlanPhaseOrderTest(TestCase):

    def testPlan_IsInPhasesListBetweenSpecAndTests(self):
        # Arrange / Act
        phases = db.PHASES

        # Assert
        self.assertIn("plan", phases)
        specIdx = phases.index("spec")
        planIdx = phases.index("plan")
        testsIdx = phases.index("tests")
        self.assertEqual(planIdx, specIdx + 1)
        self.assertEqual(testsIdx, planIdx + 1)


class PlanPhaseGateTest(TestCase):

    def _setup(self):
        db.ensureProject("proj")
        taskId = db.createTask("proj", "Test task")
        earsId = db.addEars(taskId, "event", "System SHALL do X")
        db.approveEars(taskId, earsId)
        db.addEarsQualityScores(taskId, [{"dimension": "Risco", "score": 8, "justification": "ok"}], earsId=earsId)
        db.advancePhase(taskId, "spec")
        cId = db.addCriterion(taskId, earsId, "Happy path", "item created", testMethod="testCreate_Valid")
        db.approveCriterion(taskId, cId)
        db.advancePhase(taskId, "plan")
        return taskId

    def testPhaseAdvance_FromSpecToTestsWithoutPlan(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId = self._setup()

            # Act / Assert
            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "tests")

            self.assertIn("plan", str(ctx.exception).lower())

    def testPhaseGate_BlocksTestsWithoutPlan(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId = self._setup()

            # Act
            try:
                db.advancePhase(taskId, "tests")
            except ValueError:
                pass

            # Assert
            self.assertNotEqual(db.getTask(taskId)["phase"], "tests")

    def testAdvanceFromSpecToPlan_WithCompleteCriteria_Succeeds(self):
        # Arrange
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Test task")
            earsId = db.addEars(taskId, "event", "System SHALL do X")
            db.approveEars(taskId, earsId)
            db.addEarsQualityScores(taskId, [{"dimension": "Risco", "score": 8, "justification": "ok"}], earsId=earsId)
            db.advancePhase(taskId, "spec")
            cId = db.addCriterion(taskId, earsId, "Happy path", "item created", testMethod="testCreate_Valid")
            db.approveCriterion(taskId, cId)

            # Act
            db.advancePhase(taskId, "plan")

            # Assert
            self.assertEqual(db.getTask(taskId)["phase"], "plan")

    def testPlanApproval_PersistsScopeAndAdvancesToTests(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            planId = db.createPlan(taskId, "Implement feature")
            db.addPlanFile(taskId, planId, "handlers/itemHandler.py", "modify", ["createItem"])

            # Act
            db.approvePlan(taskId, planId)
            db.advancePhase(taskId, "tests")

            # Assert
            self.assertEqual(db.getTask(taskId)["phase"], "tests")
            plan = db.getPlan(taskId)
            self.assertEqual(plan["approved"], 1)


class PlanScopeTest(TestCase):

    def _setup(self):
        db.ensureProject("proj")
        taskId = db.createTask("proj", "Test task")
        earsId = db.addEars(taskId, "event", "System SHALL do X")
        db.approveEars(taskId, earsId)
        db.addEarsQualityScores(taskId, [{"dimension": "Risco", "score": 8, "justification": "ok"}], earsId=earsId)
        db.advancePhase(taskId, "spec")
        cId = db.addCriterion(taskId, earsId, "Happy path", "item created", testMethod="testCreate_Valid")
        db.approveCriterion(taskId, cId)
        db.advancePhase(taskId, "plan")
        return taskId

    def testPlanArtifact_ContainsFullTechnicalScope(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId = self._setup()

            # Act
            planId = db.createPlan(taskId, "Implement item creation endpoint")
            db.addPlanFile(taskId, planId, "handlers/itemHandler.py", "modify", ["createItem", "validatePayload"])
            db.addPlanFile(taskId, planId, "gateways/itemGateway.py", "create", ["ItemGateway", "create"])
            scope = db.getPlanScope(taskId, planId)

            # Assert
            self.assertEqual(len(scope), 2)
            self.assertEqual(scope[0]["filePath"], "handlers/itemHandler.py")
            self.assertEqual(scope[0]["action"], "modify")
            self.assertEqual(scope[0]["components"], ["createItem", "validatePayload"])
            self.assertEqual(scope[1]["filePath"], "gateways/itemGateway.py")
            self.assertEqual(scope[1]["action"], "create")

    def testGetPlanScope_Empty_WhenNoFilesAdded(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            planId = db.createPlan(taskId, "Plan with no files yet")

            # Act
            scope = db.getPlanScope(taskId, planId)

            # Assert
            self.assertEqual(scope, [])

    def testGetPlan_ReturnsNone_WhenNoPlanExists(self):
        # Arrange
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Task without plan")

            # Act
            plan = db.getPlan(taskId)

            # Assert
            self.assertIsNone(plan)


class PlanQualityTest(TestCase):

    def _setup(self):
        db.ensureProject("proj")
        taskId = db.createTask("proj", "Test task")
        earsId = db.addEars(taskId, "event", "System SHALL do X")
        db.approveEars(taskId, earsId)
        db.addEarsQualityScores(taskId, [{"dimension": "Risco", "score": 8, "justification": "ok"}], earsId=earsId)
        db.advancePhase(taskId, "spec")
        cId = db.addCriterion(taskId, earsId, "Happy path", "item created", testMethod="testCreate_Valid")
        db.approveCriterion(taskId, cId)
        db.advancePhase(taskId, "plan")
        return taskId

    def testPlanArtifact_IncludesQualityAssessmentAllDimensions(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            planId = db.createPlan(taskId, "Implement feature")
            requiredDimensions = [
                "Risco",
                "Impacto",
                "Subjetividade",
                "Ambiguidade",
                "Conflitos de decisao",
                "Ausencia de criterios de aceite",
                "Cobertura de criterios de aceite",
                "Casos de uso bem definidos",
            ]

            # Act
            for dim in requiredDimensions:
                db.addPlanQualityScore(taskId, planId, dim, 8, "Well addressed")
            scores = db.getPlanQualityScores(taskId, planId)

            # Assert
            self.assertEqual(len(scores), 8)
            scoreDimensions = [s["dimension"] for s in scores]
            for dim in requiredDimensions:
                self.assertIn(dim, scoreDimensions)

    def testPlanApproval_SurfacesLowScoringDimensions(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            planId = db.createPlan(taskId, "Implement feature")
            db.addPlanQualityScore(taskId, planId, "Risco", 2, "High risk: external API dependency")
            db.addPlanQualityScore(taskId, planId, "Impacto", 8, "Well scoped")

            # Act
            lowScores = db.getLowQualityScores(taskId, planId, threshold=4)

            # Assert
            self.assertEqual(len(lowScores), 1)
            self.assertEqual(lowScores[0]["dimension"], "Risco")
            self.assertEqual(lowScores[0]["score"], 2)
            self.assertEqual(lowScores[0]["justification"], "High risk: external API dependency")

    def testGetLowQualityScores_Empty_WhenAllScoresAboveThreshold(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            planId = db.createPlan(taskId, "Implement feature")
            db.addPlanQualityScore(taskId, planId, "Risco", 7, "Well addressed")
            db.addPlanQualityScore(taskId, planId, "Impacto", 9, "High impact, well understood")

            # Act
            lowScores = db.getLowQualityScores(taskId, planId, threshold=4)

            # Assert
            self.assertEqual(lowScores, [])

    def testQualityScore_ScoreExactlyAtThreshold_NotConsideredLow(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            planId = db.createPlan(taskId, "Implement feature")
            db.addPlanQualityScore(taskId, planId, "Ambiguidade", 4, "Exactly at threshold")

            # Act
            lowScores = db.getLowQualityScores(taskId, planId, threshold=4)

            # Assert
            self.assertEqual(lowScores, [])
