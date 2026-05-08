import tempfile
from pathlib import Path
from unittest import TestCase
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from pipeline import db
from click.testing import CliRunner
from pipeline import cli as pipelineCli
from pipeline import staticAnalysis as sa


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


def _seedAtMutation(taskId="T01"):
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
    cId = db.addCriterion(taskId, earsId, "scen", "then", testMethod="testFoo")
    db.approveCriterion(taskId, cId)
    db.setTestQuality(taskId, cId, "STRONG")
    planId = db.createPlan(taskId, "p")
    db.addPlanFile(taskId, planId, "a.py", "modify", ["foo"])
    for dim in ("completeness", "feasibility", "scopeClarity"):
        db.addPlanQualityScore(taskId, planId, dim, 90, "ok")
    db.approvePlan(taskId, planId)
    db.advancePhase(taskId, "plan")
    db.advancePhase(taskId, "tests")
    db.recordTest(taskId, "testFoo", True)
    db.advancePhase(taskId, "implementation")
    db.recordMutation(taskId, 1, 1)
    db.advancePhase(taskId, "mutation")
    return taskId


class StaticAnalysisTest(TestCase):

    # C01 — invocação automática
    def testPhaseAdvanceToStaticAnalysis_InvokesRun(self):
        with useTempDb():
            taskId = _seedAtMutation()
            invoke = MagicMock(return_value=True)
            with patch.object(pipelineCli, "_invokeStaticAnalysis", invoke):
                CliRunner().invoke(
                    pipelineCli.cli, ["phase", "advance", taskId, "--to", "static-analysis"],
                )
            invoke.assert_called_once_with(taskId)

    # C02 — todas as ferramentas chamadas
    def testStaticAnalysisRun_AllToolsInvoked(self):
        with useTempDb():
            taskId = _seedAtMutation()
            calls = {"ruff": 0, "bandit": 0, "vulture": 0, "pylint": 0, "radon": 0}

            def mk(name, ok=True):
                def f(files):
                    calls[name] += 1
                    return {"tool": name, "value": 0, "threshold": 0, "passed": ok, "details": []}
                return f

            with patch.object(sa, "_filesFromGitDiff", return_value=["a.py"]), \
                 patch.object(sa, "runRuff", side_effect=mk("ruff")), \
                 patch.object(sa, "runBandit", side_effect=mk("bandit")), \
                 patch.object(sa, "runVulture", side_effect=mk("vulture")), \
                 patch.object(sa, "runPylint", side_effect=mk("pylint")), \
                 patch.object(sa, "runRadon", side_effect=lambda f: [{"tool": "radon_cc", "value": 1, "threshold": 10, "passed": True, "details": []}, {"tool": "radon_mi", "value": 100, "threshold": 65, "passed": True, "details": []}]):
                results = sa.runAll(taskId, files=["a.py"])
            tools = {r["tool"] for r in results}
            self.assertEqual(tools, {"ruff", "bandit", "vulture", "pylint", "radon_cc", "radon_mi"})

    # C03 — divergência planScope advisory
    def testStaticAnalysisRun_PlanScopeDivergence_WarnsButRuns(self):
        with useTempDb():
            taskId = _seedAtMutation()
            warning = sa._compareWithPlanScope(taskId, ["a.py", "b.py"])
            self.assertIn("b.py", " ".join(warning))

    # C04 — persistência
    def testStaticAnalysisResults_PersistedToDb(self):
        with useTempDb():
            taskId = _seedAtMutation()
            db.addStaticAnalysisResult(taskId, "ruff", "violation_count", 0, 0, True, [])
            rows = db.getStaticAnalysisResults(taskId)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["tool"], "ruff")
            self.assertEqual(rows[0]["passed"], 1)
            self.assertEqual(rows[0]["threshold"], 0)

    # C05 — threshold marca falha
    def testThresholds_ViolationMarksFailed(self):
        with useTempDb():
            taskId = _seedAtMutation()
            with patch.object(sa, "_filesFromGitDiff", return_value=["a.py"]), \
                 patch.object(sa, "runRuff", return_value={"tool": "ruff", "value": 1, "threshold": 0, "passed": False, "details": ["a.py:5: E501"]}), \
                 patch.object(sa, "runBandit", return_value={"tool": "bandit", "value": 0, "threshold": 0, "passed": True, "details": []}), \
                 patch.object(sa, "runVulture", return_value={"tool": "vulture", "value": 0, "threshold": 0, "passed": True, "details": []}), \
                 patch.object(sa, "runPylint", return_value={"tool": "pylint", "value": 0, "threshold": 0, "passed": True, "details": []}), \
                 patch.object(sa, "runRadon", return_value=[{"tool": "radon_cc", "value": 1, "threshold": 10, "passed": True, "details": []}, {"tool": "radon_mi", "value": 100, "threshold": 65, "passed": True, "details": []}]):
                results = sa.runAll(taskId, files=["a.py"])
            ruffResult = [r for r in results if r["tool"] == "ruff"][0]
            self.assertFalse(ruffResult["passed"])

    # C06 — bloqueio com detalhamento
    def testPhaseAdvance_ThresholdViolation_BlocksWithDetails(self):
        with useTempDb():
            taskId = _seedAtMutation()
            with patch.object(sa, "_filesFromGitDiff", return_value=["a.py"]), \
                 patch.object(sa, "runRuff", return_value={"tool": "ruff", "value": 1, "threshold": 0, "passed": False, "details": ["a.py:5: E501 line too long"]}), \
                 patch.object(sa, "runBandit", return_value={"tool": "bandit", "value": 0, "threshold": 0, "passed": True, "details": []}), \
                 patch.object(sa, "runVulture", return_value={"tool": "vulture", "value": 0, "threshold": 0, "passed": True, "details": []}), \
                 patch.object(sa, "runPylint", return_value={"tool": "pylint", "value": 0, "threshold": 0, "passed": True, "details": []}), \
                 patch.object(sa, "runRadon", return_value=[{"tool": "radon_cc", "value": 1, "threshold": 10, "passed": True, "details": []}, {"tool": "radon_mi", "value": 100, "threshold": 65, "passed": True, "details": []}]):
                result = CliRunner().invoke(
                    pipelineCli.cli, ["phase", "advance", taskId, "--to", "static-analysis"],
                )
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("a.py:5", result.output)
            self.assertEqual(db.getTask(taskId)["phase"], "mutation")

    # C07 — liberação em sucesso
    def testPhaseAdvance_AllPass_AdvancesPhase(self):
        with useTempDb():
            taskId = _seedAtMutation()
            with patch.object(sa, "_filesFromGitDiff", return_value=["a.py"]), \
                 patch.object(sa, "runRuff", return_value={"tool": "ruff", "value": 0, "threshold": 0, "passed": True, "details": []}), \
                 patch.object(sa, "runBandit", return_value={"tool": "bandit", "value": 0, "threshold": 0, "passed": True, "details": []}), \
                 patch.object(sa, "runVulture", return_value={"tool": "vulture", "value": 0, "threshold": 0, "passed": True, "details": []}), \
                 patch.object(sa, "runPylint", return_value={"tool": "pylint", "value": 0, "threshold": 0, "passed": True, "details": []}), \
                 patch.object(sa, "runRadon", return_value=[{"tool": "radon_cc", "value": 3, "threshold": 10, "passed": True, "details": []}, {"tool": "radon_mi", "value": 80, "threshold": 65, "passed": True, "details": []}]):
                result = CliRunner().invoke(
                    pipelineCli.cli, ["phase", "advance", taskId, "--to", "static-analysis"],
                )
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(db.getTask(taskId)["phase"], "static-analysis")

    # C08 — gate static-analysis → done
    def testPhaseAdvanceToDone_NoPassingRun_Blocks(self):
        with useTempDb():
            taskId = _seedAtMutation()
            db.advancePhase(taskId, "static-analysis")
            result = CliRunner().invoke(
                pipelineCli.cli, ["phase", "advance", taskId, "--to", "done"],
            )
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("static", result.output.lower())

    # C09 — exclusão de testes do radon
    def testRadon_TestFilesExcluded(self):
        excluded = sa._excludeTestFiles(["foo.py", "fooTest.py", "tests/barTest.py", "test_x.py", "x_test.py"])
        self.assertEqual(excluded, ["foo.py"])

    # C10 — ferramenta ausente
    def testStaticAnalysisRun_MissingTool_FailsClearly(self):
        with useTempDb():
            taskId = _seedAtMutation()
            def missing(files):
                raise FileNotFoundError("ruff")
            with patch.object(sa, "_filesFromGitDiff", return_value=["a.py"]), \
                 patch.object(sa, "runRuff", side_effect=missing):
                with self.assertRaises(sa.MissingToolError) as ctx:
                    sa.runAll(taskId, files=["a.py"])
            self.assertIn("ruff", str(ctx.exception))
            self.assertIn("install", str(ctx.exception).lower())
