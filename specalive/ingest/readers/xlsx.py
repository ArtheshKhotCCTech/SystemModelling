# Purpose: reads every sheet of a workbook, whatever it is called. The header row is found by
# shape — the first row with two or more text cells — so title rows above it are kept as prose;
# each later row becomes one table_row chunk that names its sheet and row and pairs every value
# with its column header, with the header -> value map kept in `fields` for the classifier and
# phase 4. A formula whose cached value is missing is reported, never read as empty.
from __future__ import annotations

from pathlib import Path

from specalive.ingest.evidence import EvidenceChunk
from specalive.ingest.readers._common import (
    ReadContext,
    ReadResult,
    cell_text,
    fields_text,
    row_fields,
)


def _is_header(values: list) -> bool:
    filled = [v for v in values if v not in (None, "")]
    return len(filled) >= 2 and all(isinstance(v, str) for v in filled)


def read(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    import openpyxl

    values_wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    formulas_wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    chunks: list[EvidenceChunk] = []
    uncached: list[str] = []
    try:
        for sheet in values_wb.worksheets:
            formula_rows = list(formulas_wb[sheet.title].iter_rows(values_only=True))
            headers: list[str] | None = None
            for number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                raw = list(row)
                formulas = formula_rows[number - 1] if number <= len(formula_rows) else ()
                for col, (value, formula) in enumerate(zip(raw, formulas), start=1):
                    if value is None and isinstance(formula, str) and formula.startswith("="):
                        uncached.append(f"{sheet.title}!R{number}C{col}")
                cells = [cell_text(v) for v in raw]
                if not any(cells):
                    continue
                locator = f"sheet {sheet.title}, row {number}"
                if headers is None:
                    if _is_header(raw):
                        headers = cells
                        continue
                    chunks.append(EvidenceChunk(source_id=source_id, locator=locator,
                                                text=" | ".join(c for c in cells if c),
                                                kind="prose"))
                    continue
                fields = row_fields(headers, cells)
                chunks.append(EvidenceChunk(source_id=source_id, locator=locator,
                                            text=fields_text(fields), kind="table_row",
                                            fields=fields))
    finally:
        values_wb.close()
        formulas_wb.close()

    title = next((c.text for c in chunks if c.kind == "prose"), None)
    if uncached:
        shown = ", ".join(uncached[:10]) + (" ..." if len(uncached) > 10 else "")
        return ReadResult("xlsx", "partial",
                          f"{len(uncached)} formula cell(s) have no cached value: {shown}",
                          title, chunks)
    return ReadResult("xlsx", "read", None, title, chunks)
