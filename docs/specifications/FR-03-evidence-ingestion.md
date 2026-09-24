# Specification - Evidence Ingestion

Delivered by **phase 3**, Track A. Tasks A1, A2. Depends on phase 2 (for source ids and the
`Source` record); produces evidence, never IR.

## Purpose
Read every file in a bundle, whatever its format, into located text the extraction stage can
quote from — and say plainly what could not be read. Classify each source by role and
reliability, because phase 4's precedence ladder ranks roles, not file names.

## Modules
1. `specalive/ingest/evidence.py` — `EvidenceChunk`, `EvidenceBundle`, `Source`.
2. `specalive/ingest/readers/` — `pdf.py`, `docx.py`, `xlsx.py`, `eml.py`, `text.py`
   (`.md`, `.txt`), `modelica.py`, `puml.py`, `json_.py`, `csv_.py`, `image.py`, and a registry
   choosing a reader by extension and content sniffing.
3. `specalive/ingest/classify.py`.
4. CLI: `specalive ingest <bundle_dir | file> -o out/<run>` writes `evidence.json`.

## Requirements
1. A bundle is a directory, walked recursively in sorted order, or a single file.
2. `EvidenceChunk`: `source_id`, `locator`, `text`, `kind` (`prose`, `table_row`, `code`,
   `diagram_text`, `email_message`, `data_summary`). Chunks are small enough to quote from: a
   paragraph, a table row with its header, an email message, a code block.
3. **Tables keep their headers.** An xlsx row becomes a chunk that names its sheet, row number
   and column headers, so "0.8 | m | CR-004 | Approved | Yes" arrives as a readable statement.
   Every sheet is read, including ones with names like `Source_Index` and `Change_Log`.
4. **Emails are split into messages**, newest first, each with sender and date, and
   quoted-printable decoded. A quoted older message is its own chunk, so a stale value in a
   reply is traced to the message that actually said it.
5. **Modelica and PlantUML are read as code**, and their comments kept. Legacy models state
   their own staleness in comments ("STALE", "archived", "predates").
6. **CSV files are summarised, not inlined**: header, row count, time span, and per-column
   min/max/first/last. The full file path is recorded so phase 7 can use it as a reference trace.
7. **Images** go to the vision model if enabled in `config.py`, with a prompt asking only for
   visible labels, tags and connections, returned as `diagram_text` chunks. With vision off, the
   image is recorded as `unread` with the reason. It is never silently skipped.
8. Every source gets a `Source` record: `id` (deterministic from the path), `path`, `format`,
   `status` (`read`, `partial`, `unread`), `reason` when not fully read.
9. **Classification** gives each source a `role`, `revision`, `date` and `reliability`:
   - `role` ∈ {`change_record`, `review_decision`, `requirement_spec`, `design_note`,
     `datasheet`, `verification_procedure`, `reference_data`, `legacy_model`,
     `legacy_architecture`, `correspondence`, `informal_note`, `register`, `other`};
   - when the bundle contains a source-index table (a sheet listing files with type, revision
     and reliability), use it and trace the classification to it;
   - otherwise infer from content, using header fields (Document / Revision / Status / Date) by
     rule first and the LLM only when the rules find nothing.
10. A register workbook is one source with many roles: a change log sheet contributes
    `change_record` chunks, a requirements sheet `requirement_spec` chunks. Role is therefore
    also a **chunk** attribute, defaulting to its source's role.

## Acceptance
1. `specalive ingest` on each of the four `Testcases/` bundles completes without an exception.
2. For each bundle, every file appears in `evidence.json` as a `Source`, with `status` and, when
   not `read`, a reason. The count of sources equals the count of files.
3. L1: a chunk exists quoting the CR-004 row that sets the T1 high limit to 0.8 m, locatable by
   sheet and row; the email thread yields at least three message chunks.
4. L1: the legacy `.mo` is classified `legacy_model`; the design review minutes
   `review_decision`; the test procedure `verification_procedure`.
5. Running ingest twice produces byte-identical `evidence.json` (vision cached).
6. A deliberately corrupt PDF in a scratch bundle yields a `Source` with `status = unread` and a
   reason, and the rest of the bundle is still ingested.

## Rules
| Id | Requirement |
|---|---|
| R-ING-1 | Nothing is silently dropped. Every file is a `Source` with a status. |
| R-ING-2 | Every chunk is locatable: a reviewer can find its text in the original from the locator alone. |
| R-ING-3 | Ingestion never interprets. It does not decide which value is right — that is phase 4. |
| R-ING-4 | Readers contain no bundle-specific logic. A sheet named `Source_Index` is recognised by its columns, not its name. |
| R-ING-5 | Chunk order is deterministic: sorted by source path, then by position in the source. |
