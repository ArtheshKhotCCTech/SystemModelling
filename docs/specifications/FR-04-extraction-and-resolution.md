# Specification - Extraction and Resolution

Delivered by **phase 4**, Track A. Tasks A3, A4, A5, A6, A8; A7 (interactive questions) is
stretch. Depends on phase 3. This is where the PRD's input-handling requirements (§6.3) are
met or failed.

## Purpose
Turn evidence into a single, schema-valid IR in which every element is traced, every
contradiction is either resolved by stated precedence or asked about, and every inference is
declared.

## Modules
1. `specalive/extract/extract.py` — LLM extraction passes.
2. `specalive/extract/merge.py` — entity resolution.
3. `specalive/extract/precedence.py` — the precedence ladder.
4. `specalive/extract/gaps.py` — assumptions, missing information, honesty gate.
5. `specalive/extract/text_input.py` — plain-text input.
6. `specalive/extract/questions.py` — interactive clarifying questions (stretch).
7. CLI: `specalive extract -i out/<run>/evidence.json -o out/<run>` writes `ir.json`.

## Requirements

### Extraction
1. Extraction runs **per source**, in a fixed order, then merges. Each pass returns IR
   *fragments* via structured outputs: candidate parts (with a catalogue `kind`), ports,
   connections, parameters, states and transitions, requirements, acceptance criteria.
2. The prompt gives the model the catalogue kinds and their descriptions, and requires a
   **verbatim supporting quote and chunk id** for every fragment. A fragment whose quote does not
   occur in the cited chunk is discarded and counted — not repaired.
3. The model may answer `kind = unknown` with a description. That becomes a `Question`
   ("the input describes X; no catalogue component matches"), never an emitted part.
4. Fragments carry the role of the chunk they came from, for the ladder.

### Merging
5. Aliases are unified into one element when the evidence equates them: an explicit mapping
   (a table with tag and alias columns, a "naming cross-reference" section), or the same tag.
   The merged element keeps every alias in `tags` and the union of traces.
6. An alias the evidence does not equate but that looks similar (`valve1` vs `V1` with no table
   linking them) is merged only with an `Assumption` naming the basis, and a `confidence` below
   the default.
7. Legacy names (e.g. state names from an archived model) are recorded as aliases of the
   current element, so the report can show the mapping.

### Precedence
8. When fragments give different values for the same parameter, `precedence.py` ranks them by
   the ladder in `../design/ADR.md` (approved change > review decision > released spec/design
   note > datasheet > legacy > informal), using the chunk role and, within a role, the later
   approved date.
9. The winner becomes the parameter value with `status = effective`. **Every loser is kept**
   (`status = superseded`) and a `Conflict` records all candidates, their sources, ranks and the
   rationale in one sentence.
10. A value that a source marks as a different configuration — "as-built", "prototype",
    "test configuration only" — is not a loser: it is kept with `status = as_built_only` or
    `verification_only` and is not a conflict.
11. Two candidates of equal rank that disagree, or a winner whose own source says it is
    provisional ("subject to", "pending", "to be confirmed"), produce a `Question` with the
    candidates as options and the ladder's choice as the default.
12. Status fields already present in the evidence (a register's `Status` / `Superseded By` /
    `Effective?` columns) are used and traced; the ladder is the fallback, not the override.

### Gaps and honesty
13. `gaps.py` checks each part against its catalogue entry's required attributes. A missing
    value is filled from the catalogue default **with its recorded assumption**, or, if the
    catalogue has no default, becomes a `Question`.
14. Implicit engineering conventions (a tank has an outlet; a fail-closed valve is closed at
    start; initial levels default to the stated minimum) are applied only through catalogue
    defaults or an explicit rule list in `gaps.py`, each producing an `Assumption`.
15. **Honesty gate.** Before `ir.json` is written, every element without a trace or assumption
    is removed and listed in the output as `rejected_untraced`. The gate never adds traces.
16. The stage writes a `missing_information` list: required values with no source, and
    references to documents the bundle does not contain.

### Plain-text input
17. `specalive extract --text "<paragraph>"` or `--text-file spec.txt` treats the text as a
    one-source bundle with role `requirement_spec` and runs the same passes. There is no
    separate code path for text.

### Clarifying questions (stretch, A7)
18. With `--interactive`, open `Question`s are asked on the terminal before `ir.json` is
    written; each answer is stored as evidence with its own `TraceLink` (source `user`,
    timestamp) and the question marked answered. Without it, defaults apply and the questions
    stay open in the report.

## Acceptance
1. On L1, `ir.json` validates against the schema.
2. On L1, the effective parameters are T1 high = 0.80 m, post-transfer wait = 12 s,
   inter-cycle wait = 8 s, with a `Conflict` for each naming the 0.78 m / 10 s / 10 s losers and
   their sources.
3. On L1, "SHUT" is extracted as a controlled drain command, not an emergency stop, traced to
   the review minutes.
4. On L1, `tank1`, `TK-101` and `T1` are one part; `valve1`, `XV-101` and `V1` are one part.
5. On L1, structural coverage against the golden IR (phase 7, `coverage.py`) is **at least
   80 %** on parts, ports and connections. Before phase 7 lands, compare by a script in the pull
   request and quote the numbers.
6. The one-paragraph text spec in `tests/adversarial/` produces a valid IR in under 2 minutes
   on a cold cache.
7. Running extract twice on the same evidence produces identical `ir.json` (cache).
8. A test with a hand-crafted fragment whose quote is not in its chunk shows the fragment
   discarded and counted.

## Rules
| Id | Requirement |
|---|---|
| R-EXT-1 | Missing information is inferred with a stated assumption or surfaced as a question. It is never silently invented. (PRD §6.3) |
| R-EXT-2 | Contradictions are flagged. A resolution by precedence is recorded as a Conflict; an unrankable one becomes a Question. (PRD §6.3) |
| R-EXT-3 | No component, port or physics that is not derivable from the input or a declared standard assumption. (PRD §6.3) |
| R-EXT-4 | Quotes are verbatim and verified against their chunk. |
| R-EXT-5 | The ladder ranks roles, never file names. |
| R-EXT-6 | A configuration variant (as-built, prototype, verification-only) is not a conflict and does not replace the nominal value. |
| R-EXT-7 | Newest is not authoritative. Approval status outranks recency. |
| R-EXT-8 | Plain text and bundles share one code path. |
