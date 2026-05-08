import re
import subprocess


class MissingToolError(Exception):
    pass


_PYLINT_DISABLED = (
    "C0103",
    "C0114",
    "C0115",
    "C0116",
    "C0209",
    "W0613",
)

_VULTURE_IGNORE_DECORATORS = (
    "@*command",
    "@*group",
    "@click.*",
)


def _result(tool, value, threshold, passed, details):
    return {
        "tool": tool, "value": value, "threshold": threshold,
        "passed": passed, "details": details,
    }


def _runProcess(cmd, timeout):
    return subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=timeout, check=False,
    )


def _missing(tool):
    return MissingToolError(
        "{0} ausente — instale via: pip install {0}".format(tool),
    )


def runRuff(files):
    try:
        proc = _runProcess(
            ["ruff", "check", "--output-format=concise"] + list(files), 120,
        )
    except FileNotFoundError as exc:
        raise _missing("ruff") from exc
    details = [line for line in proc.stdout.splitlines() if line.strip()]
    return _result("ruff", len(details), 0, len(details) == 0, details)


def runBandit(files):
    cmd = ["bandit", "-r", "-f", "txt", "-q",
           "--severity-level", "medium",
           "--confidence-level", "medium"]
    try:
        proc = _runProcess(cmd + list(files), 180)
    except FileNotFoundError as exc:
        raise _missing("bandit") from exc
    details = [line for line in proc.stdout.splitlines() if "Issue:" in line]
    return _result("bandit", len(details), 0, len(details) == 0, details)


def _vultureScanRoots(files):
    roots = set()
    for f in files:
        parts = f.split("/")
        roots.add(parts[0] if len(parts) > 1 else ".")
    return sorted(roots) or ["."]


def runVulture(files):
    if not files:
        return _result("vulture", 0, 0, True, [])
    ignore = ",".join(_VULTURE_IGNORE_DECORATORS)
    scanRoots = _vultureScanRoots(files)
    try:
        proc = _runProcess(
            ["vulture", "--ignore-decorators", ignore] + scanRoots, 120,
        )
    except FileNotFoundError as exc:
        raise _missing("vulture") from exc
    relevant = tuple(files)
    details = [line for line in proc.stdout.splitlines()
               if line.strip() and line.startswith(relevant)]
    return _result("vulture", len(details), 0, len(details) == 0, details)


def runPylint(files):
    if not files:
        return _result("pylint", 0, 0, True, [])
    cmd = ["pylint", "--score=n",
           "--disable={0}".format(",".join(_PYLINT_DISABLED))]
    try:
        proc = _runProcess(cmd + list(files), 180)
    except FileNotFoundError as exc:
        raise _missing("pylint") from exc
    pattern = re.compile(r".+:\d+:\d+: [CRWE]\d+:")
    details = [line for line in proc.stdout.splitlines() if pattern.match(line)]
    return _result("pylint", len(details), 0, len(details) == 0, details)
