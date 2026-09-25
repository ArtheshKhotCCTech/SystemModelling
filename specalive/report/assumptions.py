# Purpose: assumptions.md — everything the pipeline did not find stated plainly in the inputs:
# the IR's assumptions (basis, affected elements), each conflict with every candidate, its source,
# rank and the rationale for the winner, and the questions; then what extraction dropped or could
# not place (extract_report.json), sources not fully read (evidence.json) and the defaults that
# verification and the generator declared. A missing artefact makes its section NOT RUN.
from __future__ import annotations

import re
from pathlib import Path

from specalive.core.ir import Conflict, SystemModel
from specalive.report.artefacts import Artefact, Run, source_label, table, write_report

REPORT_FILE = "assumptions.md"
UNRESOLVED = "unresolved"
_GENERATOR_DEFAULT = re.compile(r"//\s*ASSUMPTION \(generator default\):\s*(.*)$")


def winners(conflict: Conflict) -> list:
    """The candidates holding the winning value, by authority."""
    return sorted((c for c in conflict.candidates if c.value == conflict.resolution),
                  key=lambda c: c.authority_rank)


def _assumptions(model: SystemModel) -> list[str]:
    if not model.assumptions:
        return ["None in the IR."]
    rows = []
    for a in sorted(model.assumptions, key=lambda a: a.id):
        sources = ", ".join(sorted({link.source_id for link in a.trace})) or "—"
        rows.append([f"`{a.id}`", a.text, a.basis, f"{a.confidence:g}",
                     ", ".join(f"`{e}`" for e in a.affects) or "—", sources])
    return table(["Id", "Assumption", "Basis", "Confidence", "Affects", "Sources"], rows)


def _conflicts(model: SystemModel) -> list[str]:
    if not model.conflicts:
        return ["None in the IR."]
    lines: list[str] = []
    for c in sorted(model.conflicts, key=lambda c: c.id):
        lines += [f"### `{c.id}` — `{c.subject.element_id}`.{c.subject.field}", ""]
        rows = [[cand.authority_rank, cand.value,
                 f"{cand.source_id} ({source_label(model, cand.source_id)})",
                 f"`{cand.element_id}`" if cand.element_id else "—",
                 "winner" if cand.value == c.resolution else "lost"]
                for cand in sorted(c.candidates, key=lambda x: (x.authority_rank, x.source_id))]
        lines += table(["Rank", "Value", "Source", "Held by", "Outcome"], rows)
        verdict = ("UNRESOLVED — precedence could not settle it; see the questions"
                   if c.resolution == UNRESOLVED else f"Winner: {c.resolution}")
        lines += ["", f"{verdict}. Why: {c.rationale}", ""]
    return lines[:-1]


def _questions(model: SystemModel) -> list[str]:
    if not model.questions:
        return ["None in the IR."]
    lines = []
    for q in sorted(model.questions, key=lambda q: q.id):
        options = " / ".join(q.options) if q.options else "none listed"
        answer = f"answer: {q.answer}" if q.answer is not None else "unanswered"
        affects = ", ".join(f"`{e}`" for e in q.affects) or "—"
        lines.append(f"- `{q.id}`: {q.text} Options: {options}; default if unanswered: "
                     f"{q.default_if_unanswered or 'none stated'}; {answer}. Affects: {affects}.")
    return lines


def _extract_list(report: Artefact, key: str, render) -> list[str]:
    if not report.ok:
        return [report.not_run + " (the IR was not produced by `specalive extract` here)"]
    items = report.data.get(key) or []
    return [render(item) for item in items] or ["None."]


def _unread_sources(evidence: Artefact) -> list[str]:
    if not evidence.ok:
        return [evidence.not_run + " (no ingestion in this run)"]
    lines = [f"- {s.get('status')}: `{s.get('path')}` — {s.get('reason') or 'no reason given'}"
             for s in sorted(evidence.data.get("sources") or [], key=lambda s: s.get("path", ""))
             if s.get("status") != "read"]
    return lines or ["None — every source was read."]


def _declared_defaults(run: Run) -> list[str]:
    lines = []
    if run.verification.ok:
        lines += [f"- verification: {a}" for a in run.verification.data.get("assumptions") or []]
    else:
        lines.append(f"- verification: {run.verification.not_run}")
    if run.modelica.ok:
        for line in run.modelica.data.splitlines():
            m = _GENERATOR_DEFAULT.search(line)
            if m:
                lines.append(f"- generator default ({run.modelica.name}): {m[1]}")
    else:
        lines.append(f"- generator: {run.modelica.not_run}")
    return lines or ["None."]


def render_assumptions(run: Run) -> str:
    model = run.model
    name = model.name if model else "no IR"
    ir_sections = ([("Assumptions", _assumptions(model)), ("Conflicts", _conflicts(model)),
                    ("Questions", _questions(model))] if model else
                   [(h, [run.ir.not_run]) for h in ("Assumptions", "Conflicts", "Questions")])
    report = run.extract_report
    sections = ir_sections + [
        ("Rejected untraced elements", _extract_list(
            report, "rejected_untraced",
            lambda r: f"- {r.get('kind')} `{r.get('id')}`: {r.get('reason')}")),
        ("Missing information", _extract_list(report, "missing_information", lambda s: f"- {s}")),
        ("Unresolved fragments", _extract_list(report, "unresolved", lambda s: f"- {s}")),
        ("Discarded fragments", _extract_list(
            report, "discarded_fragments",
            lambda d: f"- {d.get('kind')} from `{d.get('chunk_id')}`: {d.get('reason')} "
                      f"(quote: “{d.get('quote')}”)")),
        ("Sources not fully read", _unread_sources(run.evidence)),
        ("Defaults declared by the pipeline", _declared_defaults(run)),
    ]
    lines = [f"# Assumptions, conflicts and questions — {name}", "",
             "What the model rests on beyond what the inputs state plainly, what the inputs "
             "disagreed about and why the winner won, and what is still open."]
    for heading, body in sections:
        lines += ["", f"## {heading}", "", *body]
    return "\n".join(lines) + "\n"


def write_assumptions(run: Run, out_dir: Path) -> Path:
    return write_report(out_dir, REPORT_FILE, render_assumptions(run))
