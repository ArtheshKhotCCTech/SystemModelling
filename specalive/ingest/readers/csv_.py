# Purpose: summarises a CSV data file instead of inlining it — a reference trace has thousands of
# rows and none of them is worth quoting alone. One chunk gives the file, header, row count and
# the time span of the first time-like column; one chunk per column gives min/max/first/last for
# numeric columns, or the distinct values for text ones. The file path is kept for phase 7.
from __future__ import annotations

import csv
import io
import math
from pathlib import Path

from specalive.ingest.evidence import EvidenceChunk
from specalive.ingest.readers._common import ReadContext, ReadResult

MAX_DISTINCT = 12


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _fmt(value: float) -> str:
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)


def read(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        return ReadResult("csv", "unread", "file is empty")
    header, data = [h.strip() for h in rows[0]], rows[1:]
    columns = [[r[i].strip() if i < len(r) else "" for r in data] for i in range(len(header))]
    numeric = [[_number(v) for v in col if v] for col in columns]
    is_numeric = [bool(col) and all(v is not None for v in nums)
                  for col, nums in zip(columns, numeric)]

    summary = [f"file: {path.name}", f"columns: {', '.join(header)}", f"rows: {len(data)}"]
    time_col = next((i for i, h in enumerate(header) if "time" in h.lower() and is_numeric[i]),
                    None)
    if time_col is not None:
        values = numeric[time_col]
        summary.append(f"time span: {header[time_col]} from {_fmt(min(values))} "
                       f"to {_fmt(max(values))}")
    ragged = sum(1 for r in data if len(r) != len(header))
    if ragged:
        summary.append(f"rows with a different number of cells than the header: {ragged}")
    chunks = [EvidenceChunk(source_id=source_id, locator="file summary",
                            text="\n".join(summary), kind="data_summary")]

    for i, name in enumerate(header):
        present = [v for v in columns[i] if v]
        if not present:
            desc = f"column {name}: empty"
        elif is_numeric[i]:
            nums = numeric[i]
            desc = (f"column {name}: numeric, min {_fmt(min(nums))}, max {_fmt(max(nums))}, "
                    f"first {_fmt(nums[0])}, last {_fmt(nums[-1])}")
        else:
            distinct = list(dict.fromkeys(present))
            shown = ", ".join(distinct[:MAX_DISTINCT])
            more = f" (+{len(distinct) - MAX_DISTINCT} more)" if len(distinct) > MAX_DISTINCT \
                else ""
            desc = (f"column {name}: text, {len(distinct)} distinct value(s): {shown}{more}; "
                    f"first {present[0]}, last {present[-1]}")
        chunks.append(EvidenceChunk(source_id=source_id, locator=f"column {i + 1} ({name})",
                                    text=desc, kind="data_summary"))
    return ReadResult("csv", "read", None, None, chunks)
