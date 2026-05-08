import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from contextlib import contextmanager

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline-cli"))

from pipeline import db


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


class PhaseGateTest(TestCase):

    def _setup(self):
        db.ensureProject("proj")
        return db.createTask("proj", "Test task")

    def _addApprovedEars(self, taskId, text="System SHALL do X"):
        earsId = db.addEars(taskId, "event", text)
        db.approveEars(taskId, earsId)
        return earsId

    def _addQualityScores(self, taskId, earsId=None):
        db.addEarsQualityScores(
            taskId,
            [{"dimension": "Risco", "score": 8, "justification": "ok"}],
            earsId=earsId,
        )

    def _advanceToSpec(self, taskId):
        earsId = self._addApprovedEars(taskId)
        self._addQualityScores(taskId, earsId=earsId)
        db.advancePhase(taskId, "spec")
        return earsId

    def _addApprovedCriterion(self, taskId, earsId, testMethod="testSomething"):
        cId = db.addCriterion(taskId, earsId, "scenario", "then text", testMethod=testMethod)
        db.approveCriterion(taskId, cId)
        db.setTestQuality(taskId, cId, "STRONG")
        return cId

    # ── R01: requirements → spec ──────────────────────────────────────────────

    def testAdvanceToSpec_WithUnapprovedEars_Rejects(self):
        # Critério: lança ValueError com mensagem identificando os EARS não aprovados
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            db.addEars(taskId, "event", "System SHALL do X")

            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "spec")

            self.assertIn("EARS", str(ctx.exception))

    def testAdvanceToSpec_WithNoQualityScores_Rejects(self):
        # Critério: lança ValueError quando EARS aprovados mas sem quality scores
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            self._addApprovedEars(taskId)

            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "spec")

            self.assertIn("quality", str(ctx.exception).lower())

    def testAdvanceToSpec_WithQualityScores_Succeeds(self):
        # Critério: executa sem erro quando EARS aprovados e quality scores registrados
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            earsId = self._addApprovedEars(taskId)
            db.addEarsQualityScores(taskId, [{"dimension": "Risco", "score": 8, "justification": "ok"}], earsId=earsId)

            db.advancePhase(taskId, "spec")

            self.assertEqual(db.getTask(taskId)["phase"], "spec")

    # ── R02: spec → plan (criteria/testMethod gate moved here) ───────────────

    def testAdvanceToPlan_WithEarsHavingNoCriterion_Rejects(self):
        # Critério: lança ValueError identificando o EARS sem critério
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            self._advanceToSpec(taskId)

            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "plan")

            self.assertIn("critério", str(ctx.exception))

    def testAdvanceToPlan_WithCriterionMissingTestMethod_Rejects(self):
        # Critério: lança ValueError identificando o critério sem testMethod
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            earsId = self._advanceToSpec(taskId)
            cId = db.addCriterion(taskId, earsId, "scenario", "then", testMethod=None)
            db.approveCriterion(taskId, cId)

            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "plan")

            self.assertIn("testMethod", str(ctx.exception))

    def testAdvanceToPlan_WithCompleteCriteria_AndThenToTests_Succeeds(self):
        # Critério: spec→plan com critérios completos, depois plan→tests com plan aprovado
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            earsId = self._advanceToSpec(taskId)
            self._addApprovedCriterion(taskId, earsId, testMethod="testSomething")
            db.advancePhase(taskId, "plan")
            planId = db.createPlan(taskId, "test plan")
            db.approvePlan(taskId, planId)

            db.advancePhase(taskId, "tests")

            self.assertEqual(db.getTask(taskId)["phase"], "tests")

    # ── R03: tests → implementation ───────────────────────────────────────────

    def testAdvanceToImplementation_WithMissingTestResult_Rejects(self):
        # Critério: lança ValueError identificando testFoo como não executado
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            earsId = self._advanceToSpec(taskId)
            self._addApprovedCriterion(taskId, earsId, testMethod="testFoo")
            db.advancePhase(taskId, "plan")
            planId = db.createPlan(taskId, "p")
            db.approvePlan(taskId, planId)
            db.advancePhase(taskId, "tests")

            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "implementation")

            self.assertIn("testFoo", str(ctx.exception))

    def testAdvanceToImplementation_WithFailedTestResult_Rejects(self):
        # Critério: lança ValueError quando testMethod tem testResult com passed=0
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            earsId = self._advanceToSpec(taskId)
            self._addApprovedCriterion(taskId, earsId, testMethod="testFoo")
            db.advancePhase(taskId, "plan")
            planId = db.createPlan(taskId, "p")
            db.approvePlan(taskId, planId)
            db.advancePhase(taskId, "tests")
            db.recordTest(taskId, "testFoo", False)

            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "implementation")

            self.assertIn("testFoo", str(ctx.exception))

    def testAdvanceToImplementation_WithAllMethodsPassing_Succeeds(self):
        # Critério: executa sem erro quando todos testMethods têm testResult passed=1
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            earsId = self._advanceToSpec(taskId)
            self._addApprovedCriterion(taskId, earsId, testMethod="testFoo")
            db.advancePhase(taskId, "plan")
            planId = db.createPlan(taskId, "p")
            db.approvePlan(taskId, planId)
            db.advancePhase(taskId, "tests")
            db.recordTest(taskId, "testFoo", True)

            db.advancePhase(taskId, "implementation")

            self.assertEqual(db.getTask(taskId)["phase"], "implementation")

    # ── R04: mutation → done ──────────────────────────────────────────────────

    def _advanceToMutation(self, taskId):
        earsId = self._advanceToSpec(taskId)
        self._addApprovedCriterion(taskId, earsId, testMethod="testFoo")
        db.advancePhase(taskId, "plan")
        planId = db.createPlan(taskId, "p")
        db.approvePlan(taskId, planId)
        db.advancePhase(taskId, "tests")
        db.recordTest(taskId, "testFoo", True)
        db.advancePhase(taskId, "implementation")
        db.advancePhase(taskId, "mutation")

    def testAdvanceToDone_WithNoMutationResults_Rejects(self):
        # Critério: lança ValueError quando nenhum registro de mutação existe
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            self._advanceToMutation(taskId)

            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "done")

            self.assertIn("mutation", str(ctx.exception).lower())

    def testAdvanceToDone_WithPartialMutationScore_Rejects(self):
        # Critério: lança ValueError quando mutation score < 100%
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            self._advanceToMutation(taskId)
            db.recordMutation(taskId, 10, 9)

            with self.assertRaises(ValueError) as ctx:
                db.advancePhase(taskId, "static-analysis")

            self.assertIn("100", str(ctx.exception))

    def testAdvanceToDone_WithFullMutationScore_Succeeds(self):
        # Critério: executa sem erro quando mutation score = 100%
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            self._advanceToMutation(taskId)
            db.recordMutation(taskId, 10, 10)

            db.advancePhase(taskId, "static-analysis")

            self.assertEqual(db.getTask(taskId)["phase"], "static-analysis")

    # ── R05: pipeline phase check command ─────────────────────────────────────

    def testPhaseCheck_WithFailingGate_PrintsFailAndExitsOne(self):
        # Critério: output contém FAIL para o gate afetado e exit code é 1
        fakeGates = [("EARS aprovados", False, "EARS não aprovados: R01")]
        with patch("pipeline.cli.checkPhaseGates", return_value=fakeGates):
            from click.testing import CliRunner
            from pipeline.cli import cli
            runner = CliRunner()
            result = runner.invoke(cli, ["phase", "check", "T1", "--to", "spec"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("FAIL", result.output)

    def testPhaseCheck_WithAllGatesPassing_ExitsZero(self):
        # Critério: todos os gates mostram PASS e exit code é 0
        fakeGates = [
            ("qualidade", True, "2 critérios revisados"),
            ("Testes passando", True, "2 testMethods passing"),
        ]
        with patch("pipeline.cli.checkPhaseGates", return_value=fakeGates):
            from click.testing import CliRunner
            from pipeline.cli import cli
            runner = CliRunner()
            result = runner.invoke(cli, ["phase", "check", "T1", "--to", "implementation"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("PASS", result.output)

    # ── R06: no --force flag ──────────────────────────────────────────────────

    def testPhaseAdvance_ForceFlagNotAccepted(self):
        # Critério: pipeline phase advance com --force falha com 'no such option'
        with useTempDb():
            db.initDb()
            taskId = self._setup()

            from click.testing import CliRunner
            from pipeline.cli import cli
            runner = CliRunner()
            result = runner.invoke(cli, ["phase", "advance", taskId, "--to", "spec", "--force"])

            self.assertEqual(result.exit_code, 2)
            self.assertIn("no such option", result.output.lower())

    # ── T84: blast-radius advisory on phase advance → tests ───────────────────

    def testPhaseAdvanceToTests_InvokesBlastRadius(self):
        # Critério: advisory exibido com arquivos do scope quando avança para tests
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            earsId = self._advanceToSpec(taskId)
            self._addApprovedCriterion(taskId, earsId, testMethod="testSomething")
            db.advancePhase(taskId, "plan")
            planId = db.createPlan(taskId, "test plan")
            db.addPlanFile(taskId, planId, "handlers/itemHandler.py", "modify", ["createItem"])
            db.approvePlan(taskId, planId)

            from click.testing import CliRunner
            from pipeline.cli import cli
            runner = CliRunner()
            result = runner.invoke(cli, ["phase", "advance", taskId, "--to", "tests"])

            self.assertEqual(result.exit_code, 0)
            self.assertIn("BLAST-RADIUS ADVISORY", result.output)
            self.assertIn("handlers/itemHandler.py", result.output)
            self.assertIn("fase: tests", result.output)

    def testPhaseAdvanceToTests_BlastRadiusFailure_WarnsAndAdvances(self):
        # Critério: se getPlan lança exceção, aviso é emitido e phase ainda avança
        with useTempDb():
            db.initDb()
            taskId = self._setup()
            earsId = self._advanceToSpec(taskId)
            self._addApprovedCriterion(taskId, earsId, testMethod="testSomething")
            db.advancePhase(taskId, "plan")
            planId = db.createPlan(taskId, "test plan")
            db.approvePlan(taskId, planId)

            from click.testing import CliRunner
            from pipeline.cli import cli
            from unittest.mock import patch as mockPatch
            runner = CliRunner()
            with mockPatch("pipeline.cli.getPlan", side_effect=Exception("db error")):
                result = runner.invoke(cli, ["phase", "advance", taskId, "--to", "tests"])

            self.assertEqual(result.exit_code, 0)
            self.assertIn("AVISO", result.output)
            self.assertIn("fase: tests", result.output)
