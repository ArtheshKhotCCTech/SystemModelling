# Purpose: the single subprocess runner behind every external-tool call (R-FND-4). Each call has
# a timeout and returns a ToolResult {ok, command, stdout, stderr, duration, returncode}; a
# missing executable, a timeout or a non-zero exit is data in that result, never an exception.
# Output is decoded as UTF-8 with replacement so tool messages always reach the reports.
from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    command: tuple[str, ...]
    stdout: str
    stderr: str
    duration: float
    returncode: int | None

    @property
    def command_line(self) -> str:
        """The command as one pasteable line — what a judge would run."""
        return subprocess.list2cmdline(self.command)


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a toolchain probe: pass/fail, a one-line explanation, and the raw tool runs."""

    ok: bool
    detail: str
    runs: tuple[ToolResult, ...] = ()


def run_tool(command: Sequence[str], *, timeout: float, cwd: Path | None = None,
             stdin_text: str | None = None) -> ToolResult:
    cmd = tuple(str(part) for part in command)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=stdin_text.encode("utf-8") if stdin_text is not None else None,
            stdin=None if stdin_text is not None else subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
        )
    except FileNotFoundError:
        return ToolResult(False, cmd, "", f"executable not found: {cmd[0]}",
                          time.monotonic() - start, None)
    except subprocess.TimeoutExpired as exc:
        return ToolResult(False, cmd, _decode(exc.stdout), f"timed out after {timeout:g} s",
                          time.monotonic() - start, None)
    except OSError as exc:
        return ToolResult(False, cmd, "", f"could not start {cmd[0]}: {exc}",
                          time.monotonic() - start, None)
    return ToolResult(proc.returncode == 0, cmd, _decode(proc.stdout), _decode(proc.stderr),
                      time.monotonic() - start, proc.returncode)


def _decode(data: bytes | None) -> str:
    return data.decode("utf-8", errors="replace") if data else ""
