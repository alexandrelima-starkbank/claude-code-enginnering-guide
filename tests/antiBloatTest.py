import os
import sys
from unittest import TestCase

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(PROJECT_ROOT, ".claude", "skills", "verify-delivery", "scripts"))

from verify import checkDeadAbstractions, checkUntracedSymbols


class UntracedSymbolsTest(TestCase):

    def testUntracedSymbols_ClassNotMentionedInEars_Flagged(self):
        # Arrange
        lines = [
            "class ItemHelper:",
            "    def doSomething(self):",
            "        pass",
        ]
        earsTexts = [
            "WHEN user creates item THEN the system SHALL persist it",
        ]

        # Act
        violations = checkUntracedSymbols("handlers/itemHelper.py", lines, earsTexts)

        # Assert
        self.assertEqual(len(violations), 1)
        self.assertIn("ItemHelper", violations[0].message)
        self.assertEqual(violations[0].rule, "UNTRACED-SYMBOL")

    def testUntracedSymbols_ClassMentionedInEars_NotFlagged(self):
        # Arrange
        lines = [
            "class ItemGateway:",
            "    def create(self):",
            "        pass",
        ]
        earsTexts = [
            "WHEN user creates item THEN ItemGateway SHALL persist it to the database",
        ]

        # Act
        violations = checkUntracedSymbols("gateways/itemGateway.py", lines, earsTexts)

        # Assert
        self.assertEqual(violations, [])

    def testUntracedSymbols_MultipleClasses_OnlyUntracedFlagged(self):
        # Arrange
        lines = [
            "class ItemGateway:",
            "    pass",
            "",
            "class HelperUtil:",
            "    pass",
        ]
        earsTexts = [
            "WHEN user creates item THEN ItemGateway SHALL persist it",
        ]

        # Act
        violations = checkUntracedSymbols("gateways/itemGateway.py", lines, earsTexts)

        # Assert
        self.assertEqual(len(violations), 1)
        self.assertIn("HelperUtil", violations[0].message)

    def testUntracedSymbols_NoClasses_NoViolations(self):
        # Arrange
        lines = [
            "def parseInput(data):",
            "    return data",
        ]
        earsTexts = ["WHEN user sends data THEN system SHALL parse it"]

        # Act
        violations = checkUntracedSymbols("utils/parser.py", lines, earsTexts)

        # Assert
        self.assertEqual(violations, [])

    def testUntracedSymbols_EmptyEars_AllClassesFlagged(self):
        # Arrange
        lines = [
            "class ItemModel:",
            "    pass",
        ]
        earsTexts = []

        # Act
        violations = checkUntracedSymbols("models/itemModel.py", lines, earsTexts)

        # Assert
        self.assertEqual(len(violations), 1)
        self.assertIn("ItemModel", violations[0].message)


class DeadAbstractionsTest(TestCase):

    def testDeadAbstractions_FunctionNotReferencedAnywhere_Flagged(self):
        # Arrange
        filepath = "utils/orphanUtil.py"
        lines = [
            "def buildOrphanCache(data):",
            "    return {}",
        ]
        referencedSymbols = {"parseInput", "validateItem", "ItemGateway"}

        # Act
        violations = checkDeadAbstractions(filepath, lines, referencedSymbols)

        # Assert
        self.assertEqual(len(violations), 1)
        self.assertIn("buildOrphanCache", violations[0].message)
        self.assertEqual(violations[0].rule, "DEAD-ABSTRACTION")

    def testDeadAbstractions_FunctionReferenced_NotFlagged(self):
        # Arrange
        filepath = "utils/parser.py"
        lines = [
            "def parseInput(data):",
            "    return data",
        ]
        referencedSymbols = {"parseInput", "validateItem"}

        # Act
        violations = checkDeadAbstractions(filepath, lines, referencedSymbols)

        # Assert
        self.assertEqual(violations, [])

    def testDeadAbstractions_ClassNotReferenced_Flagged(self):
        # Arrange
        filepath = "utils/unused.py"
        lines = [
            "class UnusedHelper:",
            "    def doStuff(self):",
            "        pass",
        ]
        referencedSymbols = {"doStuff", "ItemGateway", "ItemHandler"}

        # Act
        violations = checkDeadAbstractions(filepath, lines, referencedSymbols)

        # Assert
        self.assertEqual(len(violations), 1)
        self.assertIn("UnusedHelper", violations[0].message)

    def testDeadAbstractions_DunderMethods_NotFlagged(self):
        # Arrange
        filepath = "models/item.py"
        lines = [
            "class Item:",
            "    def __init__(self):",
            "        pass",
            "    def __str__(self):",
            "        pass",
        ]
        referencedSymbols = {"Item"}

        # Act
        violations = checkDeadAbstractions(filepath, lines, referencedSymbols)

        # Assert
        self.assertEqual(violations, [])

    def testDeadAbstractions_EmptyFile_NoViolations(self):
        # Arrange
        filepath = "utils/empty.py"
        lines = []
        referencedSymbols = set()

        # Act
        violations = checkDeadAbstractions(filepath, lines, referencedSymbols)

        # Assert
        self.assertEqual(violations, [])
