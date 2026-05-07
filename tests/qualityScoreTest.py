import os
import sys
from unittest import TestCase
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline-cli"))

from pipeline.llm import evaluateQuality

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
