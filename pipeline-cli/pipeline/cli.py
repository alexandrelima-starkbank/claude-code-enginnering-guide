import os
import sys
from json import dumps
from pathlib import Path
import click

_origParseDecls = click.core.Argument._parse_decls
def _patchedParseDecls(self, *args):
    name, opts, secondary = _origParseDecls(self, *args)
    decls = args[0]
    if name and len(decls) == 1:
        name = decls[0].replace("-", "_")
    return name, opts, secondary
click.core.Argument._parse_decls = _patchedParseDecls

from .db import (
    initDb, detectProject, ensureProject, listProjects,
    createTask, getTask, listTasks, updateTask,
    advancePhase, checkPhaseGates, getPhaseHistory, PHASES,
    addEars, listEars, approveEars, approveAllEars,
    addEarsQualityScores, getEarsQualityScores,
    addCriterion, listCriteria, approveCriterion, approveAllCriteria,
    setTestQuality,
    recordTest, getTestSummary,
    recordMutation, getLatestMutation,
    createIncident, updateIncident,
    getTaskAudit,
)
from .export import generateTasksMd, formatTask
from . import vector
from .indexer import indexDirectory, generateContextSection, indexFile, indexProject
from .llm import evaluateQuality


def autoRegenTasksMd():
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return
        gitRoot = result.stdout.strip()
        tasksPath = Path(gitRoot) / "TASKS.md"
        if not tasksPath.exists():
            return
        projectName = Path(gitRoot).name
        projectId = ensureProject(projectName, gitRoot)
        content = generateTasksMd(projectId=projectId)
        tasksPath.write_text(content, encoding="utf-8")
    except Exception:
        pass


@click.group()
def cli():
    initDb()


# ─── PROJECT ──────────────────────────────────────────────────────────────────

@cli.group()
def project():
    pass


@project.command("list")
def projectList():
    for p in listProjects():
        click.echo("{0:<20} {1}".format(p["id"], p.get("path") or ""))


# ─── TASK ─────────────────────────────────────────────────────────────────────

@cli.group()
def task():
    pass


@task.command("create")
@click.option("--project", "projectName", default=None, help="Nome do projeto. Detecta via git se omitido.")
@click.option("--title", required=True, help="Título da tarefa.")
@click.option("--description", default=None)
@click.option("--type", "taskType", default="feature", type=click.Choice(["feature", "bug", "incident", "refactor"]))
def taskCreate(projectName, title, description, taskType):
    projectId = ensureProject(projectName) if projectName else detectProject()
    taskId = createTask(projectId, title, description, taskType)
    click.echo(taskId)
    autoRegenTasksMd()


@task.command("list")
@click.option("--project", "projectName", default=None)
@click.option("--status", default=None)
@click.option("--phase", default=None)
@click.option("--format", "fmt", default="table", type=click.Choice(["table", "json", "context"]))
def taskList(projectName, status, phase, fmt):
    projectId = ensureProject(projectName) if projectName else None
    tasks = listTasks(projectId=projectId, status=status, phase=phase)
    if fmt == "json":
        click.echo(dumps(tasks, ensure_ascii=False, indent=2))
        return
    if fmt == "context":
        for t in tasks:
            click.echo("[{0}] {1} | fase: {2} | status: {3} | projeto: {4}".format(
                t["id"], t["title"], t["phase"], t["status"],
                t.get("projectName", t["projectId"]),
            ))
        return
    if not tasks:
        click.echo("Nenhuma tarefa.")
        return
    click.echo("{:<6} {:<38} {:<16} {:<16} {}".format("ID", "Título", "Fase", "Status", "Projeto"))
    click.echo("-" * 92)
    for t in tasks:
        click.echo("{:<6} {:<38} {:<16} {:<16} {}".format(
            t["id"], t["title"][:38], t["phase"], t["status"],
            t.get("projectName", t["projectId"]),
        ))


@task.command("show")
@click.argument("taskId")
@click.option("--format", "fmt", default="markdown", type=click.Choice(["markdown", "json"]))
def taskShow(taskId, fmt):
    if fmt == "json":
        t = getTask(taskId)
        if not t:
            click.echo("Task {0} não encontrada.".format(taskId), err=True)
            sys.exit(1)
        click.echo(dumps(t, ensure_ascii=False, indent=2))
        return
    md = formatTask(taskId)
    if not md:
        click.echo("Task {0} não encontrada.".format(taskId), err=True)
        sys.exit(1)
    click.echo(md)


@task.command("update")
@click.argument("taskId")
@click.option("--status", default=None)
@click.option("--description", default=None)
@click.option("--title", default=None)
@click.option("--type", "taskType", default=None, type=click.Choice(["feature", "bug", "incident", "refactor"]))
def taskUpdateCmd(taskId, status, description, title, taskType):
    updateTask(taskId, status=status, description=description, title=title, type=taskType)
    click.echo("{0} atualizado.".format(taskId))
    autoRegenTasksMd()


# ─── PHASE ────────────────────────────────────────────────────────────────────

@cli.group()
def phase():
    pass


@phase.command("advance")
@click.argument("taskId")
@click.option("--to", "toPhase", required=True, type=click.Choice(PHASES))
@click.option("--reason", default=None)
def phaseAdvance(taskId, toPhase, reason):
    try:
        advancePhase(taskId, toPhase, reason)
        click.echo("{0} → fase: {1}".format(taskId, toPhase))
        autoRegenTasksMd()
    except ValueError as e:
        click.echo("ERRO: {0}".format(e), err=True)
        sys.exit(1)


@phase.command("check")
@click.argument("taskId")
@click.option("--to", "toPhase", required=True, type=click.Choice(PHASES))
def phaseCheck(taskId, toPhase):
    try:
        gates = checkPhaseGates(taskId, toPhase)
    except ValueError as e:
        click.echo("ERRO: {0}".format(e), err=True)
        sys.exit(1)
    anyFail = False
    for name, passed, detail in gates:
        icon = "PASS" if passed else "FAIL"
        click.echo("[{0}] {1}: {2}".format(icon, name, detail))
        if not passed:
            anyFail = True
    if anyFail:
        sys.exit(1)


@phase.command("history")
@click.argument("taskId")
def phaseHistoryCmd(taskId):
    rows = getPhaseHistory(taskId)
    if not rows:
        click.echo("Sem histórico de fases para {0}.".format(taskId))
        return
    for row in rows:
        fromPhase = row.get("fromPhase") or "—"
        reason = "  ({0})".format(row["reason"]) if row.get("reason") else ""
        click.echo("{0}  {1} → {2}{3}".format(row["timestamp"], fromPhase, row["toPhase"], reason))


# ─── EARS ─────────────────────────────────────────────────────────────────────

@cli.group()
def ears():
    pass


@ears.command("add")
@click.argument("taskId")
@click.option("--pattern", required=True,
              type=click.Choice(["ubiquitous", "event", "state", "unwanted", "optional"]))
@click.option("--text", required=True)
def earsAdd(taskId, pattern, text):
    reqId = addEars(taskId, pattern, text)
    t = getTask(taskId)
    if t:
        vector.addRequirement(taskId, reqId, text, t["projectId"])
    click.echo(reqId)
    autoRegenTasksMd()


@ears.command("list")
@click.argument("taskId")
@click.option("--format", "fmt", default="table", type=click.Choice(["table", "json"]))
def earsList(taskId, fmt):
    reqs = listEars(taskId)
    if fmt == "json":
        click.echo(dumps(reqs, ensure_ascii=False, indent=2))
        return
    if not reqs:
        click.echo("Nenhum requisito EARS para {0}.".format(taskId))
        return
    for r in reqs:
        approved = "✓" if r["approved"] else " "
        click.echo("[{0}][{1}] ({2}) {3}".format(r["id"], approved, r["pattern"], r["text"]))


@ears.command("approve")
@click.argument("taskId")
@click.argument("reqId", default="all")
def earsApprove(taskId, reqId):
    if reqId == "all":
        approveAllEars(taskId)
        click.echo("Todos os EARS aprovados para {0}.".format(taskId))
        autoRegenTasksMd()
        return
    approveEars(taskId, reqId)
    click.echo("{0} aprovado.".format(reqId))
    autoRegenTasksMd()


_SCORE_DIMENSIONS = [
    "Ambiguidade",
    "Ausencia de criterios de aceite",
    "Casos de uso bem definidos",
    "Cobertura de criterios de aceite",
    "Conflitos de decisao",
    "Impacto",
    "Risco",
    "Subjetividade",
]


@ears.command("score")
@click.argument("taskId")
def earsScore(taskId):
    apiKey = os.environ.get("ANTHROPIC_API_KEY")
    if not apiKey:
        click.echo("AVISO: ANTHROPIC_API_KEY não configurada — scoring ignorado.")
        return
    reqs = listEars(taskId)
    approved = [r for r in reqs if r["approved"]]
    if not approved:
        click.echo("Nenhum EARS aprovado para {0}.".format(taskId))
        return
    for r in approved:
        scores = evaluateQuality([r["text"]], _SCORE_DIMENSIONS)
        if not scores:
            click.echo("AVISO: falha ao avaliar {0} — scoring abortado.".format(r["id"]))
            return
        addEarsQualityScores(taskId, scores, earsId=r["id"], scope="individual")
        click.echo("\n{0} — Score individual:".format(r["id"]))
        for s in sorted(scores, key=lambda x: x["dimension"]):
            flag = "  ⚠ LOW SCORE" if s["score"] < 4 else ""
            click.echo("  {dim}: {score}/10{flag}  {just}".format(
                dim=s["dimension"],
                score=s["score"],
                flag=flag,
                just=s.get("justification", ""),
            ))
    allTexts = [r["text"] for r in approved]
    aggScores = evaluateQuality(allTexts, _SCORE_DIMENSIONS)
    if not aggScores:
        click.echo("AVISO: falha ao avaliar conjunto — scoring agregado ignorado.")
        return
    addEarsQualityScores(taskId, aggScores, earsId=None, scope="aggregate")
    click.echo("\nScore agregado (todos os EARS):")
    for s in sorted(aggScores, key=lambda x: x["dimension"]):
        flag = "  ⚠ LOW SCORE" if s["score"] < 4 else ""
        click.echo("  {dim}: {score}/10{flag}  {just}".format(
            dim=s["dimension"],
            score=s["score"],
            flag=flag,
            just=s.get("justification", ""),
        ))


# ─── CRITERION ────────────────────────────────────────────────────────────────

@cli.group()
def criterion():
    pass


@criterion.command("add")
@click.argument("taskId")
@click.option("--ears", "earsId", required=True, help="ID do requisito EARS de origem (ex: R01)")
@click.option("--scenario", required=True, help="Nome do cenário")
@click.option("--given", "givenText", default=None)
@click.option("--when", "whenText", default=None)
@click.option("--then", "thenText", required=True)
@click.option("--test", "testMethod", default=None, help="Nome do método de teste")
def criterionAdd(taskId, earsId, scenario, givenText, whenText, thenText, testMethod):
    cId = addCriterion(taskId, earsId, scenario, thenText, givenText, whenText, testMethod)
    click.echo(cId)
    autoRegenTasksMd()


@criterion.command("list")
@click.argument("taskId")
@click.option("--format", "fmt", default="table", type=click.Choice(["table", "json"]))
def criterionList(taskId, fmt):
    criteria = listCriteria(taskId)
    if fmt == "json":
        click.echo(dumps(criteria, ensure_ascii=False, indent=2))
        return
    if not criteria:
        click.echo("Nenhum critério para {0}.".format(taskId))
        return
    for c in criteria:
        approved = "✓" if c["approved"] else " "
        click.echo("[{0}][{1}] ← {2} | {3} → `{4}`".format(
            c["id"], approved, c["earsId"], c["scenarioName"], c.get("testMethod") or "?"
        ))


@criterion.command("set-quality")
@click.argument("taskId")
@click.argument("criterionId")
@click.argument("quality", type=click.Choice(["WEAK", "ACCEPTABLE", "STRONG"]))
def criterionSetQuality(taskId, criterionId, quality):
    setTestQuality(taskId, criterionId, quality)
    click.echo("{0} qualidade: {1}".format(criterionId, quality))
    autoRegenTasksMd()


@criterion.command("approve")
@click.argument("taskId")
@click.argument("criterionId", default="all")
def criterionApprove(taskId, criterionId):
    if criterionId == "all":
        approveAllCriteria(taskId)
        click.echo("Todos os critérios aprovados para {0}.".format(taskId))
        autoRegenTasksMd()
        return
    approveCriterion(taskId, criterionId)
    click.echo("{0} aprovado.".format(criterionId))
    autoRegenTasksMd()


# ─── TEST ─────────────────────────────────────────────────────────────────────

@cli.group()
def test():
    pass


@test.command("record")
@click.argument("taskId")
@click.option("--method", required=True, help="Nome do método de teste")
@click.option("--passed/--failed", default=True)
def testRecord(taskId, method, passed):
    recordTest(taskId, method, passed)
    click.echo("{0} → {1}".format(method, "✓ passou" if passed else "✗ falhou"))
    autoRegenTasksMd()


@test.command("summary")
@click.argument("taskId")
def testSummaryCmd(taskId):
    summary = getTestSummary(taskId)
    click.echo("Total: {0}  Passou: {1}  Falhou: {2}".format(
        summary["total"], summary["passed"], summary["failed"]
    ))
    for m in summary["methods"]:
        icon = "✓" if m["passed"] else "✗"
        click.echo("  [{0}] {1}".format(icon, m["testMethod"]))


# ─── MUTATION ─────────────────────────────────────────────────────────────────

@cli.group()
def mutation():
    pass


@mutation.command("record")
@click.argument("taskId")
@click.option("--total", "totalMutants", required=True, type=int)
@click.option("--killed", required=True, type=int)
def mutationRecord(taskId, totalMutants, killed):
    recordMutation(taskId, totalMutants, killed)
    score = (killed / totalMutants * 100) if totalMutants > 0 else 0.0
    click.echo("{0:.0f}% ({1}/{2} mutantes mortos)".format(score, killed, totalMutants))
    autoRegenTasksMd()


# ─── INCIDENT ─────────────────────────────────────────────────────────────────

@cli.group()
def incident():
    pass


@incident.command("create")
@click.argument("taskId")
@click.option("--severity", required=True, type=click.Choice(["crítico", "alto", "médio", "baixo"]))
@click.option("--level", required=True, type=click.Choice(["N3", "N4"]))
@click.option("--current", "currentBehavior", default=None)
@click.option("--expected", "expectedBehavior", default=None)
def incidentCreate(taskId, severity, level, currentBehavior, expectedBehavior):
    createIncident(taskId, severity, level, currentBehavior, expectedBehavior)
    click.echo("Incidente registrado para {0}.".format(taskId))


@incident.command("update")
@click.argument("taskId")
@click.option("--root-cause", "rootCause", default=None)
@click.option("--confidence", "rootCauseConfidence", default=None,
              type=click.Choice(["alta", "média", "baixa"]))
def incidentUpdate(taskId, rootCause, rootCauseConfidence):
    updateIncident(taskId, rootCause=rootCause, rootCauseConfidence=rootCauseConfidence)
    click.echo("{0} atualizado.".format(taskId))


# ─── AUDIT ────────────────────────────────────────────────────────────────────

@cli.command("audit")
@click.argument("taskId", default=None, required=False)
@click.option("--project", "projectName", default=None)
def audit(taskId, projectName):
    if taskId:
        _auditOne(taskId)
        return
    projectId = ensureProject(projectName) if projectName else None
    tasks = listTasks(projectId=projectId)
    if not tasks:
        click.echo("Nenhuma tarefa encontrada.")
        return
    click.echo("{:<6} {:<35} {:<16} {:<12} {}".format("ID", "Título", "Fase", "Status", "Gates"))
    click.echo("-" * 88)
    for t in tasks:
        data = getTaskAudit(t["id"])
        if not data:
            continue
        passCount = sum(1 for g in data["gates"].values() if g["pass"])
        total = len(data["gates"])
        gateStr = "{0}/{1} PASS".format(passCount, total)
        ready = "READY ✓" if passCount == total else "NOT READY"
        click.echo("{:<6} {:<35} {:<16} {:<12} {:<12} {}".format(
            t["id"], t["title"][:35], t["phase"], t["status"], gateStr, ready
        ))


def _auditOne(taskId):
    data = getTaskAudit(taskId)
    if not data:
        click.echo("Task {0} não encontrada.".format(taskId), err=True)
        sys.exit(1)

    task = data["task"]
    click.echo("\n=== PIPELINE AUDIT: {0} — {1} ===\n".format(task["id"], task["title"]))
    click.echo("Projeto: {0}   Fase: {1}   Status: {2}".format(
        task.get("projectName", task["projectId"]), task["phase"], task["status"]
    ))
    click.echo("")

    allPass = True
    for gateName, gate in data["gates"].items():
        icon = "PASS ✓" if gate["pass"] else "FAIL ✗"
        click.echo("  {0:<14} {1}   {2}".format(gateName.upper(), icon, gate["detail"]))
        if not gate["pass"]:
            allPass = False

    click.echo("")
    if not allPass:
        click.echo("Resultado: NOT READY ✗")
        click.echo("\nGates pendentes:")
        for gateName, gate in data["gates"].items():
            if not gate["pass"]:
                click.echo("  • {0}: {1}".format(gateName, gate["detail"]))
    if allPass:
        click.echo("Resultado: READY ✓")

    click.echo("\nHistórico de fases:")
    for row in data["phaseHistory"]:
        fromPhase = row.get("fromPhase") or "—"
        reason = " ({0})".format(row["reason"]) if row.get("reason") else ""
        click.echo("  {0}  {1} → {2}{3}".format(row["timestamp"], fromPhase, row["toPhase"], reason))


# ─── CONTEXT ──────────────────────────────────────────────────────────────────

@cli.group()
def context():
    pass


@context.command("add")
@click.option("--text", required=True)
@click.option("--type", "contextType", required=True, type=click.Choice(["decision", "lesson", "context"]))
@click.option("--project", "projectName", default=None)
@click.option("--task", "taskId", default=None)
def contextAdd(text, contextType, projectName, taskId):
    if not vector.isAvailable():
        click.echo("ChromaDB não disponível. Instale: pip install chromadb", err=True)
        sys.exit(1)
    projectId = ensureProject(projectName) if projectName else None
    vector.addContext(text, contextType, projectId, taskId)
    click.echo("Contexto ({0}) adicionado.".format(contextType))


@context.command("search")
@click.argument("query")
@click.option("--project", "projectName", default=None)
@click.option("--type", "contextType", default=None, type=click.Choice(["decision", "lesson", "context"]))
@click.option("--n", default=5, type=int)
def contextSearch(query, projectName, contextType, n):
    if not vector.isAvailable():
        click.echo("ChromaDB não disponível.", err=True)
        sys.exit(1)
    projectId = ensureProject(projectName) if projectName else None

    from . import llm
    expandedQuery = llm.expandQuery(query)
    reqResults = vector.searchRequirements(expandedQuery, projectId=projectId, n=n)
    ctxResults = vector.searchContext(expandedQuery, contextType=contextType, projectId=projectId, n=n)

    if not reqResults and not ctxResults:
        click.echo("Nenhum resultado para: {0}".format(query))
        return

    if reqResults:
        click.echo("\n── Requisitos similares ──")
        for r in reqResults:
            meta = r["metadata"]
            click.echo("  [{0}][{1}:{2}] {3}".format(meta.get("projectId", "?"), meta.get("taskId", "?"), meta.get("reqId", "?"), r["text"][:120]))

    if ctxResults:
        click.echo("\n── Contexto relevante ──")
        for r in ctxResults:
            meta = r["metadata"]
            click.echo("  [{0}][{1}] {2}".format(meta.get("projectId", "?"), meta.get("type", "?"), r["text"][:150]))


# ─── INDEX ────────────────────────────────────────────────────────────────────

@cli.command("index")
@click.argument("directory", default=".")
@click.option("--update-claude-md", "updateClaudeMd", is_flag=True, default=False,
              help="Atualiza a seção Contexto do CLAUDE.md no diretório.")
def indexCmd(directory, updateClaudeMd):
    from pathlib import Path
    if not vector.isAvailable():
        click.echo("ChromaDB não disponível. Instale: pip install chromadb", err=True)
        sys.exit(1)
    results = indexDirectory(directory, verbose=True)
    if not results:
        click.echo("Nenhum projeto encontrado em {0}.".format(directory))
        return
    total = sum(r["codeUnits"] for r in results)
    click.echo("\n{0} projeto(s) — {1} unidades indexadas.".format(len(results), total))
    if updateClaudeMd:
        claudeMdPath = Path(directory) / "CLAUDE.md"
        if claudeMdPath.exists():
            import re
            content = claudeMdPath.read_text(encoding="utf-8")
            section = generateContextSection(results)
            content = re.sub(r'<!--.*?-->', section, content, count=1, flags=re.DOTALL)
            claudeMdPath.write_text(content, encoding="utf-8")
            click.echo("CLAUDE.md atualizado em {0}.".format(directory))


@cli.command("index-file")
@click.argument("filePath")
@click.option("--project", "projectName", default=None)
def indexFileCmd(filePath, projectName):
    from pathlib import Path
    if not vector.isAvailable():
        sys.exit(0)
    path = Path(filePath).resolve()
    if not path.exists() or path.suffix != ".py":
        sys.exit(0)
    import subprocess
    result = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    projectRoot = Path(result.stdout.strip()) if result.returncode == 0 else path.parent
    name = projectName or projectRoot.name
    projectId = ensureProject(name, str(projectRoot))
    n = indexFile(path, projectId, projectRoot=projectRoot, force=True)
    click.echo("Re-indexado: {0} ({1} unidades)".format(path.name, n))


@cli.command("search")
@click.argument("query")
@click.option("--project", "projectName", default=None)
@click.option("--n", default=10, type=int, help="Número de resultados.")
def searchCmd(query, projectName, n):
    if not vector.isAvailable():
        click.echo("ChromaDB não disponível.", err=True)
        sys.exit(1)
    projectId = ensureProject(projectName) if projectName else None
    from . import llm
    expandedQuery = llm.expandQuery(query)
    results = vector.searchCode(expandedQuery, projectId=projectId, n=n)
    if not results:
        click.echo("Nenhum resultado para: {0}".format(query))
        return
    for r in results:
        meta = r["metadata"]
        click.echo("[{0}] {1}:{2}  {3}  [{4}]".format(
            meta.get("projectId", "?"),
            meta.get("file", "?"),
            meta.get("line", "?"),
            meta.get("qualifiedName", "?"),
            meta.get("type", "?"),
        ))
        lines = [l for l in r["document"].splitlines()[1:] if l.strip()]
        if lines:
            click.echo("    {0}".format(lines[0][:100]))


# ─── EXPORT ───────────────────────────────────────────────────────────────────

@cli.group()
def export():
    pass


@export.command("tasks-md")
@click.option("--project", "projectName", default=None)
@click.option("--task", "taskId", default=None)
@click.option("--output", default=None, help="Caminho do arquivo. Padrão: stdout.")
def exportTasksMd(projectName, taskId, output):
    projectId = None if taskId else (ensureProject(projectName) if projectName else detectProject())
    content = generateTasksMd(projectId=projectId, taskId=taskId)
    if output:
        Path(output).write_text(content, encoding="utf-8")
        click.echo("TASKS.md gerado em {0}".format(output))
        return
    click.echo(content)


@export.command("metrics")
@click.option("--project", "projectName", default=None)
def exportMetrics(projectName):
    projectId = ensureProject(projectName) if projectName else None
    tasks = listTasks(projectId=projectId)

    if not tasks:
        click.echo("Nenhuma tarefa encontrada.")
        return

    click.echo("\n=== MÉTRICAS DA PIPELINE ===\n")
    click.echo("Total de tarefas: {0}".format(len(tasks)))

    phaseCount = {ph: 0 for ph in PHASES}
    for t in tasks:
        phaseCount[t["phase"]] = phaseCount.get(t["phase"], 0) + 1

    click.echo("\nDistribuição por fase:")
    for ph, count in phaseCount.items():
        bar = "█" * count
        click.echo("  {0:<16} {1:>3}  {2}".format(ph, count, bar))

    mutations100 = []
    for t in tasks:
        m = getLatestMutation(t["id"])
        if m and m["score"] >= 100.0:
            mutations100.append(t)

    click.echo("\nMutation score 100%: {0}/{1}".format(len(mutations100), len(tasks)))
    for t in mutations100:
        click.echo("  ✓ {0} — {1}".format(t["id"], t["title"]))
