"""Stand in front of the one change in this package that cannot be undone.

WHY THIS EXISTS (2026-09-12)
----------------------------
`INSTALL.md` ends on this sentence:

    Everything here is reversible except one thing: running a first-time
    setup over a configuration that already exists.

That was true, and nothing enforced it. The `setup` skill writes
`config.yaml` with the `Write` tool and has no check of its own; its
description says it triggers on "start again". So somebody typing
`/aki-agent:setup` -- never having opened `INSTALL.md`, which is where the
warning lives -- got their configuration replaced, with no copy kept and
nothing said. The assistant still started. It simply no longer knew who they
were.

A warning in a document the reader will not open is not a guard. It is a note
for whoever is already being careful.

WHAT THIS DOES, AND WHY IT DOES IT IN THIS ORDER
------------------------------------------------
1. **Keeps a copy, always.** This is the part that matters, and it happens
   before any decision about whether to interrupt. The irreversible thing
   becomes reversible, whether or not anybody reads what comes next.
2. **Interrupts once.** The first attempt is refused with the copy's location
   and the question to put to the person. A second attempt at the same file
   goes through -- because by then somebody has been told, and a guard that
   cannot be got past on purpose is a guard that gets switched off.

FAIL OPEN
---------
Same trade as `safety_gate`: if this module breaks it allows the write and
records the failure. A broken guard must not be able to stop somebody
configuring their assistant.
"""

from __future__ import annotations

import time
from pathlib import Path

# How long a refusal stays remembered. Long enough for the assistant to ask
# and the person to answer; short enough that tomorrow's accident is caught
# again rather than waved through on yesterday's decision.
GRACE_SECONDS = 15 * 60

HISTORY_DIR = "config-history"
MARKER_NAME = "config-guard-waved.txt"


def _state_dir() -> Path:
    from . import paths

    return paths.app_dir() / "state"


def history_dir() -> Path:
    return _state_dir() / HISTORY_DIR


def is_a_config(path: Path) -> bool:
    """Is this the file the whole assistant reads itself out of?

    Matched by name rather than by full path because there are two legitimate
    locations -- `~/.aki-agent/config.yaml` before the workspace exists, and
    `<their folder>/01_Config/config.yaml` afterwards -- and a third would be
    added without anybody remembering to come back here.
    """
    return path.name.lower() in ("config.yaml", "config.yml")


def keep_a_copy(path: Path) -> Path | None:
    """Copy the existing configuration somewhere the write cannot reach."""
    import shutil

    if not path.is_file():
        return None

    target_dir = history_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M%S")

    # Two copies inside the same second is not a hypothetical -- the guard
    # runs again on the retry, which follows immediately. Without this the
    # second copy silently replaced the first, and the file being protected
    # was the one that got lost.
    target = target_dir / f"config-{stamp}.yaml"
    attempt = 2
    while target.exists():
        target = target_dir / f"config-{stamp}-{attempt}.yaml"
        attempt += 1

    shutil.copy2(path, target)
    return target


def _marker() -> Path:
    return _state_dir() / MARKER_NAME


def _was_waved_through(path: Path) -> bool:
    marker = _marker()
    try:
        recorded, _, remembered = marker.read_text(
            encoding="utf-8").partition("\n")
        if remembered.strip() != str(path):
            return False
        return (time.time() - float(recorded.strip())) < GRACE_SECONDS
    except Exception:                                     # noqa: BLE001
        return False


def _remember_the_refusal(path: Path) -> None:
    marker = _marker()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{time.time()}\n{path}", encoding="utf-8")


def assess(path: Path) -> tuple[bool, str]:
    """Returns (allowed, what to say). Never raises."""
    if not is_a_config(path) or not path.is_file():
        return True, ""

    kept = keep_a_copy(path)

    if _was_waved_through(path):
        return True, ""

    _remember_the_refusal(path)

    where = f"\n  A copy of the old one is at: {kept}" if kept else ""
    return False, (
        "STOP -- there is already a configuration at "
        f"{path}, and this would replace it."
        f"{where}\n\n"
        "Ask the person before going any further:\n\n"
        '  "You already have an assistant set up here. Do you want to start '
        'again from scratch, or change one thing about the setup you have?"\n\n'
        "If they want to change one thing, do that instead -- there is no "
        "need to redo the interview.\n"
        "If they genuinely want to start again, write the file again and it "
        "will go through."
    )


def main(argv: list[str] | None = None) -> int:
    """PreToolUse hook for `Write`. Exit 2 refuses; exit 0 allows."""
    import json
    import sys

    try:
        payload = sys.stdin.read()
    except Exception as exc:                              # noqa: BLE001
        _record_failure(f"could not read its input, so it allowed it: {exc}")
        return 0

    try:
        data = json.loads(payload) if payload.strip().startswith("{") else {}
        raw = str((data.get("tool_input") or {}).get("file_path", ""))
        if not raw:
            return 0
        allowed, message = assess(Path(raw))
    except Exception as exc:                              # noqa: BLE001
        _record_failure(f"failed while checking a write, so it allowed it: "
                        f"{exc}")
        return 0

    if allowed:
        return 0
    print(message, file=sys.stderr)
    return 2


def _record_failure(what: str) -> None:
    try:
        from . import events

        events.record("problem", f"the configuration guard {what}",
                      source="config-guard")
    except Exception:                                     # noqa: BLE001
        pass


if __name__ == "__main__":
    raise SystemExit(main())
