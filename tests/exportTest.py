import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from unittest import TestCase, main

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline-cli"))

from pipeline import db
from pipeline.export import formatPhaseBar, formatTask, generateTasksMd


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


class FormatPhaseBarTest(TestCase):

    def testFormatPhaseBar_Requirements(self):
        result = formatPhaseBar("requirements")
        self.assertIn("requirements →", result)
        self.assertNotIn("✓", result.split("requirements")[0])

    def testFormatPhaseBar_MiddlePhase(self):
        result = formatPhaseBar("tests")
        self.assertIn("requirements ✓", result)
        self.assertIn("spec ✓", result)
        self.assertIn("tests →", result)
        self.assertNotIn("implementation ✓", result)

    def testFormatPhaseBar_Done(self):
        result = formatPhaseBar("done")
        self.assertIn("done →", result)
        self.assertIn("mutation ✓", result)


class FormatTaskTest(TestCase):

    def testFormatTask_NotFound(self):
        with useTempDb():
            db.initDb()
            self.assertEqual(formatTask("T999"), "")

    def testFormatTask_BasicTask(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "My feature")
            result = formatTask(taskId)
            self.assertIn("### T1 — My feature", result)
            self.assertIn("**Projeto:** proj", result)
            self.assertIn("**Status:** pendente", result)
            self.assertIn("**Fase:**", result)

    def testFormatTask_WithEars(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Feature")
            db.addEars(taskId, "event", "When user clicks save")
            db.approveEars(taskId, "R01")
            result = formatTask(taskId)
            self.assertIn("[R01]", result)
            self.assertIn("✓", result)
            self.assertIn("(event)", result)
            self.assertIn("When user clicks save", result)

    def testFormatTask_WithoutEars_ShowsPlaceholder(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Feature")
            result = formatTask(taskId)
            self.assertIn("não definidos", result)
            self.assertIn("pipeline ears add", result)

    def testFormatTask_WithCriteria(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Feature")
            db.addEars(taskId, "event", "When user saves")
            db.addCriterion(
                taskId, "R01", "Happy path", "item saved",
                givenText="valid data",
                whenText="save clicked",
                testMethod="testSave_Valid",
            )
            result = formatTask(taskId)
            self.assertIn("**Cenário: Happy path**", result)
            self.assertIn("Dado: valid data", result)
            self.assertIn("Quando: save clicked", result)
            self.assertIn("Então: item saved", result)
            self.assertIn("`testSave_Valid`", result)

    def testFormatTask_WithTraceabilityMatrix(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Feature")
            db.addEars(taskId, "event", "Req one")
            db.addCriterion(taskId, "R01", "Scenario", "then",
                            testMethod="testX")
            result = formatTask(taskId)
            self.assertIn("Matriz de Rastreabilidade", result)
            self.assertIn("R01", result)
            self.assertIn("`testX`", result)

    def testFormatTask_EarsWithoutCriterion_ShowsSemCenario(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Feature")
            db.addEars(taskId, "event", "Req one")
            db.addEars(taskId, "state", "Req two")
            db.addCriterion(taskId, "R01", "Scenario", "then")
            result = formatTask(taskId)
            self.assertIn("sem cenário", result)

    def testFormatTask_WithMetrics(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Feature")
            db.addEars(taskId, "event", "Req")
            db.addCriterion(taskId, "R01", "Scenario", "then",
                            testMethod="testX")
            db.setTestQuality(taskId, "C01", "STRONG")
            db.recordTest(taskId, "testX", True)
            db.recordMutation(taskId, 8, 8)
            result = formatTask(taskId)
            self.assertIn("**Métricas:**", result)
            self.assertIn("EARS:", result)
            self.assertIn("Spec:", result)
            self.assertIn("Testes:", result)
            self.assertIn("Mutação:", result)
            self.assertIn("100%", result)

    def testFormatTask_WithDescription(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Feature", "Some details")
            result = formatTask(taskId)
            self.assertIn("**Descrição:** Some details", result)


class GenerateTasksMdTest(TestCase):

    def testGenerateTasksMd_Header(self):
        with useTempDb():
            db.initDb()
            result = generateTasksMd()
            self.assertIn("# TASKS.md", result)
            self.assertIn("Gerado automaticamente", result)
            self.assertIn("NÃO EDITAR DIRETAMENTE", result)

    def testGenerateTasksMd_EmptyProject(self):
        with useTempDb():
            db.initDb()
            result = generateTasksMd()
            self.assertIn("Nenhuma tarefa ativa", result)
            self.assertIn("Nenhuma tarefa concluída", result)

    def testGenerateTasksMd_ActiveTasks(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            db.createTask("proj", "Active task")
            result = generateTasksMd(projectId="proj")
            self.assertIn("## Tarefas Ativas", result)
            self.assertIn("Active task", result)

    def testGenerateTasksMd_CompletedTasks(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Done task")
            db.updateTask(taskId, status="concluído")
            result = generateTasksMd(projectId="proj")
            self.assertIn("## Histórico", result)
            self.assertIn("Done task", result)

    def testGenerateTasksMd_SeparatesActiveFromDone(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            t1 = db.createTask("proj", "Active one")
            t2 = db.createTask("proj", "Done one")
            db.updateTask(t2, status="concluído")
            result = generateTasksMd(projectId="proj")
            activeSection = result.split("## Histórico")[0]
            historySection = result.split("## Histórico")[1]
            self.assertIn("Active one", activeSection)
            self.assertNotIn("Done one", activeSection)
            self.assertIn("Done one", historySection)
            self.assertNotIn("Active one", historySection)

    def testGenerateTasksMd_SingleTask(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Single")
            result = generateTasksMd(taskId=taskId)
            self.assertIn("Single", result)

    def testGenerateTasksMd_FilterByProject(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj-a")
            db.ensureProject("proj-b")
            db.createTask("proj-a", "Task A")
            db.createTask("proj-b", "Task B")
            result = generateTasksMd(projectId="proj-a")
            self.assertIn("Task A", result)
            self.assertNotIn("Task B", result)

    def testGenerateTasksMd_CancelledTaskInHistory(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            taskId = db.createTask("proj", "Cancelled task")
            db.updateTask(taskId, status="cancelado")
            result = generateTasksMd(projectId="proj")
            historySection = result.split("## Histórico")[1]
            activeSection = result.split("## Histórico")[0]
            self.assertIn("Cancelled task", historySection)
            self.assertNotIn("Cancelled task", activeSection)

    def testGenerateTasksMd_CancelledTaskNotInActiveTasks(self):
        with useTempDb():
            db.initDb()
            db.ensureProject("proj")
            t1 = db.createTask("proj", "Active task")
            t2 = db.createTask("proj", "Cancelled task")
            db.updateTask(t1, status="em andamento")
            db.updateTask(t2, status="cancelado")
            result = generateTasksMd(projectId="proj")
            activeSection = result.split("## Histórico")[0]
            self.assertIn("Active task", activeSection)
            self.assertNotIn("Cancelled task", activeSection)


if __name__ == "__main__":
    main()
