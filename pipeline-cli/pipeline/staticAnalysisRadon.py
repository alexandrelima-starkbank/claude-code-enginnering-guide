import subprocess
import json as _json
from .staticAnalysisRunners import MissingToolError, _result


def _safeJsonLoad(stdout):
    if not stdout:
        return {}
    try:
        return _json.loads(stdout)
    except (ValueError, TypeError):
        return {}


def _radonProc(mode, files):
    return subprocess.run(
        ["radon", mode, "-s", "-j"] + list(files),
        capture_output=True, text=True, timeout=120, check=False,
    )


def _aggregateCc(ccData):
    maxCc = 0
    details = []
    for filePath, blocks in ccData.items():
        for block in blocks if isinstance(blocks, list) else []:
            cc = block.get("complexity", 0)
            maxCc = max(maxCc, cc)
            if cc > 10:
                details.append("{0}:{1} {2} CC={3}".format(
                    filePath, block.get("lineno", "?"),
                    block.get("name", "?"), cc,
                ))
    return maxCc, details


def _aggregateMi(miData):
    minMi = 100
    details = []
    for filePath, info in miData.items():
        mi = info.get("mi", 100) if isinstance(info, dict) else 100
        minMi = min(minMi, mi)
        if mi < 36:
            details.append("{0} MI={1:.2f}".format(filePath, mi))
    return minMi, details


def runRadon(files):
    if not files:
        return [
            _result("radon_cc", 0, 10, True, []),
            _result("radon_mi", 100, 36, True, []),
        ]
    try:
        ccProc = _radonProc("cc", files)
        miProc = _radonProc("mi", files)
    except FileNotFoundError as exc:
        raise MissingToolError("radon ausente — instale via: pip install radon") from exc
    maxCc, ccDetails = _aggregateCc(_safeJsonLoad(ccProc.stdout))
    minMi, miDetails = _aggregateMi(_safeJsonLoad(miProc.stdout))
    return [
        _result("radon_cc", maxCc, 10, maxCc <= 10, ccDetails),
        _result("radon_mi", minMi, 36, minMi >= 36, miDetails),
    ]
