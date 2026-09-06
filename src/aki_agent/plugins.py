"""Third-party plugins: folders that add providers without editing this package.

WHY THIS EXISTS (reported 2026-08-26)
-----------------------------------
The seams work made the four swappable parts swappable, but only from inside:
adding a calendar meant writing a class in `calendar_seam.py` and naming it in
that module's defaults. I argued that was enough, because nobody outside was
waiting to write one. He disagreed ——
and that is the call.

So this is the DeepSeek Harness's install path in Python. There it is
`dsh plugin add <path|github|npm|tarball>`, a `dsh.bundle` field in the
package's own `package.json`, and a package that declares nothing installs as a
plain library with a warning rather than an error. Here it is
`aki plugin add <folder|zip>`, a `PLUGIN.md`, and the same forgiving failure.

WHAT A PLUGIN IS
----------------
A folder with a `PLUGIN.md` and some Python:

    my-icloud-calendar/
        PLUGIN.md          name, version, what it provides, prose for a human
        plugin.py          def register(seams): ...

`PLUGIN.md` carries YAML frontmatter for exactly the reason `SKILL.md` does:
this package's whole convention is that the thing a person edits is text they
can read, and the prose under the frontmatter is where the plugin explains
itself to whoever finds it in a folder six months from now.

`register(seams)` receives this package's `seams` module and registers whatever
it likes:

    def register(seams):
        seams.seam("calendar").register(ICloudCalendar())

A plugin's providers are then ordinary providers. Nothing downstream can tell
them from the built-in ones, which is the entire point — `agenda`,
`calendar-add`, the month view and the `providers:` list all work on them
without knowing they exist.

THE TRUST STANCE, COPIED VERBATIM IN SPIRIT
-------------------------------------------
A plugin is Python running as the user, with the user's mail and calendars in
reach. DeepSeek says of its own dynamic plugins: *"The sandbox isolates globals
but is not a security boundary… Treat this toolset like bash access."* There is
not even a sandbox here, so the honesty has to be louder: `plugin add` shows
what it found and refuses to proceed without `--yes`, and the phrasing says
plainly that installing one is trusting its author with everything the
assistant can reach.

That is a real limit, stated rather than engineered around. A permission model
worth the name is a much larger piece of work, and pretending a weak one is
strong is worse than having none.

ONE BROKEN PLUGIN MUST NOT TAKE THE ASSISTANT DOWN
--------------------------------------------------
Every failure here is contained and reported: a folder with no manifest, a
manifest that will not parse, a module that raises on import, a `register` that
throws. The assistant starts, everything else loads, and `aki inspect` says in
red which one is broken and why. A plugin someone wrote at midnight must not be
able to stop the morning summary.
"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths


MANIFEST = "PLUGIN.md"
ENTRY = "plugin.py"


def plugins_dir() -> Path:
    """Where installed plugins live.

    Beside the configuration rather than inside the package, for the same
    reason a forked skill and a custom panel live there: an upgrade replaces
    the package wholesale, and anything of the user's inside it would be
    destroyed by the next release.
    """
    return paths.app_dir() / "plugins"


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------

@dataclass
class Plugin:
    """One installed plugin, as declared and as it actually behaved."""

    name: str
    path: Path
    version: str = ""
    description: str = ""
    provides: tuple[str, ...] = ()
    entry: str = ENTRY
    # Filled in by `load_all`. Empty means it loaded cleanly.
    problem: str = ""
    registered: tuple[str, ...] = ()

    @property
    def contents(self) -> dict[str, int]:
        """What this package holds, counted on disk each time it is asked.

        A property rather than a stored field because a package is a folder a
        person can edit: caching the count at discovery would show yesterday's
        number to somebody who just dropped a skill in.
        """
        return contents(self.path)

    @property
    def loaded(self) -> bool:
        return not self.problem

    def describe(self) -> str:
        line = self.name
        if self.version:
            line += f" {self.version}"
        if self.description:
            line += f" — {self.description}"
        return line


def _frontmatter(text: str) -> tuple[dict, str]:
    """The YAML block at the top of a `PLUGIN.md`, and the prose after it.

    Hand-rolled rather than reaching for a parser, matching `library.py`: a
    manifest is three or four lines and the failure mode of a strict parser is
    an install that stops on a stray tab.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    block = text[3:end]
    body = text[end + 4:].lstrip("\n")

    try:
        import yaml

        data = yaml.safe_load(block) or {}
    except Exception:                                     # noqa: BLE001
        return {}, body
    return (data if isinstance(data, dict) else {}), body


def read_manifest(folder: Path) -> tuple[Plugin | None, str]:
    """One plugin folder, or None with a sentence saying why not."""
    manifest = folder / MANIFEST
    if not manifest.is_file():
        return None, (f"{folder.name}: no {MANIFEST}, so this folder is not a "
                      "plugin. A plugin needs one, naming it and what it adds.")
    try:
        text = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"{folder.name}: {MANIFEST} could not be read — {exc}"

    data, prose = _frontmatter(text)
    name = str(data.get("name") or folder.name).strip()
    if not name:
        return None, f"{folder.name}: {MANIFEST} declares no name."

    provides = data.get("provides") or ()
    if isinstance(provides, str):
        provides = [provides]
    if not isinstance(provides, (list, tuple)):
        provides = ()

    description = str(data.get("description") or "").strip()
    if not description:
        # The first line of the prose is a fair description when none was
        # declared -- better than showing a folder name with nothing beside it.
        description = next((line.strip() for line in prose.splitlines()
                            if line.strip() and not line.startswith("#")), "")

    return Plugin(
        name=name,
        path=folder,
        version=str(data.get("version") or "").strip(),
        description=description,
        provides=tuple(str(one).strip() for one in provides if str(one).strip()),
        entry=str(data.get("entry") or ENTRY).strip() or ENTRY,
    ), ""


CONTENT_KINDS = ("tools", "skills", "workflows", "panels")


def contents(folder: Path) -> dict[str, int]:
    """What kinds of thing a package folder actually holds, counted on disk.

    Declared counts would be a promise; these are the fact. A manifest that
    claims six skills and ships two should show two, because the number a
    person is shown before installing has to be the number they get.

    `tools` is the odd one: a tool is registered by `plugin.py` calling into a
    seam, so it is code rather than a folder, and its presence is the entry
    file rather than a directory.
    """
    out: dict[str, int] = {}
    for kind in ("skills", "workflows", "panels"):
        sub = folder / kind
        if sub.is_dir():
            n = sum(1 for child in sub.iterdir()
                    if not child.name.startswith((".", "_")))
            if n:
                out[kind] = n
    if (folder / ENTRY).is_file():
        out["tools"] = 1
    return out


def installed() -> tuple[list[Plugin], list[str]]:
    """Every plugin folder that declares itself, and every one that does not.

    A folder without a manifest is reported, not ignored: somebody who unzipped
    a plugin one level too deep should be told, rather than left wondering why
    nothing happened.
    """
    root = plugins_dir()
    if not root.is_dir():
        return [], []

    found: list[Plugin] = []
    problems: list[str] = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.name.startswith((".", "_")):
            continue
        plugin, problem = read_manifest(folder)
        if plugin is None:
            problems.append(problem)
        else:
            found.append(plugin)
    return found, problems


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_LOADED: list[Plugin] = []
_LOAD_PROBLEMS: list[str] = []
_HAVE_LOADED = False


def _import_entry(plugin: Plugin):
    """Import a plugin's entry module under a name that cannot collide.

    `importlib.util.spec_from_file_location` rather than adding the folder to
    `sys.path`: two plugins are entitled to both call their module `plugin.py`,
    and a shared path would make the second one silently get the first.
    """
    import importlib.util

    target = plugin.path / plugin.entry
    if not target.is_file():
        raise FileNotFoundError(
            f"{plugin.entry} is missing — a plugin needs it, with a "
            "`register(seams)` function inside.")

    spec = importlib.util.spec_from_file_location(
        f"aki_plugin_{plugin.name.replace('-', '_')}", target)
    if spec is None or spec.loader is None:              # pragma: no cover
        raise ImportError(f"{plugin.entry} could not be prepared for import.")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



class _SeamRecorder:
    """One seam, wrapped so a plugin's registrations can be attributed to it."""

    def __init__(self, registry, into: list) -> None:
        self._registry = registry
        self._into = into

    def register(self, provider) -> None:
        self._into.append(f"{self._registry.what}:{provider.name}")
        self._registry.register(provider)

    def __getattr__(self, name):
        return getattr(self._registry, name)


class _Recorder:
    """The `seams` a plugin's `register` is handed.

    WHY NOT JUST DIFF THE REGISTRIES BEFORE AND AFTER
    -------------------------------------------------
    That was the first version, and it was wrong the second time it ran. The
    dashboard reloads plugins when somebody opens the page, and by then the
    provider is already registered — so nothing looked new, and a working
    plugin was reported as "added nothing" beside its own working calendar.

    Recording at the moment of registration is exact rather than inferred, and
    it is also right in the case a diff can never see: a plugin that replaces
    a built-in provider of the same name.
    """

    def __init__(self, seams) -> None:
        self._seams = seams
        self.recorded: list[str] = []

    def seam(self, what: str):
        registry = self._seams.seam(what)
        if registry is None:
            return None
        return _SeamRecorder(registry, self.recorded)

    def __getattr__(self, name):
        return getattr(self._seams, name)


def load_all(force: bool = False) -> tuple[list[Plugin], list[str]]:
    """Import every installed plugin and let it register what it provides.

    Runs once per process unless forced. Returns what loaded and what did not,
    and never raises: a plugin that throws is a plugin that is reported.
    """
    global _HAVE_LOADED

    if _HAVE_LOADED and not force:
        return list(_LOADED), list(_LOAD_PROBLEMS)

    from . import seams

    # The seams a plugin registers into have to exist before it runs. This
    # imports them and nothing else -- calling `load_every_seam` here would
    # come straight back to this function.
    seams.import_seam_modules()

    _LOADED.clear()
    _LOAD_PROBLEMS.clear()

    found, problems = installed()
    _LOAD_PROBLEMS.extend(problems)

    for plugin in found:
        # A package that carries only skills, workflows or panels has nothing
        # to import and nothing to register, and it is not broken. Before the
        # package model was written down this fell through to `_import_entry`
        # and every such plugin was reported as missing its `plugin.py` on
        # every single load -- software calling a working thing broken.
        if not (plugin.path / plugin.entry).is_file():
            if not plugin.contents:
                # Still listed, not moved to `problems`: an installed thing
                # has to stay visible, and the state "installed and empty" is
                # its own answer to "why is nothing happening".
                plugin.problem = (
                    f"{plugin.entry} is missing, and there are no skills, "
                    "workflows or panels either — this package is empty.")
            _LOADED.append(plugin)
            continue

        recorder = _Recorder(seams)
        try:
            module = _import_entry(plugin)
            register = getattr(module, "register", None)
            if not callable(register):
                raise AttributeError(
                    f"{plugin.entry} has no `register(seams)` function. That "
                    "is the one thing a plugin has to provide.")
            register(recorder)
        except Exception as exc:                          # noqa: BLE001
            # Contained on purpose. See the module docstring: a plugin written
            # at midnight must not be able to stop the morning summary.
            plugin.problem = f"{type(exc).__name__}: {exc}"
            _LOAD_PROBLEMS.append(f"{plugin.name}: {plugin.problem}")
            _LOADED.append(plugin)
            continue

        plugin.registered = tuple(sorted(recorder.recorded))
        _LOADED.append(plugin)

    _HAVE_LOADED = True
    return list(_LOADED), list(_LOAD_PROBLEMS)


def forget_loaded() -> None:
    """Drop the once-per-process memo. For tests."""
    global _HAVE_LOADED

    _LOADED.clear()
    _LOAD_PROBLEMS.clear()
    _HAVE_LOADED = False


# ---------------------------------------------------------------------------
# Installing
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    """What `add` found before anything was copied anywhere."""

    plugin: Plugin | None
    source: Path
    # A temporary folder that must be cleaned up, when the source was a zip.
    scratch: Path | None = None
    problem: str = ""
    warnings: list[str] = field(default_factory=list)


def _looks_like_plugin(folder: Path) -> bool:
    return (folder / MANIFEST).is_file()


def _unwrap(folder: Path) -> Path:
    """Follow a zip that wrapped its contents in one extra folder.

    Everyone's zip does this, and refusing it would mean telling people their
    correct plugin is not a plugin.
    """
    if _looks_like_plugin(folder):
        return folder
    children = [one for one in folder.iterdir() if one.is_dir()]
    if len(children) == 1 and _looks_like_plugin(children[0]):
        return children[0]
    return folder


def examine(source: str | Path) -> Candidate:
    """Read a folder or zip and say what installing it would add.

    Nothing is copied. This is the half `add` shows before asking, because
    installing a plugin is trusting its author with everything the assistant
    can reach, and a person cannot consent to something they have not been
    shown.
    """
    import tempfile

    origin = Path(source).expanduser()
    if not origin.exists():
        return Candidate(None, origin, problem=f"There is nothing at {origin}.")

    scratch: Path | None = None
    folder = origin
    if origin.is_file():
        if origin.suffix.lower() != ".zip":
            return Candidate(None, origin, problem=(
                f"{origin.name} is a file, not a folder or a zip. A plugin is "
                "a folder with a PLUGIN.md in it."))
        scratch = Path(tempfile.mkdtemp(prefix="aki-plugin-"))
        try:
            with zipfile.ZipFile(origin) as archive:
                archive.extractall(scratch)
        except Exception as exc:                          # noqa: BLE001
            shutil.rmtree(scratch, ignore_errors=True)
            return Candidate(None, origin,
                             problem=f"{origin.name} could not be opened — {exc}")
        folder = _unwrap(scratch)

    plugin, problem = read_manifest(folder)
    if plugin is None:
        return Candidate(None, origin, scratch=scratch, problem=problem)

    warnings: list[str] = []
    if not (folder / plugin.entry).is_file() and not contents(folder):
        warnings.append(
            f"there is no {plugin.entry} and no skills, workflows or panels, "
            "so this will install and add nothing")
    if (plugins_dir() / plugin.name).exists():
        warnings.append(f"a plugin called '{plugin.name}' is already installed "
                        "and will be replaced")

    return Candidate(plugin, folder, scratch=scratch, warnings=warnings)


def consent_text(candidate: Candidate) -> str:
    """What a person is agreeing to. Deliberately blunt."""
    plugin = candidate.plugin
    assert plugin is not None

    lines = [f"  {plugin.describe()}"]
    held = plugin.contents
    if held:
        lines.append("  contains: "
                     + ", ".join(f"{n} {kind}" for kind, n in held.items()))
    if plugin.provides:
        lines.append(f"  adds: {', '.join(plugin.provides)}")
    lines.append(f"  from: {candidate.source}")
    for warning in candidate.warnings:
        lines.append(f"  ! {warning}")
    lines.append("")
    lines.append("  A plugin is code that runs as you, with your mail, your")
    lines.append("  calendars and your files in reach. There is no sandbox.")
    lines.append("  Install one only if you trust whoever wrote it.")
    return "\n".join(lines)


def install(candidate: Candidate) -> tuple[bool, str]:
    """Copy an examined candidate into place, replacing any earlier version."""
    plugin = candidate.plugin
    if plugin is None:                                    # pragma: no cover
        return False, candidate.problem or "Nothing to install."

    target = plugins_dir() / plugin.name
    try:
        plugins_dir().mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(candidate.source, target)
    except Exception as exc:                              # noqa: BLE001
        return False, f"Could not install {plugin.name} — {exc}"
    finally:
        cleanup(candidate)

    return True, (f"Installed {plugin.name} into {target}. "
                  "Run `inspect` to see what it added.")


def cleanup(candidate: Candidate) -> None:
    if candidate.scratch is not None:
        shutil.rmtree(candidate.scratch, ignore_errors=True)
        candidate.scratch = None


def remove(name: str) -> tuple[bool, str]:
    """Delete an installed plugin. The folder is the whole of it."""
    target = plugins_dir() / name
    if not target.is_dir():
        found, _ = installed()
        known = ", ".join(one.name for one in found)
        return False, (f"There is no plugin called '{name}'."
                       + (f" Installed: {known}." if known else ""))
    try:
        shutil.rmtree(target)
    except Exception as exc:                              # noqa: BLE001
        return False, f"Could not remove {name} — {exc}"
    return True, f"Removed {name}."


# ---------------------------------------------------------------------------
# For `inspect`
# ---------------------------------------------------------------------------

def report() -> dict[str, Any]:
    plugins, problems = load_all()
    return {
        "folder": str(plugins_dir()),
        "installed": [{
            "name": one.name,
            "version": one.version,
            "description": one.description,
            "registered": list(one.registered),
            "problem": one.problem,
        } for one in plugins],
        "problems": problems,
    }
