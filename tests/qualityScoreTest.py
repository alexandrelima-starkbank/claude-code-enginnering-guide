import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline-cli"))

from pipeline import db
from pipeline.llm import evaluateQuality


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

REQUIRED_DIMENSIONS = [
    "Risco",
    "Impacto",
    "Subjetividade",
    "Ambiguidade",
    "Conflitos de decisao",
    "Ausencia de criterios de aceite",
    "Cobertura de criterios de aceite",
    "Casos de uso bem definidos",
]


def makeFakeResponse(scores):
    import json
    content = json.dumps({"dimensions": scores})
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    return msg


class EvaluateQualityTest(TestCase):

    def testEvaluateQuality_ReturnsAllEightDimensions(self):
        # Arrange
        fakeScores = [
            {"dimension": dim, "score": 8, "justification": "Well addressed"}
            for dim in REQUIRED_DIMENSIONS
        ]
        fakeResponse = makeFakeResponse(fakeScores)

        with patch("pipeline.llm.anthropic") as mockAnthropic:
            mockAnthropic.Anthropic.return_value.messages.create.return_value = fakeResponse

            # Act
            result = evaluateQuality(
                texts=["WHEN user creates item THEN system SHALL persist it"],
                dimensions=REQUIRED_DIMENSIONS,
            )

        # Assert
        self.assertEqual(len(result), 8)
        resultDimensions = [r["dimension"] for r in result]
        for dim in REQUIRED_DIMENSIONS:
            self.assertIn(dim, resultDimensions)

    def testEvaluateQuality_EachEntryHasScoreAndJustification(self):
        # Arrange
        fakeScores = [
            {"dimension": dim, "score": 7, "justification": "Acceptable coverage"}
            for dim in REQUIRED_DIMENSIONS
        ]
        fakeResponse = makeFakeResponse(fakeScores)

        with patch("pipeline.llm.anthropic") as mockAnthropic:
            mockAnthropic.Anthropic.return_value.messages.create.return_value = fakeResponse

            # Act
            result = evaluateQuality(
                texts=["WHEN user creates item THEN system SHALL persist it"],
                dimensions=REQUIRED_DIMENSIONS,
            )

        # Assert
        for entry in result:
            self.assertIn("dimension", entry)
            self.assertIn("score", entry)
            self.assertIn("justification", entry)
            self.assertIsInstance(entry["score"], int)
            self.assertGreaterEqual(entry["score"], 0)
            self.assertLessEqual(entry["score"], 10)

    def testEvaluateQuality_LowScoreIdentifiedCorrectly(self):
        # Arrange
        fakeScores = [
            {"dimension": "Ambiguidade", "score": 2, "justification": "Too vague"},
            {"dimension": "Risco", "score": 8, "justification": "Well mitigated"},
        ]
        fakeResponse = makeFakeResponse(fakeScores)

        with patch("pipeline.llm.anthropic") as mockAnthropic:
            mockAnthropic.Anthropic.return_value.messages.create.return_value = fakeResponse

            # Act
            result = evaluateQuality(
                texts=["WHEN user does something THEN system SHALL react"],
                dimensions=["Ambiguidade", "Risco"],
            )

        # Assert
        lowScores = [r for r in result if r["score"] < 4]
        self.assertEqual(len(lowScores), 1)
        self.assertEqual(lowScores[0]["dimension"], "Ambiguidade")
        self.assertEqual(lowScores[0]["score"], 2)

    def testEvaluateQuality_NoApiKey_ReturnsEmptyList(self):
        # Arrange
        with patch.dict(os.environ, {}, clear=True):
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]

            # Act
            result = evaluateQuality(
                texts=["WHEN user creates item THEN system SHALL persist it"],
                dimensions=REQUIRED_DIMENSIONS,
            )

        # Assert
        self.assertEqual(result, [])

    def testEvaluateQuality_LlmError_ReturnsEmptyList(self):
        # Arrange
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("pipeline.llm.anthropic") as mockAnthropic:
                mockAnthropic.Anthropic.return_value.messages.create.side_effect = Exception("API error")

                # Act
                result = evaluateQuality(
                    texts=["WHEN user creates item THEN system SHALL persist it"],
                    dimensions=REQUIRED_DIMENSIONS,
                )

        # Assert
        self.assertEqual(result, [])


class EarsScoreCommandTest(TestCase):

    def _setupTask(self):
        db.ensureProject("proj")
        taskId = db.createTask("proj", "Test task")
        earsId = db.addEars(taskId, "event", "WHEN user does X THEN system SHALL do Y")
        db.approveEars(taskId, earsId)
        return taskId, earsId

    def _makeFakeScores(self):
        from pipeline.cli import _SCORE_DIMENSIONS
        return [{"dimension": d, "score": 8, "justification": "ok"} for d in _SCORE_DIMENSIONS]

    def _makeFakeResponse(self, scores):
        import json
        content = json.dumps({"dimensions": scores})
        msg = MagicMock()
        msg.content = [MagicMock(text=content)]
        return msg

    def testEarsScore_NoApiKey_PrintsWarningAndSkips(self):
        # Arrange / Act
        with useTempDb():
            db.initDb()
            taskId, _ = self._setupTask()
            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("ANTHROPIC_API_KEY", None)
                from click.testing import CliRunner
                from pipeline.cli import cli
                runner = CliRunner()
                result = runner.invoke(cli, ["ears", "score", taskId])

        # Assert
        self.assertEqual(result.exit_code, 0)
        self.assertIn("AVISO", result.output)
        self.assertIn("ANTHROPIC_API_KEY", result.output)

    def testEarsScore_EvaluateQualityFails_PrintsWarningAndAborts(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId, _ = self._setupTask()
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                with patch("pipeline.cli.evaluateQuality", return_value=[]):
                    from click.testing import CliRunner
                    from pipeline.cli import cli
                    runner = CliRunner()

                    # Act
                    result = runner.invoke(cli, ["ears", "score", taskId])

        # Assert
        self.assertEqual(result.exit_code, 0)
        self.assertIn("AVISO", result.output)
        scores = db.getEarsQualityScores(taskId)
        self.assertEqual(scores, [])

    def testEarsScore_Success_PersistsIndividualAndAggregateScores(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId, earsId = self._setupTask()
            fakeScores = self._makeFakeScores()
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                with patch("pipeline.cli.evaluateQuality", return_value=fakeScores):
                    from click.testing import CliRunner
                    from pipeline.cli import cli
                    runner = CliRunner()

                    # Act
                    result = runner.invoke(cli, ["ears", "score", taskId])

            # Assert
            self.assertEqual(result.exit_code, 0)
            individual = db.getEarsQualityScores(taskId, earsId=earsId, scope="individual")
            aggregate = db.getEarsQualityScores(taskId, scope="aggregate")
            self.assertGreater(len(individual), 0)
            self.assertGreater(len(aggregate), 0)

    def testEarsScore_LowScore_FlaggedInOutput(self):
        # Arrange
        with useTempDb():
            db.initDb()
            taskId, _ = self._setupTask()
            lowScores = [{"dimension": "Ambiguidade", "score": 2, "justification": "vague"}]
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                with patch("pipeline.cli.evaluateQuality", side_effect=[lowScores, lowScores]):
                    from click.testing import CliRunner
                    from pipeline.cli import cli
                    runner = CliRunner()

                    # Act
                    result = runner.invoke(cli, ["ears", "score", taskId])

        # Assert
        self.assertIn("LOW SCORE", result.output)
