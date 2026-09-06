"""Which of the three installs is this, actually?

WHY THE SOFTWARE ANSWERS THIS AND NOT THE USER
-----------------------------------------------
Someone who has just downloaded a zip does not know whether they are doing a
first install, an update, or joining this to an assistant they already have.
They will say "install this", and an assistant that takes that literally can
do real damage: run a first-time setup over a working configuration, or add a
second assistant beside one the person already relies on and leave them with
two.

"Joining", not "merging". The word "merge" was used here and in the question
this module asks until 2026-09-06, and it hid a defect for as long as it was
there: it names an operation without naming a direction, so the two opposite
things somebody can do -- bring their assistant into this one, or add this one
to theirs -- read as the same offer. See the note beside `EXISTING_AGENT`.

The machine, on the other hand, can tell. The evidence is all on disk. So this
module looks, reports what it found, and names the situation — and then stops,
because the last word belongs to the person.

WHAT IT WILL NOT DO
-------------------
It does not act, and it never guesses silently. Every verdict comes with the
evidence that produced it, in a form a person can check: "your configuration
file exists, here is its path". A confident wrong answer here costs someone
their setup, so the honest output when the signs are mixed is to say they are
mixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from . import paths

FRESH = "fresh"
NOT_SET_UP = "installed-not-set-up"
UPDATE = "update"
ALREADY = "already-current"
EXISTING_AGENT = "existing-assistant"


@dataclass
class Situation:
    kind: str
    headline: str
    evidence: list[str] = dataclass_field(default_factory=list)
    do_next: str = ""
    ask: str = ""

    def as_text(self) -> str:
        lines = [self.headline, ""]
        if self.evidence:
            lines.append("What I found on this machine:")
            lines += [f"  - {line}" for line in self.evidence]
            lines.append("")
        if self.do_next:
            lines += ["What this means:", f"  {self.do_next}", ""]
        if self.ask:
            lines += ["Before anything happens, ask:", f"  {self.ask}"]
        return "\n".join(lines)


def _upgrade_command(source: Path) -> str:
    """The exact upgrade command for this copy, spelled out.

    Spelled out rather than described, because a described command gets
    approximated and an approximated one silently does less.
    """
    from . import engine

    try:
        return (engine.how_to_run("aki_agent.cli", "upgrade")
                + f' --from "{source}" --yes')
    except Exception:                                     # noqa: BLE001
        return f'aki_agent.cli upgrade --from "{source}" --yes'


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _plugin_installed() -> bool:
    """Is this package installed as a plugin, as opposed to just unzipped?"""
    record = (paths.home() / ".claude" / "plugins"
              / "installed_plugins.json")
    if not record.exists():
        return False
    try:
        return "aki-agent" in record.read_text(encoding="utf-8",
                                               errors="replace")
    except OSError:
        return False


def _signs_of_another_assistant() -> list[str]:
    """Evidence that this person already runs an assistant of their own.

    Reported, never acted on. Each of these is ordinary on a developer's
    machine, so any one of them alone means little — which is precisely why
    they are shown to the user rather than used to decide.
    """
    found: list[str] = []

    skills = paths.home() / ".claude" / "skills"
    if skills.exists():
        own = [entry for entry in skills.glob("*/SKILL.md")]
        if own:
            found.append(f"{len(own)} skill(s) of your own in {skills}")

    settings = paths.home() / ".claude" / "settings.json"
    if settings.exists():
        try:
            if "hooks" in settings.read_text(encoding="utf-8",
                                             errors="replace"):
                found.append("hooks configured in your Claude Code settings")
        except OSError:
            pass

    here = Path.cwd() / "CLAUDE.md"
    if here.exists():
        found.append(f"instructions of your own at {here}")

    return found


def detect() -> Situation:
    """Look, and name the situation. Never changes anything."""
    from . import schedule

    config = paths.config_file()
    package = _package_root()

    if config.exists():
        current, was = schedule.install_root_is_current()
        if not current:
            return Situation(
                UPDATE,
                "This looks like an UPDATE of an assistant already running "
                "here.",
                evidence=[
                    f"your configuration already exists: {config}",
                    f"the scheduled work was set up against {was}",
                    f"this copy of the package is at {package}",
                ],
                # ONE command, and it is the command that exists.
                #
                # This used to describe the manual route -- install the
                # plugin, then `repair --yes` -- which is what `upgrade` does
                # as two of its eight steps. Following the description
                # skipped the rest: staging the new engine so the old one
                # survives for a rollback, closing the dashboard before
                # replacing the folder it runs from, writing the upgrade log,
                # and (since 0.31.0) saying which files the person had edited
                # before replacing them.
                #
                # Both this report and INSTALL.md said the old thing, so an
                # assistant reading either did the update the hard way and
                # lost the safety net without knowing it was there.
                do_next=(
                    "Run the upgrade. It replaces the program, keeps your "
                    "configuration, memory and work untouched, re-points the "
                    "scheduled tasks at the new copy, and keeps the previous "
                    "version so it can be put back: "
                    + _upgrade_command(package)),
                ask=("\"You already have an assistant set up here. Shall I "
                     "update it and keep everything as it is?\""))

        return Situation(
            ALREADY,
            "An assistant is already set up here, from this same copy of the "
            "package.",
            evidence=[f"your configuration: {config}",
                      f"this package: {package}"],
            do_next=("There is nothing to install. If something is wrong, run "
                     "the health check; to change an answer you gave during "
                     "setup, run setup again."),
            ask=("\"Everything is already installed. Did you want to change "
                 "a setting, or fix something that is not working?\""))

    if _plugin_installed():
        return Situation(
            NOT_SET_UP,
            "The plugin is installed, but the setup interview has not been "
            "run yet.",
            evidence=["the plugin is registered with Claude Code",
                      f"there is no configuration at {paths.config_file()}"],
            do_next="Run the setup interview. Nothing else is needed first.",
            ask=("\"Shall I run the setup now? It takes ten to twenty "
                 "minutes and it is a conversation, not a form.\""))

    others = _signs_of_another_assistant()
    if others:
        return Situation(
            EXISTING_AGENT,
            "This looks like a FIRST install on a machine that already has an "
            "assistant of your own.",
            evidence=others + [f"no configuration for this package yet: "
                               f"{paths.config_file()}"],
            # THREE OPTIONS, AND WHY "MERGE" WAS THE WRONG WORD (2026-09-06)
            # ---------------------------------------------------------------
            # `import-my-agent` was built to do the thing wanted here --
            # take the memory, the scheduled work and the skills out of an
            # assistant somebody already has and bring them INTO this one --
            # and then met an install that never offered it. What it offered
            # was `integrate`, which runs the other way: their assistant stays
            # the base and pieces of this one are added to it.
            #
            # Both are real and both ship as skills. The defect was that this
            # question named only one of them and called it "merge", a word
            # that carries no direction at all. He read it as the direction he
            # had asked for and was shown the opposite. A question about which
            # way things move must not be asked in a word that does not say.
            #
            # So: three options, each named by where things END UP, and the
            # word "merge" retired from this question entirely.
            do_next=(
                "There are three honest options and the difference between "
                "them is WHICH ASSISTANT ENDS UP AS THE MAIN ONE.\n"
                "  (a) Side by side — install normally. Nothing of yours is "
                "touched, but you have two assistants with two memories that "
                "never meet.\n"
                "  (b) This one becomes the main assistant, and what is in "
                "yours is brought across into it: notes, instructions, "
                "settings, scheduled work. Their own folder is left exactly "
                "as it is. Use the `import-my-agent` skill.\n"
                "  (c) Their assistant stays the main one, and capabilities "
                "from this package are added to it, one at a time and "
                "additively. Use the `integrate` skill; INTEGRATE.md "
                "describes it.\n"
                "Do not answer this from the shape of the question. Ask, and "
                "read the direction back to them before doing anything."),
            ask=("\"You already have an assistant of your own. Three ways to "
                 "go: keep them separate; make THIS one your main assistant "
                 "and bring your existing agent's memory and tasks into it; "
                 "or keep YOUR agent as the main one and add pieces of this "
                 "one to it. Which?\""))

    return Situation(
        FRESH,
        "This is a FIRST install on a machine with nothing set up yet.",
        evidence=[f"no configuration at {paths.config_file()}",
                  "the plugin is not registered with Claude Code yet"],
        do_next=("Add this folder as a plugin marketplace, install the "
                 "plugin, then run the setup interview. Afterwards the "
                 "downloaded folder can be deleted — it is an installer, not "
                 "the assistant."),
        ask=("\"Shall I install it and then walk you through the setup?\""))
