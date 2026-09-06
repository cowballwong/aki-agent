"""Watching the assistant work, rather than reading its diary afterwards.

WHAT THIS READS, AND WHY IT IS NOT A NEW LOG
--------------------------------------------
Claude Code already writes every session to a transcript as it happens. This
reads that file. Nothing new is recorded, nothing is duplicated, and if this
module were deleted the assistant would behave identically — which is the test
of whether a viewer is a viewer or a second source of truth.

The event bus (`events.py`) answers *what happened*, in the words a person
uses. This answers *what is it doing right now*, in the assistant's own steps.
Both are needed and they are not the same thing: a bus entry appears once a
thing is done, and the interesting minutes are the ones before that.

THE CURSOR, AND WHY IT IS A LINE NUMBER
---------------------------------------
A live view polls. Polling that re-reads a growing file from the beginning
gets slower every minute and re-renders what the reader already has. So a
caller passes the line count it last saw and receives only what was appended
after it. Line numbers rather than timestamps because a transcript is
append-only and two entries can share a second.

WHAT IS DELIBERATELY NOT SHOWN
------------------------------
Tool *results* are truncated hard. A file read can be a megabyte, and a viewer
that renders it becomes a slow page that reveals the contents of whatever was
being read. The step ("read a file", "ran a command") is what a person
watching wants; the payload is not.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

from . import paths, secrets

MAX_DETAIL = 400


@dataclass
class Step:
    at: str
    kind: str            # thinking | said | tool | result
    text: str
    tool: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"at": self.at, "kind": self.kind, "text": self.text,
                "tool": self.tool}


def transcript_dir() -> Path:
    return paths.home() / ".claude" / "projects"


def _slug(folder: Path) -> str:
    """Claude Code's folder-name encoding for a project path."""
    text = str(folder).replace(":", "").replace("\\", "-").replace("/", "-")
    return text.replace(" ", "-")


def newest_transcript(folder: Path | None = None) -> Path | None:
    """The transcript being written now, or the most recent one.

    A restart can leave a dead transcript with a NEWER timestamp than the live
    one, which is a rule this package already records elsewhere. This is a
    viewer, so newest-wins is acceptable and the honest caveat is that it may
    briefly show a session that has just ended -- better than showing nothing
    and better than pretending to know which process owns which file.
    """
    root = transcript_dir()
    if not root.exists():
        return None

    candidates: list[Path] = []
    if folder is not None:
        specific = root / _slug(folder)
        if specific.exists():
            candidates = list(specific.glob("*.jsonl"))
    if not candidates:
        candidates = list(root.glob("*/*.jsonl"))
    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def read(folder: Path | None = None, *, since_line: int = 0,
         limit: int = 200) -> tuple[list[Step], int]:
    """Steps appended after `since_line`, plus the new cursor."""
    path = newest_transcript(folder)
    if path is None:
        return [], 0

    try:
        lines = path.read_text(encoding="utf-8",
                               errors="replace").splitlines()
    except OSError:
        return [], since_line

    fresh = lines[since_line:] if since_line else lines[-limit:]
    steps: list[Step] = []
    for line in fresh:
        steps.extend(_steps_from(line))
    return steps[-limit:], len(lines)


def _steps_from(line: str) -> list[Step]:
    try:
        entry = json.loads(line)
    except ValueError:
        return []

    message = entry.get("message") or {}
    content = message.get("content")
    stamp = str(entry.get("timestamp", ""))[11:19]
    role = message.get("role", "")

    if isinstance(content, str):
        return [Step(stamp, "said" if role == "assistant" else "heard",
                     _short(content))] if content.strip() else []

    if not isinstance(content, list):
        return []

    out: list[Step] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text" and block.get("text", "").strip():
            out.append(Step(stamp, "said" if role == "assistant" else "heard",
                            _short(block["text"])))
        elif kind == "thinking" and block.get("thinking", "").strip():
            out.append(Step(stamp, "thinking", _short(block["thinking"])))
        elif kind == "tool_use":
            name = str(block.get("name", "tool"))
            out.append(Step(stamp, "tool", _describe(block.get("input")),
                            tool=name))
        elif kind == "tool_result":
            out.append(Step(stamp, "result", _short(
                _flatten(block.get("content")))))
    return out


def _flatten(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [block.get("text", "") for block in content
                 if isinstance(block, dict)]
        return " ".join(part for part in parts if part)
    return ""


def _describe(payload) -> str:
    """One line naming what a tool was asked to do, never the whole payload."""
    if not isinstance(payload, dict):
        return _short(str(payload or ""))
    for key in ("description", "command", "file_path", "path", "pattern",
                "query", "prompt"):
        if payload.get(key):
            return _short(str(payload[key]))
    return _short(", ".join(sorted(payload)[:4]))


def _short(text: str) -> str:
    clean = secrets.redact(" ".join(str(text or "").split()))
    return clean[:MAX_DETAIL - 1] + "…" if len(clean) > MAX_DETAIL else clean


def is_working(folder: Path | None = None,
               within_seconds: int = 90) -> bool:
    """Has the transcript been written to recently enough to look alive?"""
    path = newest_transcript(folder)
    if path is None:
        return False
    try:
        age = _dt.datetime.now().timestamp() - path.stat().st_mtime
    except OSError:
        return False
    return age <= within_seconds
