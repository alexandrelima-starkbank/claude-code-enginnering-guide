import os
from pathlib import Path
from threading import local
from datetime import datetime
from sqlite3 import connect, Row

DB_PATH = Path.home() / ".claude" / "pipeline" / "pipeline.db"

_threadLocal = local()

PHASES = ["requirements", "spec", "plan", "tests", "implementation", "mutation", "static-analysis", "done"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT,
    createdAt TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    projectId TEXT NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL,
    description TEXT,
    type TEXT DEFAULT 'feature',
    status TEXT DEFAULT 'pendente',
    phase TEXT DEFAULT 'requirements',
    createdAt TEXT DEFAULT (datetime('now')),
    updatedAt TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS phaseTransitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    fromPhase TEXT,
    toPhase TEXT NOT NULL,
    reason TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS earsRequirements (
    id TEXT NOT NULL,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    pattern TEXT NOT NULL,
    text TEXT NOT NULL,
    approved INTEGER DEFAULT 0,
    approvedAt TEXT,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (taskId, id)
);

CREATE TABLE IF NOT EXISTS acceptanceCriteria (
    id TEXT NOT NULL,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    earsId TEXT NOT NULL,
    scenarioName TEXT NOT NULL,
    givenText TEXT,
    whenText TEXT,
    thenText TEXT NOT NULL,
    testMethod TEXT,
    testQuality TEXT,
    reviewedAt TEXT,
    approved INTEGER DEFAULT 0,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (taskId, id)
);

CREATE TABLE IF NOT EXISTS testResults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    testMethod TEXT NOT NULL,
    passed INTEGER NOT NULL,
    runAt TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mutationResults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    totalMutants INTEGER NOT NULL,
    killed INTEGER NOT NULL,
    score REAL NOT NULL,
    runAt TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS incidents (
    taskId TEXT PRIMARY KEY REFERENCES tasks(id),
    severity TEXT NOT NULL,
    level TEXT NOT NULL,
    currentBehavior TEXT,
    expectedBehavior TEXT,
    rootCause TEXT,
    rootCauseConfidence TEXT
);

CREATE TABLE IF NOT EXISTS planArtifacts (
    id TEXT NOT NULL,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    description TEXT,
    approved INTEGER DEFAULT 0,
    approvedAt TEXT,
    createdAt TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (taskId, id)
);

CREATE TABLE IF NOT EXISTS planScope (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    planId TEXT NOT NULL,
    filePath TEXT NOT NULL,
    action TEXT NOT NULL,
    components TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS planQualityScores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    planId TEXT NOT NULL,
    dimension TEXT NOT NULL,
    score INTEGER NOT NULL,
    justification TEXT
);

CREATE TABLE IF NOT EXISTS staticAnalysisResults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    tool TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    threshold REAL NOT NULL,
    passed INTEGER NOT NULL,
    detailsJson TEXT NOT NULL DEFAULT '[]',
    runAt TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisionPoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    pointId TEXT NOT NULL,
    gate TEXT NOT NULL,
    context TEXT NOT NULL,
    optionsJson TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    choice TEXT,
    rationale TEXT,
    createdAt TEXT DEFAULT (datetime('now')),
    resolvedAt TEXT
);

CREATE TABLE IF NOT EXISTS earsQualityScores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taskId TEXT NOT NULL REFERENCES tasks(id),
    earsId TEXT,
    scope TEXT NOT NULL DEFAULT 'individual',
    dimension TEXT NOT NULL,
    score INTEGER NOT NULL,
    justification TEXT,
    createdAt TEXT DEFAULT (datetime('now'))
);
"""

def getConn():
    conn = getattr(_threadLocal, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except Exception:
            conn = None
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(str(DB_PATH))
    conn.row_factory = Row
    conn.execute("PRAGMA foreign_keys = ON")
    _threadLocal.conn = conn
    return conn


def closeConn():
    conn = getattr(_threadLocal, "conn", None)
    if conn is not None:
        conn.close()
        _threadLocal.conn = None

def initDb():
    with getConn() as conn:
        conn.executescript(SCHEMA)
        # Migrations para bancos existentes
        for migration in (
            "ALTER TABLE acceptanceCriteria ADD COLUMN testQuality TEXT",
            "ALTER TABLE acceptanceCriteria ADD COLUMN reviewedAt TEXT",
        ):
            try:
                conn.execute(migration)
            except Exception:
                pass  # Coluna já existe

# --- Projects ---

def ensureProject(name, path=None):
    projectId = name.lower().replace(" ", "-").replace("/", "-")
    with getConn() as conn:
        existing = conn.execute("SELECT id FROM projects WHERE id = ?", (projectId,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO projects (id, name, path) VALUES (?, ?, ?)",
                (projectId, name, path),
            )
    return projectId

def detectProject():
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            projectPath = result.stdout.strip()
            projectName = Path(projectPath).name
            return ensureProject(projectName, projectPath)
    except Exception:
        pass
    projectName = Path(".").resolve().name
    return ensureProject(projectName, str(Path(".").resolve()))

def listProjects():
    with getConn() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM projects ORDER BY name").fetchall()]

# --- Tasks ---

def nextTaskId():
    with getConn() as conn:
        row = conn.execute(
            "SELECT id FROM tasks ORDER BY CAST(SUBSTR(id, 2) AS INTEGER) DESC LIMIT 1"
        ).fetchone()
        if not row:
            return "T1"
        return "T{0}".format(int(row["id"][1:]) + 1)

def createTask(projectId, title, description=None, taskType="feature"):
    taskId = nextTaskId()
    with getConn() as conn:
        conn.execute(
            "INSERT INTO tasks (id, projectId, title, description, type) VALUES (?, ?, ?, ?, ?)",
            (taskId, projectId, title, description, taskType),
        )
        conn.execute(
            "INSERT INTO phaseTransitions (taskId, fromPhase, toPhase, reason) VALUES (?, NULL, 'requirements', 'task created')",
            (taskId,),
        )
    return taskId

def getTask(taskId):
    with getConn() as conn:
        row = conn.execute(
            "SELECT t.*, p.name as projectName FROM tasks t JOIN projects p ON t.projectId = p.id WHERE t.id = ?",
            (taskId,),
        ).fetchone()
        return dict(row) if row else None

def listTasks(projectId=None, status=None, phase=None):
    query = "SELECT t.*, p.name as projectName FROM tasks t JOIN projects p ON t.projectId = p.id WHERE 1=1"
    params = []
    if projectId:
        query += " AND t.projectId = ?"
        params.append(projectId)
    if status:
        query += " AND t.status = ?"
        params.append(status)
    if phase:
        query += " AND t.phase = ?"
        params.append(phase)
    query += " ORDER BY CAST(SUBSTR(t.id, 2) AS INTEGER)"
    with getConn() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]

def updateTask(taskId, **kwargs):
    allowed = {"status", "description", "title", "type"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return
    updates["updatedAt"] = datetime.now().isoformat()
    setClauses = ", ".join("{0} = ?".format(k) for k in updates)
    with getConn() as conn:
        conn.execute(
            "UPDATE tasks SET {0} WHERE id = ?".format(setClauses),
            list(updates.values()) + [taskId],
        )

# --- Phase transitions ---

def _checkPhaseGates(task, toPhase):
    taskId = task["id"]
    fromPhase = task["phase"]
    results = []

    if fromPhase == "requirements" and toPhase == "spec":
        ears = listEars(taskId)
        unapproved = [r for r in ears if not r["approved"]]
        passed = not unapproved
        detail = (
            "EARS não aprovados: {0}".format(", ".join(r["id"] for r in unapproved))
            if unapproved
            else "{0} EARS".format(len(ears))
        )
        results.append(("EARS aprovados", passed, detail))
        approvedEars = [r for r in ears if r["approved"]]
        if approvedEars:
            scores = getEarsQualityScores(taskId)
            apiKeyMissing = not os.environ.get("ANTHROPIC_API_KEY")
            passedScores = bool(scores) or apiKeyMissing
            detailScores = (
                "{0} score(s) registrados".format(len(scores))
                if scores
                else "ANTHROPIC_API_KEY não configurada — scoring ignorado"
                if apiKeyMissing
                else "quality scoring não executado — rode 'pipeline ears score {0}'".format(taskId)
            )
            results.append(("Quality scores", passedScores, detailScores))

    if fromPhase == "spec" and toPhase == "plan":
        ears = listEars(taskId)
        criteria = listCriteria(taskId)
        approvedCriteria = [c for c in criteria if c["approved"]]
        earsWithoutCriterion = [
            r for r in ears
            if not any(c["earsId"] == r["id"] for c in approvedCriteria)
        ]
        passedCoverage = not earsWithoutCriterion
        detailCoverage = (
            "EARS sem critério: {0}".format(", ".join(r["id"] for r in earsWithoutCriterion))
            if earsWithoutCriterion
            else "todos os EARS cobertos"
        )
        results.append(("Cobertura", passedCoverage, detailCoverage))
        withoutMethod = [c for c in approvedCriteria if not c.get("testMethod")]
        passedMethod = not withoutMethod
        detailMethod = (
            "critérios sem testMethod: {0}".format(", ".join(c["id"] for c in withoutMethod))
            if withoutMethod
            else "{0} critérios com testMethod".format(len(approvedCriteria))
        )
        results.append(("testMethod", passedMethod, detailMethod))

    if fromPhase == "plan" and toPhase == "tests":
        plan = getPlan(taskId)
        passedPlan = plan is not None and bool(plan["approved"])
        detailPlan = "plan aprovado" if passedPlan else "nenhum plan aprovado encontrado"
        results.append(("Plan aprovado", passedPlan, detailPlan))

    if fromPhase == "tests" and toPhase == "implementation":
        criteria = listCriteria(taskId)
        withMethod = [c for c in criteria if c.get("testMethod")]
        unreviewed = [c for c in withMethod if c.get("testQuality") not in ("ACCEPTABLE", "STRONG")]
        passedQuality = not unreviewed
        detailQuality = (
            "{0} critério(s) sem qualidade ({1})".format(
                len(unreviewed), ", ".join(c["id"] for c in unreviewed),
            )
            if unreviewed
            else "{0} critérios revisados".format(len(withMethod))
        )
        results.append(("qualidade", passedQuality, detailQuality))
        notPassing = [
            c["testMethod"] for c in withMethod
            if getLatestTestResult(taskId, c["testMethod"]) != 1
        ]
        passedTests = not notPassing
        detailTests = (
            "sem resultado passing: {0}".format(", ".join(notPassing))
            if notPassing
            else "{0} testMethods passing".format(len(withMethod))
        )
        results.append(("Testes passando", passedTests, detailTests))

    if fromPhase == "mutation" and toPhase == "static-analysis":
        mutation = getLatestMutation(taskId)
        if mutation is None:
            results.append(("Mutation score", False, "nenhum resultado de mutação registrado"))
        if mutation is not None and mutation["score"] < 100.0:
            results.append(("Mutation score", False, "score {0:.0f}% — exigido 100%".format(mutation["score"])))
        if mutation is not None and mutation["score"] >= 100.0:
            results.append(("Mutation score", True, "100%"))

    if fromPhase == "static-analysis" and toPhase == "done":
        rows = getLatestStaticAnalysis(taskId)
        requiredTools = {"ruff", "bandit", "vulture", "pylint", "radon_cc", "radon_mi"}
        passingTools = {row["tool"] for row in rows if row["passed"]}
        missing = requiredTools - passingTools
        if missing:
            results.append(("Static analysis", False,
                "ferramentas sem run passando: {0}".format(", ".join(sorted(missing)))))
        if not missing:
            results.append(("Static analysis", True, "todas as ferramentas passaram"))

    return results


def checkPhaseGates(taskId, toPhase):
    task = getTask(taskId)
    if not task:
        raise ValueError("Task {0} não encontrada".format(taskId))
    return _checkPhaseGates(task, toPhase)


def advancePhase(taskId, toPhase, reason=None):
    if toPhase not in PHASES:
        raise ValueError("Fase inválida: {0}. Válidas: {1}".format(toPhase, ", ".join(PHASES)))
    task = getTask(taskId)
    if not task:
        raise ValueError("Task {0} não encontrada".format(taskId))
    currentIdx = PHASES.index(task["phase"])
    targetIdx = PHASES.index(toPhase)
    if targetIdx != currentIdx + 1:
        nextPhase = PHASES[currentIdx + 1] if currentIdx + 1 < len(PHASES) else "done"
        raise ValueError(
            "Não é possível avançar de '{0}' para '{1}'. Próxima fase: '{2}'".format(
                task["phase"], toPhase, nextPhase
            )
        )
    gates = _checkPhaseGates(task, toPhase)
    failing = [(name, msg) for name, passed, msg in gates if not passed]
    if failing:
        details = "; ".join("{0}: {1}".format(name, msg) for name, msg in failing)
        raise ValueError("Gate: {0}".format(details))
    with getConn() as conn:
        conn.execute(
            "UPDATE tasks SET phase = ?, updatedAt = datetime('now') WHERE id = ?",
            (toPhase, taskId),
        )
        conn.execute(
            "INSERT INTO phaseTransitions (taskId, fromPhase, toPhase, reason) VALUES (?, ?, ?, ?)",
            (taskId, task["phase"], toPhase, reason),
        )

def getPhaseHistory(taskId):
    with getConn() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM phaseTransitions WHERE taskId = ? ORDER BY timestamp",
            (taskId,),
        ).fetchall()]

# --- EARS Requirements ---

def nextEarsId(taskId):
    with getConn() as conn:
        row = conn.execute(
            "SELECT id FROM earsRequirements WHERE taskId = ? ORDER BY sequence DESC LIMIT 1",
            (taskId,),
        ).fetchone()
        if not row:
            return "R01", 1
        n = int(row["id"][1:])
        return "R{0:02d}".format(n + 1), n + 1

def addEars(taskId, pattern, text):
    reqId, seq = nextEarsId(taskId)
    with getConn() as conn:
        conn.execute(
            "INSERT INTO earsRequirements (id, taskId, pattern, text, sequence) VALUES (?, ?, ?, ?, ?)",
            (reqId, taskId, pattern, text, seq),
        )
    return reqId

def listEars(taskId):
    with getConn() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM earsRequirements WHERE taskId = ? ORDER BY sequence",
            (taskId,),
        ).fetchall()]

def approveEars(taskId, reqId):
    with getConn() as conn:
        conn.execute(
            "UPDATE earsRequirements SET approved = 1, approvedAt = datetime('now') WHERE taskId = ? AND id = ?",
            (taskId, reqId),
        )

def approveAllEars(taskId):
    with getConn() as conn:
        conn.execute(
            "UPDATE earsRequirements SET approved = 1, approvedAt = datetime('now') WHERE taskId = ?",
            (taskId,),
        )

# --- Acceptance Criteria ---

def nextCriterionId(taskId):
    with getConn() as conn:
        row = conn.execute(
            "SELECT id FROM acceptanceCriteria WHERE taskId = ? ORDER BY sequence DESC LIMIT 1",
            (taskId,),
        ).fetchone()
        if not row:
            return "C01", 1
        n = int(row["id"][1:])
        return "C{0:02d}".format(n + 1), n + 1

def addCriterion(taskId, earsId, scenarioName, thenText, givenText=None, whenText=None, testMethod=None):
    cId, seq = nextCriterionId(taskId)
    with getConn() as conn:
        conn.execute(
            "INSERT INTO acceptanceCriteria (id, taskId, earsId, scenarioName, givenText, whenText, thenText, testMethod, sequence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cId, taskId, earsId, scenarioName, givenText, whenText, thenText, testMethod, seq),
        )
    return cId

def listCriteria(taskId):
    with getConn() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM acceptanceCriteria WHERE taskId = ? ORDER BY sequence",
            (taskId,),
        ).fetchall()]

def approveCriterion(taskId, criterionId):
    with getConn() as conn:
        conn.execute(
            "UPDATE acceptanceCriteria SET approved = 1 WHERE taskId = ? AND id = ?",
            (taskId, criterionId),
        )

def approveAllCriteria(taskId):
    with getConn() as conn:
        conn.execute(
            "UPDATE acceptanceCriteria SET approved = 1 WHERE taskId = ?",
            (taskId,),
        )

def setTestQuality(taskId, criterionId, quality):
    with getConn() as conn:
        conn.execute(
            "UPDATE acceptanceCriteria SET testQuality = ?, reviewedAt = datetime('now') WHERE taskId = ? AND id = ?",
            (quality, taskId, criterionId),
        )

# --- Test Results ---

def recordTest(taskId, testMethod, passed):
    with getConn() as conn:
        conn.execute(
            "INSERT INTO testResults (taskId, testMethod, passed) VALUES (?, ?, ?)",
            (taskId, testMethod, 1 if passed else 0),
        )

def getTestSummary(taskId):
    with getConn() as conn:
        rows = conn.execute(
            """
            SELECT testMethod, passed, runAt
            FROM testResults
            WHERE taskId = ? AND id IN (
                SELECT MAX(id) FROM testResults WHERE taskId = ? GROUP BY testMethod
            )
            ORDER BY testMethod
            """,
            (taskId, taskId),
        ).fetchall()
    total = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "methods": [dict(r) for r in rows],
    }

def getLatestTestResult(taskId, testMethod):
    if not testMethod:
        return None
    with getConn() as conn:
        row = conn.execute(
            "SELECT passed FROM testResults WHERE taskId = ? AND testMethod = ? ORDER BY id DESC LIMIT 1",
            (taskId, testMethod),
        ).fetchone()
        return row["passed"] if row else None

# --- Mutation Results ---

def recordMutation(taskId, totalMutants, killed):
    score = (killed / totalMutants * 100) if totalMutants > 0 else 0.0
    with getConn() as conn:
        conn.execute(
            "INSERT INTO mutationResults (taskId, totalMutants, killed, score) VALUES (?, ?, ?, ?)",
            (taskId, totalMutants, killed, score),
        )

def getLatestMutation(taskId):
    with getConn() as conn:
        row = conn.execute(
            "SELECT * FROM mutationResults WHERE taskId = ? ORDER BY id DESC LIMIT 1",
            (taskId,),
        ).fetchone()
        return dict(row) if row else None

# --- Incidents ---

def createIncident(taskId, severity, level, currentBehavior=None, expectedBehavior=None):
    with getConn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO incidents (taskId, severity, level, currentBehavior, expectedBehavior) VALUES (?, ?, ?, ?, ?)",
            (taskId, severity, level, currentBehavior, expectedBehavior),
        )

def updateIncident(taskId, **kwargs):
    allowed = {"rootCause", "rootCauseConfidence", "currentBehavior", "expectedBehavior"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return
    setClauses = ", ".join("{0} = ?".format(k) for k in updates)
    with getConn() as conn:
        conn.execute(
            "UPDATE incidents SET {0} WHERE taskId = ?".format(setClauses),
            list(updates.values()) + [taskId],
        )

# --- Plan Artifacts ---

import json as _json


def nextPlanId(taskId):
    with getConn() as conn:
        row = conn.execute(
            "SELECT id FROM planArtifacts WHERE taskId = ? ORDER BY id DESC LIMIT 1",
            (taskId,),
        ).fetchone()
        if not row:
            return "P01"
        n = int(row["id"][1:])
        return "P{0:02d}".format(n + 1)


def createPlan(taskId, description=None):
    planId = nextPlanId(taskId)
    with getConn() as conn:
        conn.execute(
            "INSERT INTO planArtifacts (id, taskId, description) VALUES (?, ?, ?)",
            (planId, taskId, description),
        )
    return planId


def approvePlan(taskId, planId):
    with getConn() as conn:
        conn.execute(
            "UPDATE planArtifacts SET approved = 1, approvedAt = datetime('now') WHERE taskId = ? AND id = ?",
            (taskId, planId),
        )


def getPlan(taskId):
    with getConn() as conn:
        row = conn.execute(
            "SELECT * FROM planArtifacts WHERE taskId = ? ORDER BY id DESC LIMIT 1",
            (taskId,),
        ).fetchone()
        return dict(row) if row else None


def addPlanFile(taskId, planId, filePath, action, components):
    with getConn() as conn:
        conn.execute(
            "INSERT INTO planScope (taskId, planId, filePath, action, components) VALUES (?, ?, ?, ?, ?)",
            (taskId, planId, filePath, action, _json.dumps(components)),
        )


def getPlanScope(taskId, planId):
    with getConn() as conn:
        rows = conn.execute(
            "SELECT * FROM planScope WHERE taskId = ? AND planId = ? ORDER BY id",
            (taskId, planId),
        ).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        entry["components"] = _json.loads(entry["components"])
        result.append(entry)
    return result


def addPlanQualityScore(taskId, planId, dimension, score, justification=None):
    with getConn() as conn:
        conn.execute(
            "INSERT INTO planQualityScores (taskId, planId, dimension, score, justification) VALUES (?, ?, ?, ?, ?)",
            (taskId, planId, dimension, score, justification),
        )


def getPlanQualityScores(taskId, planId):
    with getConn() as conn:
        rows = conn.execute(
            "SELECT * FROM planQualityScores WHERE taskId = ? AND planId = ? ORDER BY id",
            (taskId, planId),
        ).fetchall()
        return [dict(row) for row in rows]


def getLowQualityScores(taskId, planId, threshold=4):
    with getConn() as conn:
        rows = conn.execute(
            "SELECT * FROM planQualityScores WHERE taskId = ? AND planId = ? AND score < ? ORDER BY id",
            (taskId, planId, threshold),
        ).fetchall()
        return [dict(row) for row in rows]


def compareScopeVsImplemented(taskId, planId, implementedComponents):
    scope = getPlanScope(taskId, planId)
    plannedComponents = []
    for entry in scope:
        plannedComponents.extend(entry["components"])
    implementedSet = set(implementedComponents)
    plannedSet = set(plannedComponents)
    return {
        "missingFromImpl": sorted(plannedSet - implementedSet),
        "notInPlan": sorted(implementedSet - plannedSet),
    }


def addEarsQualityScores(taskId, scores, earsId=None, scope="individual"):
    conn = getConn()
    for entry in scores:
        conn.execute(
            "INSERT INTO earsQualityScores (taskId, earsId, scope, dimension, score, justification) VALUES (?, ?, ?, ?, ?, ?)",
            (taskId, earsId, scope, entry["dimension"], entry["score"], entry.get("justification", "")),
        )
    conn.commit()


def getEarsQualityScores(taskId, earsId=None, scope=None):
    conn = getConn()
    query = "SELECT * FROM earsQualityScores WHERE taskId = ?"
    params = [taskId]
    if earsId is not None:
        query += " AND earsId = ?"
        params.append(earsId)
    if scope is not None:
        query += " AND scope = ?"
        params.append(scope)
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# --- Static Analysis Results ---


def addStaticAnalysisResult(taskId, tool, metric, value, threshold, passed, details):
    with getConn() as conn:
        conn.execute(
            "INSERT INTO staticAnalysisResults (taskId, tool, metric, value, threshold, passed, detailsJson) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (taskId, tool, metric, float(value), float(threshold), 1 if passed else 0,
             _json.dumps(details, ensure_ascii=False)),
        )


def getStaticAnalysisResults(taskId):
    with getConn() as conn:
        rows = conn.execute(
            "SELECT * FROM staticAnalysisResults WHERE taskId = ? ORDER BY id",
            (taskId,),
        ).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        entry["details"] = _json.loads(entry["detailsJson"])
        result.append(entry)
    return result


def getLatestStaticAnalysis(taskId):
    with getConn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM staticAnalysisResults
            WHERE taskId = ? AND id IN (
                SELECT MAX(id) FROM staticAnalysisResults
                WHERE taskId = ? GROUP BY tool
            )
            ORDER BY tool
            """,
            (taskId, taskId),
        ).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        entry["details"] = _json.loads(entry["detailsJson"])
        result.append(entry)
    return result


# --- Decision Points ---


def nextDecisionPointId(taskId):
    with getConn() as conn:
        row = conn.execute(
            "SELECT pointId FROM decisionPoints WHERE taskId = ? ORDER BY id DESC LIMIT 1",
            (taskId,),
        ).fetchone()
        if not row:
            return "D01"
        n = int(row["pointId"][1:])
        return "D{0:02d}".format(n + 1)


def addDecisionPoint(taskId, gate, context, options):
    pointId = nextDecisionPointId(taskId)
    with getConn() as conn:
        conn.execute(
            "INSERT INTO decisionPoints (taskId, pointId, gate, context, optionsJson) VALUES (?, ?, ?, ?, ?)",
            (taskId, pointId, gate, context, _json.dumps(options, ensure_ascii=False)),
        )
    return pointId


def getDecisionPoint(taskId, pointId):
    with getConn() as conn:
        row = conn.execute(
            "SELECT * FROM decisionPoints WHERE taskId = ? AND pointId = ?",
            (taskId, pointId),
        ).fetchone()
        if not row:
            return None
        entry = dict(row)
        entry["options"] = _json.loads(entry["optionsJson"])
        return entry


def getPendingDecisions(taskId, gate=None):
    query = "SELECT * FROM decisionPoints WHERE taskId = ? AND status = 'pending'"
    params = [taskId]
    if gate is not None:
        query += " AND gate = ?"
        params.append(gate)
    query += " ORDER BY id"
    with getConn() as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        entry["options"] = _json.loads(entry["optionsJson"])
        result.append(entry)
    return result


def listDecisionPoints(taskId):
    with getConn() as conn:
        rows = conn.execute(
            "SELECT * FROM decisionPoints WHERE taskId = ? ORDER BY id",
            (taskId,),
        ).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        entry["options"] = _json.loads(entry["optionsJson"])
        result.append(entry)
    return result


def resolveDecisionPoint(taskId, pointId, choice, rationale):
    with getConn() as conn:
        conn.execute(
            "UPDATE decisionPoints SET status = 'resolved', choice = ?, rationale = ?, resolvedAt = datetime('now') WHERE taskId = ? AND pointId = ?",
            (choice, rationale, taskId, pointId),
        )


# --- Audit ---

def getTaskAudit(taskId):
    task = getTask(taskId)
    if not task:
        return None
    ears = listEars(taskId)
    criteria = listCriteria(taskId)
    testSummary = getTestSummary(taskId)
    mutation = getLatestMutation(taskId)
    phaseHistory = getPhaseHistory(taskId)

    earsApproved = len(ears) > 0 and all(r["approved"] for r in ears)
    criteriaApproved = len(criteria) > 0 and all(c["approved"] for c in criteria)
    traceabilityOk = len(ears) > 0 and len(criteria) > 0 and all(
        any(c["earsId"] == r["id"] for c in criteria)
        for r in ears
    )
    testsOk = testSummary["total"] > 0 and testSummary["failed"] == 0

    # Gate de qualidade: cada critério com testMethod deve ter qualidade ACCEPTABLE ou STRONG
    withMethod = [c for c in criteria if c.get("testMethod")]
    testQualityOk = len(withMethod) > 0 and all(
        c.get("testQuality") in ("ACCEPTABLE", "STRONG") for c in withMethod
    )
    qualityStrong = sum(1 for c in withMethod if c.get("testQuality") == "STRONG")
    qualityAcceptable = sum(1 for c in withMethod if c.get("testQuality") == "ACCEPTABLE")
    qualityWeak = sum(1 for c in withMethod if c.get("testQuality") == "WEAK")
    qualityNone = sum(1 for c in withMethod if not c.get("testQuality"))

    mutationOk = mutation is not None and mutation["score"] >= 100.0

    gates = {
        "requirements": {
            "pass": earsApproved,
            "detail": "{0} EARS, {1} aprovados".format(
                len(ears), sum(1 for r in ears if r["approved"])
            ),
        },
        "spec": {
            "pass": criteriaApproved,
            "detail": "{0} cenários, {1} aprovados".format(
                len(criteria), sum(1 for c in criteria if c["approved"])
            ),
        },
        "traceability": {
            "pass": traceabilityOk,
            "detail": "cada EARS tem ≥1 cenário" if traceabilityOk else "EARS sem cenário detectado",
        },
        "tests": {
            "pass": testsOk,
            "detail": "{0} testes — {1} passando, {2} falhando".format(
                testSummary["total"], testSummary["passed"], testSummary["failed"]
            ),
        },
        "testQuality": {
            "pass": testQualityOk,
            "detail": "{0} revisados — {1} STRONG, {2} ACCEPTABLE, {3} WEAK, {4} sem revisão".format(
                len(withMethod), qualityStrong, qualityAcceptable, qualityWeak, qualityNone,
            ) if withMethod else "nenhum critério com testMethod",
        },
        "mutation": {
            "pass": mutationOk,
            "detail": "{0:.0f}% ({1}/{2})".format(
                mutation["score"] if mutation else 0,
                mutation["killed"] if mutation else "—",
                mutation["totalMutants"] if mutation else "—",
            ),
        },
    }

    return {
        "task": task,
        "gates": gates,
        "ears": ears,
        "criteria": criteria,
        "testSummary": testSummary,
        "mutation": mutation,
        "phaseHistory": phaseHistory,
    }
