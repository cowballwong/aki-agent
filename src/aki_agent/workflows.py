"""Workflows: whole jobs, installed as folders, run on demand.

WHY THIS EXISTS (reported 2026-08-29)
-----------------------------------
He had built a Hong Kong feasibility study — an interview, a statutory
envelope, dimensioned drawings, standard details, visualisations, a fee
proposal, four sign-off gates and an A3 PDF at the end — and asked how it would
eventually arrive here. I said: a plugin.

That correction was right, and it is worth stating plainly, because it is a
category distinction and not a naming preference.

    A tool answers a question.  The calendar reader inside
    `local-ics-calendar` answers "can you read a calendar?" — stateless,
    called, returns, and the caller does not know or care that it exists.

    A workflow does a job.  It owns a project folder, writes intermediates,
    carries sign-off gates, stops halfway for a judgement only a person can
    make, resumes, and ends in a deliverable.

Forcing the second into `provides:` would have been a category error: nothing
about a multi-day process with its own data and its own gates fits a provider's
lifecycle. This package had `skills/` for judgement and `plugins/` for
capabilities, and no slot at all for a process. This is that slot.

A CORRECTION, THREE DAYS LATER (2026-08-29)
-------------------------------------------
The paragraph above originally said "a plugin answers a question", and that
was wrong in a way worth leaving on the record rather than quietly deleting.
The thing that answers a question is a TOOL. A plugin is not a peer of tools,
skills, workflows and panels at all — it is the BOX they arrive in, and one
box can hold all four.

So a workflow is not an alternative to a plugin. It is one of the things a
plugin can contain, and `plugin_workflow_dirs()` below is how it gets found
there. `docs/PACKAGES.md` is the authority on all five words.

WHAT A WORKFLOW IS
------------------
A folder with a `WORKFLOW.md` and, usually, some Python:

    hk-feasibility-study/
        WORKFLOW.md    name, what it produces, its entry, its gates, prose
        skills/        the judgement steps, as Markdown. No code.
        steps/         the deterministic steps, each runnable on its own
        lib/           engines only this workflow uses
        data/          reference data the owner edits
        templates/     anything it fills in

Only `WORKFLOW.md` is required. The rest is the shape that has proved to work,
not a rule — a workflow that is nothing but a manifest and one script is still
a workflow.

THE ONE PLACE THIS DIFFERS FROM A PLUGIN, AND IT MATTERS
---------------------------------------------------------
**A workflow is never imported at discovery time.** `plugins.load_all()` has to
execute `register()` to find out what a plugin provides, which is why that
module is so careful about containing a plugin that raises on import.

Nothing here runs until somebody asks for it by name. Listing workflows reads
manifests and no more, so a workflow with a syntax error in it cannot affect
the morning summary, the dashboard, or another workflow. That is not caution
carried over out of habit; it falls out of what a workflow is.

The trust stance is otherwise identical to `plugins`, and for the same reason:
running one is running somebody's Python as you, with everything you can reach.
`workflow add` shows what it found and refuses without `--yes`, and `workflow
run` says whose code it is about to execute.

RELATIONSHIP TO PLUGINS
-----------------------
A workflow may declare `requires_capabilities:`. Generating a visualisation
needs image generation; searching for precedent needs web search. The workflow
declares what it needs and a plugin — or a built-in — supplies it. Which
provider serves the capability is not the workflow's business, which is the
same separation that lets `agenda` work over any calendar.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import atomic, paths

MANIFEST = "WORKFLOW.md"

# How long `run` waits when a workflow declares nothing. Fifteen
# minutes: long enough for the real ones this package ships, short
# enough that a workflow waiting on something that will never come
# does not hold a dashboard request open until the machine is
# rebooted. A workflow that needs longer says so in its manifest.
DEFAULT_RUN_TIMEOUT = 900


def workflows_dir() -> Path:
    """Where installed workflows live.

    Beside the configuration, for the reason plugins and forked skills are:
    an upgrade replaces the package wholesale, and a workflow somebody has
    been editing for a month must not be inside the thing that gets replaced.
    """
    return paths.app_dir() / "workflows"


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------

@dataclass
class Workflow:
    """One installed workflow, as it declares itself."""

    name: str
    path: Path
    version: str = ""
    title: str = ""
    description: str = ""
    entry: str = ""
    deliverable: str = ""
    gates: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    problem: str = ""

    # How long `run` will wait before stopping this. Declared by the workflow
    # because it is the only thing that knows: a summariser takes seconds, a
    # whole-project report can take twenty minutes, and a single number
    # chosen here would be wrong for one of them. Zero or missing means the
    # default.
    timeout_seconds: int = 0

    # True when this folder lives inside a plugin rather than in the user's
    # own workflows folder. It decides what may be done to it: a plugin's
    # workflow can be switched off, and must never be deleted -- see
    # `remove`.
    from_plugin: bool = False

    @property
    def timeout(self) -> int:
        """Seconds `run` will wait, never zero and never unbounded."""
        declared = int(self.timeout_seconds or 0)
        return declared if declared > 0 else DEFAULT_RUN_TIMEOUT

    @property
    def usable(self) -> bool:
        return not self.problem and bool(self.entry)

    @property
    def on(self) -> bool:
        """Whether it may be run. Off is a choice, never a fault.

        Unlike the skills list -- where a switch was asked for and
        withdrew it the same evening -- there is a real job for one here: a
        workflow that arrived inside a plugin cannot be removed without
        damaging the plugin, so switching it off is the only honest control
        its owner has over it.
        """
        return is_on(self.name)

    @property
    def counts(self) -> dict[str, int]:
        """How much of each kind the folder holds. Read from disk, not
        declared — a manifest that claims twelve skills and ships three should
        show three."""
        out = {}
        for kind in ("skills", "steps", "lib", "data", "templates"):
            folder = self.path / kind
            if folder.is_dir():
                n = sum(1 for _ in folder.rglob("*") if _.is_file())
                if n:
                    out[kind] = n
        return out

    def describe(self) -> str:
        line = self.title or self.name
        if self.version:
            line += f" {self.version}"
        if self.description:
            line += f" — {self.description}"
        return line


def _frontmatter(text: str) -> tuple[dict, str]:
    """YAML frontmatter and the prose after it.

    Same shape as `SKILL.md` and `PLUGIN.md` on purpose: the convention across
    this package is that the thing a person edits is text they can read, and
    the prose under the frontmatter is where it explains itself to whoever
    opens the folder six months from now.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    head, prose = text[3:end], text[end + 4:]
    try:
        import yaml
        data = yaml.safe_load(head) or {}
    except Exception:
        return {}, prose
    return (data if isinstance(data, dict) else {}), prose


def _seconds(value) -> int:
    """A timeout out of a manifest, or 0 when it does not say a usable one.

    Anything unreadable becomes 0, which means the default -- never
    unbounded. A manifest with `timeout_seconds: forever` in it is a mistake
    to fall back from, not an instruction to honour.
    """
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 0
    return seconds if seconds > 0 else 0


def _tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(one).strip() for one in value if str(one).strip())


def read_manifest(folder: Path) -> tuple[Workflow | None, str]:
    """One workflow folder, or None with a sentence saying why not."""
    manifest = folder / MANIFEST
    if not manifest.is_file():
        return None, (f"{folder.name}: no {MANIFEST}, so this folder is not a "
                      "workflow. A workflow needs one, naming it and saying "
                      "what it produces.")
    try:
        text = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"{folder.name}: {MANIFEST} could not be read — {exc}"

    data, prose = _frontmatter(text)
    name = str(data.get("name") or folder.name).strip()
    if not name:
        return None, f"{folder.name}: {MANIFEST} declares no name."

    description = str(data.get("description") or "").strip()
    if not description:
        description = next((line.strip() for line in prose.splitlines()
                            if line.strip() and not line.startswith("#")), "")

    entry = str(data.get("entry") or "").strip()
    problem = ""
    if entry and not (folder / entry).exists():
        # Declared and missing is worth saying. A workflow that cannot be run
        # is still worth listing — somebody should be told why, not left to
        # wonder why the Run button does nothing.
        problem = f"entry `{entry}` is named in {MANIFEST} but is not in the folder"

    return Workflow(
        name=name,
        path=folder,
        version=str(data.get("version") or "").strip(),
        title=str(data.get("title") or "").strip(),
        description=description,
        entry=entry,
        deliverable=str(data.get("deliverable") or "").strip(),
        gates=_tuple(data.get("gates")),
        requires=_tuple(data.get("requires_capabilities")),
        keywords=_tuple(data.get("keywords")),
        timeout_seconds=_seconds(data.get("timeout_seconds")),
        problem=problem,
    ), ""


def plugin_workflow_dirs() -> list[Path]:
    """A `workflows/` folder inside any installed plugin.

    The same seam `panels.plugin_panels_dirs()` opened, for the same reason:
    a plugin is a box, and a whole profession arrives as one — the workflows,
    the skills, the panels and the tools for one trade together, installed and
    removed as a unit.

    Failures are swallowed on purpose. A broken plugin costs the user its own
    workflows and nothing else.
    """
    try:
        from . import plugins

        found, _ = plugins.installed()
        return [one.path / "workflows" for one in found]
    except Exception:
        return []


def installed() -> tuple[list[Workflow], list[str]]:
    """Every workflow folder that declares itself, and every one that does not.

    A folder without a manifest is reported rather than ignored: somebody who
    unzipped one level too deep should be told, not left wondering.

    **Nothing is imported here.** This reads text.
    """
    found: list[Workflow] = []
    problems: list[str] = []

    # The user's own first, then whatever plugins carry. A workflow installed
    # directly wins over a plugin's of the same name, the same precedence
    # `panels.catalogue()` uses, and for the same reason: what somebody put
    # there by hand beats what arrived in a box.
    mine = workflows_dir()
    for root in (mine, *plugin_workflow_dirs()):
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir()):
            if not folder.is_dir() or folder.name.startswith((".", "_")):
                continue
            one, why = read_manifest(folder)
            if one is None:
                problems.append(why)
            elif not any(other.name == one.name for other in found):
                # Recorded here because this is the only place that knows
                # which root it came out of. Working it out later from the
                # path would be a second implementation of the same fact.
                one.from_plugin = (root != mine)
                found.append(one)
    return found, problems


def get(name: str) -> Workflow | None:
    found, _ = installed()
    name = (name or "").strip().lower()
    for one in found:
        if one.name.lower() == name:
            return one
    return None


# ---------------------------------------------------------------------------
# Installing
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    """What a folder or zip would install, before anything is copied."""

    source: str
    workflow: Workflow | None = None
    problem: str = ""
    warnings: list[str] = field(default_factory=list)
    temp: Path | None = None


def _looks_like(folder: Path) -> bool:
    return (folder / MANIFEST).is_file()


def _unwrap(folder: Path) -> Path:
    """A zip of a folder of a folder is the commonest mistake. Look one level
    down before giving up."""
    if _looks_like(folder):
        return folder
    children = [c for c in folder.iterdir() if c.is_dir()] if folder.is_dir() else []
    if len(children) == 1 and _looks_like(children[0]):
        return children[0]
    return folder


def examine(source: str | Path) -> Candidate:
    """Read a folder or zip and say what installing it would add. Copies
    nothing."""
    src = Path(str(source)).expanduser()
    cand = Candidate(source=str(source))

    if not src.exists():
        cand.problem = f"{src} does not exist."
        return cand

    folder = src
    if src.is_file() and src.suffix.lower() == ".zip":
        temp = workflows_dir().parent / f"_workflow_unzip_{src.stem}"
        shutil.rmtree(temp, ignore_errors=True)
        temp.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(src) as zf:
                zf.extractall(temp)
        except Exception as exc:
            cand.problem = f"{src.name} could not be unzipped — {exc}"
            return cand
        cand.temp = temp
        folder = temp

    folder = _unwrap(folder)
    one, why = read_manifest(folder)
    if one is None:
        cand.problem = why
        return cand

    cand.workflow = one
    if one.problem:
        cand.warnings.append(one.problem)
    if not one.entry:
        cand.warnings.append(
            "declares no entry, so it can be read but not run from here")
    if (folder / "steps").is_dir() or (folder / "lib").is_dir():
        cand.warnings.append(
            "contains Python that will run as you when this workflow is run")
    for cap in one.requires:
        cand.warnings.append(f"needs the `{cap}` capability to be available")
    if (workflows_dir() / one.name).exists():
        # `plugins.examine()` has always said this and this did not, so an
        # update would have quietly replaced a workflow with a half-finished
        # project folder inside it. Overwriting somebody's work in progress is
        # the one thing here that cannot be undone.
        cand.warnings.append(
            f"a workflow called '{one.name}' is already installed — this "
            "replaces it, and anything it had in progress goes with it")
    return cand


def consent_text(candidate: Candidate) -> str:
    """What `add` prints before asking for `--yes`.

    The honesty here is louder than it is for a plugin because a workflow
    usually ships more code, and because it is the kind of thing somebody
    passes to a colleague.
    """
    one = candidate.workflow
    if one is None:
        return candidate.problem
    lines = [f"  {one.describe()}"]
    counts = one.counts
    if counts:
        lines.append("  contains: " + ", ".join(
            f"{n} {kind}" for kind, n in counts.items()))
    if one.deliverable:
        lines.append(f"  produces: {one.deliverable}")
    if one.gates:
        lines.append(f"  sign-off gates: {', '.join(one.gates)}")
    for w in candidate.warnings:
        lines.append(f"  ! {w}")
    lines.append("")
    lines.append("  Installing a workflow means trusting whoever wrote it with")
    lines.append("  everything this assistant can reach. Nothing runs on install,")
    lines.append("  but `workflow run` executes its code as you.")
    return "\n".join(lines)


def install(candidate: Candidate) -> tuple[bool, str]:
    one = candidate.workflow
    if one is None:
        return False, candidate.problem
    dest = workflows_dir() / one.name
    if dest.exists():
        return False, (f"{one.name} is already installed. Remove it first, or "
                       "rename the folder you are adding.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(one.path, dest)
    except OSError as exc:
        return False, f"could not copy into {dest} — {exc}"
    return True, f"{one.name} installed into {dest}"


def cleanup(candidate: Candidate) -> None:
    if candidate.temp and candidate.temp.exists():
        shutil.rmtree(candidate.temp, ignore_errors=True)


def switch_file() -> Path:
    """Which workflows have been switched off, by name.

    A list of the OFF ones, so that a workflow arriving later -- from a
    plugin update, or a folder somebody drops in -- is on by default. Storing
    the on ones would mean anything new was silently off and nobody could
    work out why it would not run.
    """
    return paths.state_dir() / "workflows-off.json"


def _switched_off() -> set[str]:
    stored = atomic.read_json(switch_file(), default=[]) or []
    if not isinstance(stored, list):
        return set()
    return {str(one).strip().lower() for one in stored if str(one).strip()}


def is_on(name: str) -> bool:
    return (name or "").strip().lower() not in _switched_off()


def set_on(name: str, on: bool) -> tuple[bool, str]:
    """Switch one on or off. Nothing on disk is moved either way."""
    key = (name or "").strip().lower()
    if not key:
        return False, "no workflow was named."

    off = _switched_off()
    if on:
        off.discard(key)
    else:
        off.add(key)
    atomic.write_json(switch_file(), sorted(off))

    return True, (f"{name} is on." if on else
                  f"{name} is off. It stays installed, and nothing can run "
                  "it until you switch it back on.")


def remove(name: str) -> tuple[bool, str]:
    one = get(name)
    if one is None:
        return False, f"no workflow called {name} is installed."

    # A PLUGIN'S WORKFLOW IS NOT OURS TO DELETE (2026-09-05).
    #
    # `installed()` lists the user's own folder and every plugin's together,
    # which is right for reading and was quietly wrong here: this function
    # is `shutil.rmtree(one.path)`, so pressing Remove on a plugin's workflow
    # deleted files out of the middle of that plugin. The plugin would then
    # be missing a piece with nothing to say so, and the next plugin update
    # would either restore it or fail on it.
    #
    # Found while adding the on/off switch the maintainer asked for, which turns out
    # to be exactly the control this case needed: you cannot uninstall part
    # of somebody else's box, but you can decline to use it.
    if one.from_plugin:
        return False, (
            f"{one.name} came with a plugin, so removing it here would delete "
            "part of that plugin. Switch it off instead, or remove the whole "
            "plugin from Keys & servers.")

    try:
        shutil.rmtree(one.path)
    except OSError as exc:
        return False, f"could not remove {one.path} — {exc}"
    # Forget any switch we were keeping for it, so that installing something
    # of the same name later does not arrive mysteriously switched off.
    off = _switched_off()
    if one.name.lower() in off:
        off.discard(one.name.lower())
        atomic.write_json(switch_file(), sorted(off))
    return True, f"{one.name} removed."


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def run(name: str, args: list[str] | None = None) -> tuple[int, str]:
    """Run a workflow's entry, from inside its own folder.

    The working directory is the workflow's folder because that is what makes
    the folder portable: everything it reads is relative to itself, so it does
    not care where it was installed.
    """
    one = get(name)
    if one is None:
        return 1, f"no workflow called {name} is installed."
    # Checked HERE, not only on the page. A switch that is enforced by hiding
    # a button is not a switch -- the CLI, a scheduled task and anything else
    # that reaches this function would all still run it, and the person who
    # switched it off would have no way of knowing.
    if not one.on:
        return 1, (f"{one.name} is switched off. Turn it back on from "
                   "Workflows if you want to run it.")
    if not one.entry:
        return 1, (f"{one.name} declares no entry, so there is nothing to run. "
                   f"It can still be read at {one.path}.")
    target = one.path / one.entry
    if not target.exists():
        return 1, f"{one.name}: {one.entry} is missing from {one.path}."

    cmd = [sys.executable, str(target), *(args or [])]
    try:
        proc = subprocess.run(cmd, cwd=str(one.path), timeout=one.timeout,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        # WHY THIS IS NOT LEFT TO RUN (2026-09-06)
        # ----------------------------------------
        # This is called from a dashboard request. Without a timeout, a
        # workflow that waits on something -- a prompt nobody will answer, a
        # network call with no deadline of its own -- holds that request open
        # for as long as the machine is on, and the page never comes back.
        # The person pressing Run has no way to tell that from "it is still
        # working", and no way to stop it from the interface that started it.
        #
        # How long is a real decision and it belongs to the workflow, which
        # is the only thing that knows whether it takes ten seconds or twenty
        # minutes. `timeout_seconds` in its manifest; the default below when
        # it says nothing.
        return 1, (f"{one.name} was still running after "
                   f"{one.timeout // 60} minutes, so it was stopped. If it "
                   f"genuinely needs longer, set `timeout_seconds` in "
                   f"{MANIFEST}.")
    except OSError as exc:
        return 1, f"{one.name} could not start — {exc}"

    if proc.returncode == 0:
        return 0, ""

    # A failure used to come back as a code and an empty string, so the page
    # said a workflow had failed and nothing at all about why -- with the
    # explanation the workflow had printed going to the dashboard's own
    # stdout, where nobody was looking.
    detail = (proc.stderr or proc.stdout or "").strip()
    if not detail:
        return proc.returncode, (f"{one.name} stopped with code "
                                 f"{proc.returncode} and said nothing.")
    tail = detail.splitlines()[-12:]
    return proc.returncode, (f"{one.name} stopped with code "
                             f"{proc.returncode}:\n" + "\n".join(tail))


# ---------------------------------------------------------------------------
# For `aki inspect` and the dashboard
# ---------------------------------------------------------------------------

def report() -> dict[str, Any]:
    found, problems = installed()
    return {
        "folder": str(workflows_dir()),
        "installed": [{
            "name": one.name,
            "title": one.title,
            "version": one.version,
            "description": one.description,
            "entry": one.entry,
            "deliverable": one.deliverable,
            "gates": list(one.gates),
            "requires": list(one.requires),
            "counts": one.counts,
            "problem": one.problem,
            "path": str(one.path),
        } for one in found],
        "problems": problems,
    }
