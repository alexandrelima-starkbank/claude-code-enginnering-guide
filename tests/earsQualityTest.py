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
from click.testing import CliRunner
from pipeline.cli import cli

DIMENSIONS = [
    "Risco",
    "Impacto",
    "Subjetividade",
    "Ambiguidade",
    "Conflitos de decisao",
    "Ausencia de criterios de aceite",
    "Cobertura de criterios de aceite",
    "Casos de uso bem definidos",
]


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


def makeScores(score=8):
    return [
        {"dimension": dim, "score": score, "justification": "Adequate coverage"}
        for dim in DIMENSIONS
    ]


def setupTaskWithEars(text="WHEN user creates item THEN system SHALL persist it"):
    db.initDb()
    db.ensureProject("proj")
    taskId = db.createTask("proj", "Test task")
    earsId = db.addEars(taskId, "event", text)
    return taskId, earsId


class EarsApproveQualityDisplayTest(TestCase):

    def testEarsApprove_Single_DisplaysQualityScore(self):
        # Arrange
        with useTempDb():
            taskId, earsId = setupTaskWithEars()
            fakeScores = makeScores(8)

            with patch("pipeline.cli.evaluateQuality", return_value=fakeScores) as mockEval:
                with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                    runner = CliRunner()

                    # Act
                    result = runner.invoke(cli, ["ears", "approve", taskId, earsId])

            # Assert
            self.assertEqual(result.exit_code, 0)
            mockEval.assert_called_once()
            self.assertIn("Risco", result.output)
            self.assertIn("8", result.output)

    def testEarsApprove_All_DisplaysIndividualAndAggregateScores(self):
        # Arrange
        with useTempDb():
            taskId, _ = setupTaskWithEars()
            db.addEars(taskId, "event", "WHEN user deletes item THEN system SHALL remove it")
            fakeScores = makeScores(7)

            with patch("pipeline.cli.evaluateQuality", return_value=fakeScores):
                with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                    runner = CliRunner()

                    # Act
                    result = runner.invoke(cli, ["ears", "approve", taskId, "all"])

            # Assert
            self.assertEqual(result.exit_code, 0)
            self.assertIn("score agregado", result.output.lower())
            self.assertIn("r01", result.output.lower())
            self.assertIn("r02", result.output.lower())

    def testEarsApprove_LowScore_HighlightedWithoutBlocking(self):
        # Arrange
        with useTempDb():
            taskId, earsId = setupTaskWithEars()
            fakeScores = [
                {"dimension": "Ambiguidade", "score": 2, "justification": "Too vague"},
                {"dimension": "Risco", "score": 8, "justification": "Well mitigated"},
            ]

            with patch("pipeline.cli.evaluateQuality", return_value=fakeScores):
                with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                    runner = CliRunner()

                    # Act
                    result = runner.invoke(cli, ["ears", "approve", taskId, earsId])

            # Assert
            self.assertEqual(result.exit_code, 0)
            self.assertIn("LOW SCORE", result.output)
            self.assertIn("Ambiguidade", result.output)
            task = db.getTask(taskId)
            ears = db.listEars(taskId)
            self.assertTrue(any(e["approved"] for e in ears))

    def testEarsApprove_NoApiKey_ProceedsWithWarning(self):
        # Arrange
        with useTempDb():
            taskId, earsId = setupTaskWithEars()

            with patch("pipeline.cli.evaluateQuality", return_value=[]):
                with patch.dict(os.environ, {}, clear=True):
                    if "ANTHROPIC_API_KEY" in os.environ:
                        del os.environ["ANTHROPIC_API_KEY"]
                    runner = CliRunner()

                    # Act
                    result = runner.invoke(cli, ["ears", "approve", taskId, earsId])

            # Assert
            self.assertEqual(result.exit_code, 0)
            self.assertIn("quality scoring", result.output.lower())
            ears = db.listEars(taskId)
            self.assertTrue(any(e["approved"] for e in ears))


class EarsQualityPersistenceTest(TestCase):

    def testEarsApprove_ScoresPersistedToDb(self):
        # Arrange
        with useTempDb() as dbPath:
            taskId, earsId = setupTaskWithEars()
            fakeScores = makeScores(9)

            with patch("pipeline.cli.evaluateQuality", return_value=fakeScores):
                with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                    runner = CliRunner()
                    runner.invoke(cli, ["ears", "approve", taskId, earsId])

            # Act
            scores = db.getEarsQualityScores(taskId)

            # Assert
            self.assertGreater(len(scores), 0)
            dimensions = [s["dimension"] for s in scores]
            self.assertIn("Risco", dimensions)
            self.assertIn("Ambiguidade", dimensions)
