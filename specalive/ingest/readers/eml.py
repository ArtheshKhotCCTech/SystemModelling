# Purpose: reads an email thread into one chunk per message, so a stale value repeated in a reply
# is traced to the message that actually said it. The body is decoded (quoted-printable, charset),
# then split at forwarding separators ("-----Original Message-----", "---- reply ----"), at
# "On ... wrote:" lines and at ">"-quoted blocks; each part's From/Sent/Date lines give its sender
# and date. Messages are ordered newest first by parsed date — thread position is not reliable.
from __future__ import annotations

import email
import re
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from pathlib import Path

from specalive.ingest.evidence import EvidenceChunk
from specalive.ingest.readers._common import (
    ReadContext,
    ReadResult,
    line_range,
    parse_mail_date,
)

SEPARATOR = re.compile(r"^\s*-{2,}\s*[A-Za-z][A-Za-z -]*[A-Za-z]\s*-{2,}\s*$")
WROTE = re.compile(r"^\s*On (?P<when>.+?),\s*(?P<who>[^,]+?)\s+wrote:\s*$")
HEADER = re.compile(r"^(From|Sent|Date|To|Cc|Subject):\s*(.*)$", re.IGNORECASE)


@dataclass
class _Message:
    first_line: int
    headers: dict[str, str] = field(default_factory=dict)
    body: list[tuple[int, str]] = field(default_factory=list)

    @property
    def sender(self) -> str:
        return self.headers.get("from", "unknown sender")

    @property
    def when(self) -> str:
        return self.headers.get("date") or self.headers.get("sent") or ""


def _body_text(msg) -> tuple[str, list[str]]:
    """The plain-text body and a list of what was not read (attachments, HTML-only parts)."""
    skipped: list[str] = []
    part = msg.get_body(preferencelist=("plain",))
    text = ""
    if part is not None:
        text = part.get_content()
    else:
        html = msg.get_body(preferencelist=("html",))
        if html is not None:
            text = re.sub(r"<[^>]+>", "", html.get_content())
            skipped.append("HTML-only body read with tags stripped")
    for attachment in msg.iter_attachments():
        skipped.append(f"attachment {attachment.get_filename() or '(unnamed)'} not read")
    return text, skipped


def _split(top: dict[str, str], text: str) -> list[_Message]:
    messages = [_Message(first_line=1, headers=dict(top))]
    in_headers = False
    in_quote = False
    for number, line in enumerate(text.splitlines(), start=1):
        current = messages[-1]
        quoted = line.lstrip().startswith(">")
        if SEPARATOR.match(line):
            messages.append(_Message(first_line=number))
            in_headers, in_quote = True, False
            continue
        wrote = WROTE.match(line)
        if wrote:
            messages.append(_Message(first_line=number, headers={
                "from": wrote["who"].strip(), "date": wrote["when"].strip()}))
            in_headers, in_quote = False, True
            continue
        if quoted and not in_quote:
            messages.append(_Message(first_line=number))
            in_headers, in_quote = False, True
            current = messages[-1]
        if in_quote:
            if not quoted and line.strip():
                in_quote = False  # the quote ended; what follows belongs to no header
                messages.append(_Message(first_line=number, headers=dict(top)))
                current = messages[-1]
            else:
                line = re.sub(r"^\s*>\s?", "", line)
        current = messages[-1]
        header = HEADER.match(line) if (in_headers or (in_quote and not current.body)) else None
        if header:
            current.headers.setdefault(header[1].lower(), header[2].strip())
            continue
        if in_headers and not line.strip():
            in_headers = False
            continue
        in_headers = False
        current.body.append((number, line))
    return [m for m in messages if any(t.strip() for _, t in m.body)]


def read(path: Path, source_id: str, ctx: ReadContext) -> ReadResult:
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    top = {k: str(msg[k]).strip() for k in ("From", "Date", "Subject") if msg[k]}
    top = {k.lower(): v for k, v in top.items()}
    text, skipped = _body_text(msg)
    messages = _split(top, text)
    if not messages:
        return ReadResult("eml", "unread", "no message text found", top.get("subject"))

    def order(item: tuple[int, _Message]) -> tuple[int, float, int]:
        position, m = item
        when: datetime | None = parse_mail_date(m.when)
        return (0, -when.timestamp(), position) if when else (1, 0.0, position)

    ranked = sorted(enumerate(messages, start=1), key=order)
    chunks = []
    for rank, (position, m) in enumerate(ranked, start=1):
        head = [f"From: {m.sender}"]
        if m.when:
            head.append(f"Date: {m.when}")
        if "subject" in m.headers:
            head.append(f"Subject: {m.headers['subject']}")
        body_lines = [t for _, t in m.body]
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        body = "\n".join(body_lines).strip()
        lines = [n for n, _ in m.body]
        locator = (f"message {rank} of {len(ranked)} (newest first): from {m.sender}"
                   f"{', ' + m.when if m.when else ''}; thread block {position}, decoded body "
                   f"{line_range(lines[0], lines[-1])}")
        chunks.append(EvidenceChunk(source_id=source_id, locator=locator, kind="email_message",
                                    text="\n".join(head) + "\n\n" + body))
    if skipped:
        return ReadResult("eml", "partial", "; ".join(skipped), top.get("subject"), chunks)
    return ReadResult("eml", "read", None, top.get("subject"), chunks)
