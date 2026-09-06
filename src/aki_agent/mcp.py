"""MCP servers: what is connected, and adding one without breaking anything.

reported 2026-08-19: "我發現個dashboard無MCP setting".

WHERE MCP CONFIGURATION ACTUALLY LIVES
--------------------------------------
Two places, and the difference decides everything this module is allowed to
touch:

* **`~/.claude.json`** — Claude Code's own file. It holds user-scope servers
  *and a section for every project on the machine*, along with a great deal of
  unrelated state.
* **`.mcp.json` in a project folder** — project scope, read when a session
  starts in that folder.

**This module writes only the second one, and only in the assistant's own
folder.** Editing `~/.claude.json` would mean this package writing into a file
that every other project on the machine depends on, that Claude Code rewrites
under us, and that contains state we do not understand. Reading it to *show*
what is connected is fine; writing it is not ours to do.

The project file is also the better home for a user: it sits in the folder
they back up, it moves with the assistant, and they can read it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import atomic, paths

PROJECT_FILE = ".mcp.json"


@dataclass
class Server:
    """One MCP server the assistant can reach."""

    name: str
    command: str = ""
    args: tuple = ()
    scope: str = "workspace"        # workspace | user
    editable: bool = True           # only workspace entries are ours to change

    def describe(self) -> str:
        return " ".join([self.command, *self.args]).strip() or "(no command)"


def project_file(root: Path | None = None) -> Path:
    """The assistant's own `.mcp.json`."""
    base = Path(root) if root else paths.app_dir().parent
    return base / PROJECT_FILE


def claude_config() -> Path:
    """Claude Code's own file. Read only, ever."""
    return paths.home() / ".claude.json"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}


def read(root: Path | None = None) -> list[Server]:
    """Everything reachable, workspace first, marked by where it came from."""
    found: list[Server] = []

    for name, entry in (_read_json(project_file(root)).get("mcpServers")
                        or {}).items():
        found.append(Server(name=name,
                            command=str((entry or {}).get("command", "")),
                            args=tuple((entry or {}).get("args") or ()),
                            scope="workspace", editable=True))

    # Shown but never touched: these belong to Claude Code and to every other
    # project on this machine.
    for name, entry in (_read_json(claude_config()).get("mcpServers")
                        or {}).items():
        if any(server.name == name for server in found):
            continue
        found.append(Server(name=name,
                            command=str((entry or {}).get("command", "")),
                            args=tuple((entry or {}).get("args") or ()),
                            scope="user", editable=False))

    return sorted(found, key=lambda server: (server.scope != "workspace",
                                             server.name.casefold()))


def add(name: str, command: str, args: tuple = (), root: Path | None = None,
        env: dict | None = None) -> tuple[bool, str]:
    """Add a server to the assistant's own `.mcp.json`."""
    name = (name or "").strip()
    command = (command or "").strip()
    if not name:
        return False, "A server needs a name."
    if not command:
        return False, "A server needs a command to run."

    path = project_file(root)
    data = _read_json(path)
    servers = dict(data.get("mcpServers") or {})

    if name in servers:
        return False, (f"{name} is already there. Remove it first if you want "
                       "to change it — silently replacing a working server is "
                       "how an assistant loses a tool nobody notices.")

    entry: dict = {"command": command}
    if args:
        entry["args"] = list(args)
    if env:
        entry["env"] = dict(env)
    servers[name] = entry
    data["mcpServers"] = servers

    try:
        atomic.write_json(path, data)
    except OSError as exc:                                # pragma: no cover
        return False, f"could not write {path}: {exc}"

    return True, (f"Added {name} to {path.name}. **Restart Claude Code** — "
                  "servers are read when a session starts, so nothing changes "
                  "until it does.")


def remove(name: str, root: Path | None = None) -> tuple[bool, str]:
    """Remove a server from the assistant's own file. Never from Claude's."""
    path = project_file(root)
    data = _read_json(path)
    servers = dict(data.get("mcpServers") or {})

    if name not in servers:
        return False, (f"{name} is not in {path.name}. If it is listed as a "
                       "user server, it belongs to Claude Code itself and this "
                       "will not touch it — remove it with `claude mcp remove`.")

    servers.pop(name)
    data["mcpServers"] = servers
    try:
        atomic.write_json(path, data)
    except OSError as exc:                                # pragma: no cover
        return False, f"could not write {path}: {exc}"

    return True, f"Removed {name}. Restart Claude Code to apply it."
