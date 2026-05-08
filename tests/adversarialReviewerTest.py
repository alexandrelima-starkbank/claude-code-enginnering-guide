import json
import tempfile
from pathlib import Path
from unittest import TestCase
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from pipeline import db
from click.testing import CliRunner
from pipeline import cli as pipelineCli


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


def _claudeProcessReturning(decisionPoints):
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = json.dumps({"decision_points": decisionPoints})
    proc.stderr = ""
    return proc


class AdversarialReviewerTest(TestCase):

    def _seedAtPhase(self, phase):
        db.initDb()
        db.ensureProject("proj")
        taskId = db.createTask("proj", "Test task")
        earsId = db.addEars(taskId, "event", "WHEN x THEN system SHALL y")
        db.approveEars(taskId, earsId)
        db.addEarsQualityScores(
            taskId,
            [{"dimension": "Risco", "score": 8, "justification": "ok"}],
            earsId=earsId,
        )
        db.advancePhase(taskId, "spec")
        cId = db.addCriterion(taskId, earsId, "scen", "then", testMethod="testFoo_Bar")
        db.approveCriterion(taskId, cId)
        db.setTestQuality(taskId, cId, "STRONG")
        if phase == "spec":
            return taskId, earsId
        planId = db.createPlan(taskId, "p")
        db.addPlanFile(taskId, planId, "x.py", "modify", ["foo"])
        for dim in ("completeness", "feasibility", "scopeClarity"):
            db.addPlanQualityScore(taskId, planId, dim, 90, "ok")
        db.approvePlan(taskId, planId)
        db.advancePhase(taskId, "plan")
        if phase == "plan":
            return taskId, earsId
        db.advancePhase(taskId, "tests")
        if phase == "tests":
            return taskId, earsId
        db.recordTest(taskId, "testFoo_Bar", True)
        db.advancePhase(taskId, "implementation")
        if phase == "implementation":
            return taskId, earsId
        return taskId, earsId

    # C01 — gate spec→plan emite ponto de decisão quando agente identifica ambiguidade
    def testGateSpecPlan_AmbiguousEars_EmitsDecisionPoint(self):
        with useTempDb():
            taskId, _ = self._seedAtPhase("spec")
            decision = {
                "context": "Validação no handler ou no gateway",
                "options": [
                    {"label": "A", "description": "Handler", "arguments": ["padrão A"]},
                    {"label": "B", "description": "Gateway", "arguments": ["padrão B"]},
                ],
            }
            with patch.object(pipelineCli, "_runReviewerSubprocess",
                              return_value=_claudeProcessReturning([decision])):
                result = CliRunner().invoke(
                    pipelineCli.cli, ["phase", "advance", taskId, "--to", "plan"],
                )

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("DECISÃO REQUERIDA", result.output)
            self.assertIn("Validação no handler ou no gateway", result.output)
            pending = db.getPendingDecisions(taskId, gate="spec_plan")
            self.assertEqual(len(pending), 1)
            self.assertEqual(db.getTask(taskId)["phase"], "spec")

    # C02 — gate spec→plan limpo: confirmação explícita e avanço
    def testGateSpecPlan_NoAmbiguity_AdvancesCleanly(self):
        with useTempDb():
            taskId, _ = self._seedAtPhase("spec")
            with patch.object(pipelineCli, "_runReviewerSubprocess",
                              return_value=_claudeProcessReturning([])):
                result = CliRunner().invoke(
                    pipelineCli.cli, ["phase", "advance", taskId, "--to", "plan"],
                )

            self.assertEqual(result.exit_code, 0)
            self.assertIn("Nenhum ponto de decisão identificado", result.output)
            self.assertEqual(db.getTask(taskId)["phase"], "plan")

    # C03 — gate tests→implementation emite ponto de decisão
    def testGateTestsImpl_MockStrategyChoice_EmitsDecisionPoint(self):
        with useTempDb():
            taskId, _ = self._seedAtPhase("tests")
            decision = {
                "context": "Mock vs integração",
                "options": [
                    {"label": "A", "description": "Mock", "arguments": ["rápido"]},
                    {"label": "B", "description": "Integração", "arguments": ["fiel"]},
                ],
            }
            with patch.object(pipelineCli, "_runReviewerSubprocess",
                              return_value=_claudeProcessReturning([decision])):
                result = CliRunner().invoke(
                    pipelineCli.cli, ["phase", "advance", taskId, "--to", "implementation"],
                )

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("DECISÃO REQUERIDA", result.output)
            pending = db.getPendingDecisions(taskId, gate="tests_impl")
            self.assertEqual(len(pending), 1)
            self.assertEqual(db.getTask(taskId)["phase"], "tests")

    # C04 — gate implementation→mutation emite ponto de decisão
    def testGateImplMutation_PlacementChoice_EmitsDecisionPoint(self):
        with useTempDb():
            taskId, _ = self._seedAtPhase("implementation")
            decision = {
                "context": "Validação no handler ou no gateway",
                "options": [
                    {"label": "A", "description": "Handler", "arguments": ["coeso"]},
                    {"label": "B", "description": "Gateway", "arguments": ["isolado"]},
                ],
            }
            with patch.object(pipelineCli, "_runReviewerSubprocess",
                              return_value=_claudeProcessReturning([decision])):
                result = CliRunner().invoke(
                    pipelineCli.cli, ["phase", "advance", taskId, "--to", "mutation"],
                )

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("DECISÃO REQUERIDA", result.output)
            pending = db.getPendingDecisions(taskId, gate="impl_mutation")
            self.assertEqual(len(pending), 1)
            self.assertEqual(db.getTask(taskId)["phase"], "implementation")

    # C05 — bloqueio quando há decisão pendente já registrada (sem invocar agente novamente)
    def testPhaseAdvance_PendingDecision_BlocksAdvancement(self):
        with useTempDb():
            taskId, _ = self._seedAtPhase("spec")
            db.addDecisionPoint(
                taskId,
                gate="spec_plan",
                context="dilema",
                options=[
                    {"label": "A", "description": "x", "arguments": ["a1"]},
                    {"label": "B", "description": "y", "arguments": ["b1"]},
                ],
            )

            invoked = MagicMock()
            with patch.object(pipelineCli, "_runReviewerSubprocess", invoked):
                result = CliRunner().invoke(
                    pipelineCli.cli, ["phase", "advance", taskId, "--to", "plan"],
                )

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("decisão pendente", result.output.lower())
            invoked.assert_not_called()
            self.assertEqual(db.getTask(taskId)["phase"], "spec")

    # C06 — decisão resolvida persiste no ChromaDB via vector.addContext
    def testDecisionResolve_PersistsToChromaDb(self):
        with useTempDb():
            taskId, _ = self._seedAtPhase("spec")
            pointId = db.addDecisionPoint(
                taskId,
                gate="spec_plan",
                context="dilema",
                options=[
                    {"label": "A", "description": "x", "arguments": ["a1"]},
                    {"label": "B", "description": "y", "arguments": ["b1"]},
                ],
            )

            addCtx = MagicMock()
            with patch.object(pipelineCli, "vector") as vec:
                vec.addContext = addCtx
                vec.isAvailable = lambda: True
                result = CliRunner().invoke(
                    pipelineCli.cli,
                    ["decision", "resolve", taskId, "--point", pointId,
                     "--choice", "opção A: handler", "--rationale", "coesão local"],
                )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(addCtx.call_count, 1)
            args, kwargs = addCtx.call_args
            allArgs = list(args) + list(kwargs.values())
            joined = " ".join(str(a) for a in allArgs)
            self.assertIn("decision", joined)
            self.assertIn(taskId, joined)
            self.assertIn("opção A", joined)
            self.assertIn("coesão local", joined)
            resolved = db.getDecisionPoint(taskId, pointId)
            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["choice"], "opção A: handler")

    # C07 — confirmação explícita "Nenhum ponto de decisão identificado"
    def testGate_NoDecisionPoints_ExplicitConfirmation(self):
        with useTempDb():
            taskId, _ = self._seedAtPhase("spec")
            with patch.object(pipelineCli, "_runReviewerSubprocess",
                              return_value=_claudeProcessReturning([])):
                result = CliRunner().invoke(
                    pipelineCli.cli, ["phase", "advance", taskId, "--to", "plan"],
                )

            self.assertEqual(result.exit_code, 0)
            self.assertIn("Nenhum ponto de decisão identificado", result.output)

    # C08 — argumentos sem marcadores de preferência
    def testDecisionPoint_ArgumentsNeutral_NoPreferenceMarkers(self):
        self.assertFalse(pipelineCli._containsPreferenceMarker("é coeso e local"))
        self.assertFalse(pipelineCli._containsPreferenceMarker("isolamento permite reuso"))
        self.assertTrue(pipelineCli._containsPreferenceMarker("essa é a melhor opção"))
        self.assertTrue(pipelineCli._containsPreferenceMarker("recomendado pelo time"))
        self.assertTrue(pipelineCli._containsPreferenceMarker("você deveria escolher A"))
        self.assertTrue(pipelineCli._containsPreferenceMarker("This is the preferred path"))
