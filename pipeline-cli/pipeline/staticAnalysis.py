import re
import subprocess
from .staticAnalysisRadon import runRadon
from .staticAnalysisRunners import MissingToolError
from .db import addStaticAnalysisResult, getPlan, getPlanScope
from .staticAnalysisRunners import runBandit, runPylint, runRuff, runVulture


THRESHOLDS = {
    "ruff": {"metric": "violation_count", "threshold": 0, "op": "<="},
    "bandit": {"metric": "violation_count", "threshold": 0, "op": "<="},
    "vulture": {"metric": "violation_count", "threshold": 0, "op": "<="},
    "pylint": {"metric": "violation_count", "threshold": 0, "op": "<="},
    "radon_cc": {"metric": "max_cc", "threshold": 10, "op": "<="},
    "radon_mi": {"metric": "min_mi", "threshold": 36, "op": ">="},
}

_TEST_FILE_PATTERNS = (
    re.compile(r".*Test\.py$"),
    re.compile(r".*_test\.py$"),
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"(^|/)tests?/"),
)


def _excludeTestFiles(files):
    return [f for f in files
            if not any(p.search(f) for p in _TEST_FILE_PATTERNS)]


def _filesFromGitDiff(taskId):
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "development...HEAD"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.endswith(".py")]


def _compareWithPlanScope(taskId, files):
    plan = getPlan(taskId)
    if not plan:
        return []
    scope = getPlanScope(taskId, plan["id"])
    plannedSet = {entry["filePath"] for entry in scope}
    diffSet = set(files)
    warnings = []
    for f in sorted(diffSet - plannedSet):
        warnings.append("AVISO: {0} modificado mas fora do planScope".format(f))
    for f in sorted(plannedSet - diffSet):
        warnings.append("AVISO: {0} no planScope mas sem alteração no diff".format(f))
    return warnings


def _persist(taskId, results):
    for r in results:
        addStaticAnalysisResult(
            taskId, r["tool"],
            THRESHOLDS.get(r["tool"], {}).get("metric", "value"),
            r["value"], r["threshold"], r["passed"], r.get("details", []),
        )


def _safeRun(name, runner, files):
    try:
        return runner(files)
    except FileNotFoundError as exc:
        raise MissingToolError(
            "{0} ausente — instale via: pip install {0}".format(name),
        ) from exc


def runAll(taskId, files=None):
    files = files if files is not None else _filesFromGitDiff(taskId)
    if not files:
        return []
    nonTest = _excludeTestFiles(files)
    results = [
        _safeRun("ruff", runRuff, files),
        _safeRun("bandit", runBandit, files),
        _safeRun("vulture", runVulture, nonTest),
        _safeRun("pylint", runPylint, nonTest),
    ]
    results.extend(_safeRun("radon", runRadon, nonTest))
    _persist(taskId, results)
    return results
