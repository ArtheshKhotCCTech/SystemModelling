# Purpose: summary.md — the page an engineer reads in under a minute to approve or reject a run:
# what the model understands the system to be, one status line per gate read from its artefact
# (R-REP-4), the counts, the open questions with their defaults and the assumptions (R-REP-1),
# one line per conflict resolved by precedence, and the command that compiles the model. Lists
# are capped so the page stays within MAX_LINES; the rest is in assumptions.md.
from __future__ import annotations

from collections import Counter
from pathlib import Path

from specalive.core.ir import SYSTEM_OWNER, Conflict, SystemModel
from specalive.report.artefacts import INVALID, NOT_RUN, Run, source_label, write_report
from specalive.report.assumptions import UNRESOLVED, winners

REPORT_FILE = "summary.md"
MAX_LINES = 60
MAX_QUESTIONS = 8
MAX_ASSUMPTIONS = 5
MAX_CONFLICTS = 5
_TEXT_WIDTH = 160


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _TEXT_WIDTH else text[:_TEXT_WIDTH - 1].rstrip() + "…"


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {plural or word + 's'}"


def describe(model: SystemModel) -> str:
    """One paragraph: the IR's own description, then what the model is made of."""
    kinds = Counter(p.kind for p in model.parts)
    parts = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
    text = [model.description.strip().rstrip(".") + ".",
            f"The model holds {_plural(len(model.parts), 'part')} ({parts}) joined by "
            f"{_plural(len(model.connections), 'connection')}."]
    for sm in sorted(model.state_machines, key=lambda s: s.id):
        names = ", ".join(s.name for s in sm.states)
        text.append(f"{sm.owner} runs state machine {sm.id} with "
                    f"{_plural(len(sm.states), 'state')} ({names}), starting in "
                    f"{next((s.name for s in sm.states if s.id == sm.initial), sm.initial)}.")
    active = sum(1 for r in model.requirements if r.status == "active")
    criteria = _plural(len(model.acceptance_criteria), "acceptance criterion",
                       "acceptance criteria")
    text.append(f"{_plural(active, 'active requirement')} and {criteria} are traced to it.")
    return " ".join(text)


# --- gates --------------------------------------------------------------------------------

def _ir_gate(run: Run) -> str:
    if run.ir.ok:
        return "PASS"
    return f"FAIL — {run.ir.reason}" if run.ir.state == INVALID else run.ir.not_run


def _tool_gate(artefact, issues: bool = False) -> str:
    if not artefact.ok:
        return artefact.not_run
    data = artefact.data
    line = str(data.get("status", NOT_RUN))
    if issues:
        line += (f" ({_plural(len(data.get('errors') or []), 'error')}, "
                 f"{_plural(len(data.get('warnings') or []), 'warning')})")
    detail = data.get("detail")
    return f"{line} — {_clip(detail)}" if detail and line.split()[0] != "ok" else line


def _tally(items: list[dict], statuses: tuple[str, ...]) -> str:
    counts = Counter(i.get("status") for i in items)
    return " / ".join(f"{counts.get(s, 0)} {s}" for s in statuses)


def gate_lines(run: Run) -> list[str]:
    v = run.verification
    lines = [f"- IR valid: {_ir_gate(run)}",
             f"- SysML valid: {_tool_gate(run.sysml_validation, issues=True)}",
             f"- Modelica compiles: {_tool_gate(run.repair_log)}"]
    if v.ok:
        sim = v.data.get("simulation") or {}
        status = sim.get("status", NOT_RUN)
        detail = "" if status == "ok" else f" — {_clip(str(sim.get('detail', '')))}"
        lines.append(f"- Simulates: {status}{detail}")
        reference = v.data.get("reference") or {}
        if reference.get("status") == "ok":
            lines.append("- Reference trace: " + _tally(v.data.get("signals") or [],
                                                        ("PASS", "FAIL", "NOT COMPARED")))
        else:
            lines.append(f"- Reference trace: {NOT_RUN} — {reference.get('reason')}")
        lines.append("- Acceptance criteria: " + _tally(v.data.get("criteria") or [],
                                                        ("PASS", "FAIL", "NOT CHECKED")))
        lines.append(f"- Verification overall: {v.data.get('status', NOT_RUN)}")
    else:
        lines += [f"- Simulates: {v.not_run}", f"- Reference trace: {v.not_run}",
                  f"- Acceptance criteria: {v.not_run}"]
    c = run.coverage
    if not c.ok:
        lines.append(f"- Coverage: {c.not_run}")
    elif c.data.get("status") != "ok":
        lines.append(f"- Coverage: {NOT_RUN} — {c.data.get('reason')}")
    else:
        cats = [k for k, x in c.data.items() if isinstance(x, dict) and "percent" in x]
        lines.append("- Coverage: " + ", ".join(f"{k} {c.data[k]['percent']:g}%" for k in cats))
    return lines


# --- IR sections --------------------------------------------------------------------------

def _more(total: int, shown: int, what: str) -> list[str]:
    return [f"- … and {total - shown} more {what} in assumptions.md"] if total > shown else []


def conflict_line(model: SystemModel, c: Conflict) -> str:
    """'<part tag> <parameter>: <winner> (<source>) over <loser> (<sources>)'."""
    params = {p.id: p for p in model.parameters}
    parts = {p.id: p for p in model.parts}
    subject = c.subject.element_id
    if subject in params:
        p = params[subject]
        owner = parts.get(p.owner)
        who = owner.tags[0] if owner and owner.tags else p.owner
        subject = p.name if p.owner == SYSTEM_OWNER else f"{who} {p.name}"
    elif c.subject.field != "value":
        subject = f"{subject}.{c.subject.field}"

    def cited(cands) -> str:
        return ", ".join(dict.fromkeys(source_label(model, x.source_id) for x in cands))

    if c.resolution == UNRESOLVED:
        values = dict.fromkeys(x.value for x in c.candidates)
        return f"- {subject}: UNRESOLVED between {' / '.join(values)} — see the open questions"
    losers: dict[str, list] = {}
    for x in sorted(c.candidates, key=lambda x: x.authority_rank):
        if x.value != c.resolution:
            losers.setdefault(x.value, []).append(x)
    over = "; ".join(f"{value} ({cited(cands)})" for value, cands in losers.items())
    return f"- {subject}: {c.resolution} ({cited(winners(c))}) over {over}"


def _ir_sections(model: SystemModel) -> list[str]:
    open_q = sorted((q for q in model.questions if q.answer is None), key=lambda q: q.id)
    states = sum(len(sm.states) for sm in model.state_machines)
    lines = ["", "## Counts", "",
             f"- {_plural(len(model.parts), 'part')}, "
             f"{_plural(len(model.connections), 'connection')}, {_plural(states, 'state')}, "
             f"{_plural(len(model.requirements), 'requirement')}",
             f"- {_plural(len(model.assumptions), 'assumption')}, "
             f"{len(open_q)} open question{'' if len(open_q) == 1 else 's'}, "
             f"{_plural(len(model.conflicts), 'conflict')}",
             "", "## Open questions", ""]
    lines += [f"- `{q.id}`: {_clip(q.text)} — default: "
              f"{q.default_if_unanswered or 'none stated'}" for q in open_q[:MAX_QUESTIONS]]
    lines += _more(len(open_q), MAX_QUESTIONS, "open questions") or ([] if open_q else
                                                                     ["- None."])
    assumptions = sorted(model.assumptions, key=lambda a: a.id)
    lines += ["", "## Assumptions", ""]
    lines += [f"- `{a.id}`: {_clip(a.text)}" for a in assumptions[:MAX_ASSUMPTIONS]]
    lines += _more(len(assumptions), MAX_ASSUMPTIONS, "assumptions") or ([] if assumptions else
                                                                         ["- None."])
    # unresolved conflicts first: they are open, not settled
    conflicts = sorted(model.conflicts, key=lambda c: (c.resolution != UNRESOLVED, c.id))
    lines += ["", "## Conflicts resolved by precedence", ""]
    lines += [conflict_line(model, c) for c in conflicts[:MAX_CONFLICTS]]
    lines += _more(len(conflicts), MAX_CONFLICTS, "conflicts") or ([] if conflicts else
                                                                   ["- None."])
    return lines


def _reproduce(run: Run, plots) -> list[str]:
    log = run.repair_log
    command = log.data.get("command") if log.ok else None
    lines = ["", "## Reproduce", ""]
    if command:
        model = log.data.get("model")
        lines += [f"Compile {model} ({log.data.get('delivered')}):" if model else "Compile:",
                  "", f"    {command}"]
    else:
        lines.append(f"Compile: {log.not_run if not log.ok else NOT_RUN + ' — no compile ran'}")
    lines += ["", "Details: traceability.md, assumptions.md, correspondence.md."]
    if plots is not None:
        lines.append(f"Plots: {len(plots.figures)} in plots/" if plots.status == "ok"
                     else f"Plots: {NOT_RUN} — {plots.reason}")
    return lines


def render_summary(run: Run, plots=None) -> str:
    model = run.model
    title = model.name if model else run.run_dir.name
    lines = [f"# SpecAlive run summary — {title}", ""]
    lines.append(describe(model) if model else f"No system description: {run.ir.not_run}.")
    lines += ["", "## Status", "", *gate_lines(run)]
    if model:
        lines += _ir_sections(model)
    else:
        for heading in ("Counts", "Open questions", "Assumptions",
                        "Conflicts resolved by precedence"):
            lines += ["", f"## {heading}", "", f"{NOT_RUN} — no valid IR ({run.ir.reason})"]
    lines += _reproduce(run, plots)
    return "\n".join(lines) + "\n"


def write_summary(run: Run, out_dir: Path, plots=None) -> Path:
    return write_report(out_dir, REPORT_FILE, render_summary(run, plots))
