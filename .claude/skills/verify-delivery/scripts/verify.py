#!/usr/bin/env python3
"""
Convention Verifier — checks Python files against project conventions.

Usage:
    python3 verify.py file1.py file2.py
    python3 verify.py --git
    python3 verify.py --git-staged
"""
import re
import sys
import subprocess
from pathlib import Path


class Violation:
    def __init__(self, file, line, rule, message):
        self.file = file
        self.line = line
        self.rule = rule
        self.message = message

    def __str__(self):
        return "{file}:{line} [{rule}] {message}".format(
            file=self.file, line=self.line, rule=self.rule, message=self.message,
        )


def checkFstrings(filepath, lines):
    violations = []
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("#"):
            continue
        if re.search(r'\bf["\']', line):
            violations.append(Violation(
                filepath, i, "NO-FSTRING",
                "f-string detected — use .format() instead",
            ))
    return violations


def checkElseBlocks(filepath, lines):
    violations = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not (stripped == "else:" or stripped.startswith("else:")):
            continue
        isAllowed = False
        for j in range(i - 2, max(0, i - 20), -1):
            prev = lines[j].strip()
            if prev.startswith("except") or prev.startswith("try:"):
                isAllowed = True
                break
            if prev.startswith("def ") or prev.startswith("class "):
                break
        if not isAllowed:
            for j in range(i - 2, max(0, i - 30), -1):
                prev = lines[j].strip()
                if prev.startswith("for ") or prev.startswith("while "):
                    indentFor = len(lines[j]) - len(lines[j].lstrip())
                    indentElse = len(line) - len(line.lstrip())
                    if indentFor == indentElse:
                        isAllowed = True
                        break
                if prev.startswith("def ") or prev.startswith("class "):
                    break
        if not isAllowed:
            violations.append(Violation(
                filepath, i, "NO-ELSE",
                "else block detected — use early return pattern",
            ))
    return violations


def checkNamingConventions(filepath, lines):
    violations = []
    for i, line in enumerate(lines, 1):
        match = re.match(r"^\s*def\s+([a-z][a-z0-9_]*[a-z0-9])\s*\(", line)
        if not match:
            continue
        funcName = match.group(1)
        if funcName.startswith("__") and funcName.endswith("__"):
            continue
        if "_" not in funcName:
            continue
        if funcName.startswith("test"):
            continue
        if re.match(r"^_?[a-z]+(_[a-z]+)+$", funcName):
            violations.append(Violation(
                filepath, i, "NAMING",
                "snake_case function '{name}' — use camelCase".format(name=funcName),
            ))
    return violations


def checkTrailingComma(filepath, lines):
    violations = []
    for i, line in enumerate(lines, 1):
        if line.strip() != ")":
            continue
        if i < 2:
            continue
        prev = lines[i - 2].rstrip()
        if not prev:
            continue
        if prev.endswith(",") or prev.endswith("("):
            continue
        if prev.strip().startswith("#") or prev.strip().startswith(")"):
            continue
        if "=" in prev or prev.strip().startswith('"') or prev.strip().startswith("'"):
            violations.append(Violation(
                filepath, i - 1, "TRAILING-COMMA",
                "missing trailing comma on last argument",
            ))
    return violations


def checkForbiddenFiles(filepath):
    violations = []
    name = Path(filepath).name
    forbidden = {"main_local.py", "query_dev.py", "test_local.sh"}
    if name in forbidden:
        violations.append(Violation(
            filepath, 0, "FORBIDDEN-FILE",
            "file should not be committed: {n}".format(n=name),
        ))
    if "/it_tests/" in filepath or "\\it_tests\\" in filepath:
        violations.append(Violation(
            filepath, 0, "FORBIDDEN-FILE",
            "integration test files should not be committed",
        ))
    return violations


def checkUntracedSymbols(filepath, lines, earsTexts):
    violations = []
    earsCombined = " ".join(earsTexts).lower()
    for line in lines:
        match = re.match(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:(]", line)
        if not match:
            continue
        className = match.group(1)
        if className.lower() in earsCombined:
            continue
        violations.append(Violation(
            filepath, 0, "UNTRACED-SYMBOL",
            "class '{n}' not traceable to any EARS requirement".format(n=className),
        ))
    return violations


def checkDeadAbstractions(filepath, lines, referencedSymbols):
    violations = []
    for line in lines:
        match = re.match(r"^\s*(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:(]", line)
        if not match:
            continue
        name = match.group(1)
        if name.startswith("__") and name.endswith("__"):
            continue
        if name not in referencedSymbols:
            violations.append(Violation(
                filepath, 0, "DEAD-ABSTRACTION",
                "'{n}' defined but not referenced in the codebase".format(n=name),
            ))
    return violations


def getGitFiles(stagedOnly=False):
    cmd = ["git", "diff", "--name-only"]
    if stagedOnly:
        cmd.append("--staged")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return [f for f in result.stdout.strip().split("\n") if f.endswith(".py") and f]
    except subprocess.CalledProcessError:
        return []


def verifyFile(filepath):
    violations = checkForbiddenFiles(filepath)
    try:
        with open(filepath) as f:
            lines = f.read().split("\n")
    except (FileNotFoundError, PermissionError) as e:
        violations.append(Violation(filepath, 0, "READ-ERROR", str(e)))
        return violations
    violations.extend(checkFstrings(filepath, lines))
    violations.extend(checkElseBlocks(filepath, lines))
    violations.extend(checkNamingConventions(filepath, lines))
    violations.extend(checkTrailingComma(filepath, lines))
    return violations


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 verify.py <files...> | --git | --git-staged")
        sys.exit(1)
    files = args
    if args[0] == "--git":
        files = getGitFiles()
    elif args[0] == "--git-staged":
        files = getGitFiles(stagedOnly=True)
    if not files:
        print("No Python files to check.")
        sys.exit(0)
    allViolations = []
    for filepath in files:
        allViolations.extend(verifyFile(filepath))
    if allViolations:
        print("FAIL — {n} violation(s):\n".format(n=len(allViolations)))
        for v in allViolations:
            print("  {v}".format(v=v))
        print("\nFix before proceeding.")
        sys.exit(1)
    print("PASS — {n} file(s) checked, no violations.".format(n=len(files)))
    sys.exit(0)


if __name__ == "__main__":
    main()
