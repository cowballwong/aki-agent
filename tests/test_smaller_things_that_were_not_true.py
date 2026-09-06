"""Group F: small things, each of which was a claim with nothing behind it.

None of these would stop the software. That is what they have in common, and
it is why they lasted: every one of them fails by looking fine.
"""

from __future__ import annotations

import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = PACKAGE_ROOT / "src" / "aki_agent" / "dashboard" / "templates"


# ---------------------------------------------------------------------------
# What travels onto a student's machine
# ---------------------------------------------------------------------------

def test_a_library_skill_does_not_bring_the_sync_clients_leftovers(tmp_path,
                                                                   monkeypatch):
    """Measured: `library/skills` held 93 SKILL.md files and 94 desktop.ini.

    So the loop that copies "anything alongside the SKILL.md -- checklists,
    templates" had never once copied anything a person wrote. It had only ever
    copied Google Drive's own folder metadata, onto students' machines, where
    it marks the folder with a custom icon pointing at an executable they do
    not have.
    """
    from aki_agent import library, skills_store

    monkeypatch.setattr(skills_store, "skills_dir",
                        lambda: tmp_path / ".claude" / "skills")

    source = tmp_path / "library" / "skills" / "pretend"
    source.mkdir(parents=True)
    # `name` is the key, so it is the folder name — see `read_item`.
    (source / "SKILL.md").write_text(
        "---\nname: pretend\ntitle: Pretend\n"
        "description: Use when testing.\n---\nbody\n",
        encoding="utf-8")
    (source / "checklist.md").write_text("real content\n", encoding="utf-8")
    (source / "desktop.ini").write_text("[.ShellClassInfo]\n", encoding="utf-8")
    (source / "Thumbs.db").write_bytes(b"\x00")

    monkeypatch.setattr(library, "library_dir", lambda: tmp_path / "library")

    ok, _ = library.activate("pretend")
    assert ok

    landed = tmp_path / ".claude" / "skills" / "pretend"
    assert (landed / "SKILL.md").exists()
    assert (landed / "checklist.md").exists(), "real sidecars must still come"
    assert not (landed / "desktop.ini").exists()
    assert not (landed / "Thumbs.db").exists()


def test_the_shipped_library_carries_no_clutter():
    """And the source folder itself is clean, so there is nothing to copy."""
    strays = [str(path.relative_to(PACKAGE_ROOT))
              for path in (PACKAGE_ROOT / "library").rglob("*")
              if path.is_file() and path.name in
              ("desktop.ini", "Thumbs.db", ".DS_Store")]
    assert not strays, f"{len(strays)} sync-client files in the library"


# ---------------------------------------------------------------------------
# Four skills that promised a warning nothing could deliver
# ---------------------------------------------------------------------------

def test_the_deadline_skills_do_not_claim_to_watch_the_calendar():
    """`deadline-watch:43`, under a heading called "What this never does",
    said "It tells the user, in time." Nothing scheduled it, so it could only
    ever tell them when asked — and somebody who believed the sentence would
    have found out on the day."""
    for name in ("deadline-watch", "tax-filing-calendar",
                 "court-deadline-diary", "stock-and-expiry"):
        # Whitespace flattened: the claim below spans a line break in the
        # file, and asserting on a phrase that happens not to wrap is
        # asserting on the width of somebody's editor.
        text = " ".join((PACKAGE_ROOT / "library" / "skills" / name /
                         "SKILL.md").read_text(encoding="utf-8").split())

        assert "It tells the user, in time." not in text
        assert "does not watch the calendar on its own" in text, (
            f"{name} does not say that it only runs when asked")
        # And it says how to make it genuine, rather than only withdrawing
        # the claim.
        assert "Schedule page" in text, f"{name} withdraws without offering"


# ---------------------------------------------------------------------------
# Dead code that cost something
# ---------------------------------------------------------------------------

def test_repairing_an_install_keeps_the_persona():
    """`cmd_repair` rebuilt LauncherOptions inline and recovered two of the
    three fields. `--agent` was simply not in it, so repairing an install --
    which is what somebody runs when something is already wrong -- rewrote
    the launcher without the persona. The assistant started as a plain
    session from then on, and the repair reported success."""
    source = (PACKAGE_ROOT / "src" / "aki_agent" / "cli.py").read_text(
        encoding="utf-8")
    # `_repoint` is where the launcher is rebuilt; `cmd_repair` calls it.
    repair = source[source.index("def _repoint("):]
    repair = repair[:repair.index("\ndef ", 1)]

    assert "launcher.choices_in(" in repair, (
        "cmd_repair reads the launcher back its own way again")
    assert '"--permission-mode auto" in' not in repair, (
        "the inline copy is still there")


def test_choices_in_recovers_every_field_it_is_used_for():
    """One read-back, in one place, that gains a line when a field is added.
    The inline copy could not gain that line, because nobody knew it existed.
    """
    from aki_agent import launcher

    everything = launcher.LauncherOptions(
        auto_mode=True, open_dashboard=True, assistant_agent="mira")
    written = launcher.windows_launcher(everything, Path("C:/anywhere"))

    kept = launcher.choices_in(written)
    assert kept == {"auto_mode": True, "open_dashboard": True,
                    "assistant_agent": "mira"}


def test_a_failing_credential_store_says_so_in_words(monkeypatch):
    """`SecretsUnavailable` was defined and never raised anywhere, so a store
    that refused a write reached a non-technical student as a raw
    `WinError 1312` -- in the middle of connecting their email, which is
    exactly the moment they are least able to read one."""
    import pytest

    from aki_agent import secrets

    class Refuses:
        @staticmethod
        def set_password(*_args):
            raise RuntimeError("WinError 1312")

    monkeypatch.setattr(secrets, "_keyring_or_none", lambda: Refuses)

    with pytest.raises(secrets.SecretsUnavailable) as raised:
        secrets.set_secret("mail:someone@example.com", "hunter2")

    said = str(raised.value)
    assert "Nothing has been saved" in said
    assert "Traceback" not in said


# ---------------------------------------------------------------------------
# Orphans
# ---------------------------------------------------------------------------

def test_the_duplicate_announce_route_is_gone():
    """The switch moved to Notifications on 2026-08-21, at the maintainer's request:
    The route survived the move with
    nothing posting to it.

    Worth a test because the instinct on finding an orphan in an audit is to
    wire it back up — which would put the control back on a page somebody
    deliberately took it off. `/notifications/assign` does the job, and does
    more of it: it sets the quiet mode as well as the flag.
    """
    source = (PACKAGE_ROOT / "src" / "aki_agent" / "dashboard" /
              "app.py").read_text(encoding="utf-8")

    assert '@app.route("/schedule/announce"' not in source
    assert '@app.route("/notifications/assign"' in source

    for page in TEMPLATES.glob("*.html"):
        assert "/schedule/announce" not in page.read_text(encoding="utf-8")


def test_the_duplicate_verdict_route_is_gone():
    """No form in any of the sixty templates named it, and it was a second
    way into `traces.record_verdict`, which `approvals.answer` already calls
    on the path a person actually takes. An endpoint with no caller is a POST
    that writes to the learning store and that nobody would look at."""
    source = (PACKAGE_ROOT / "src" / "aki_agent" / "dashboard" /
              "app.py").read_text(encoding="utf-8")
    assert '@app.route("/verdict"' not in source

    approvals = (PACKAGE_ROOT / "src" / "aki_agent" / "approvals.py").read_text(
        encoding="utf-8")
    assert "traces.record_verdict(" in approvals, (
        "the real path stopped recording verdicts")


def test_the_chat_page_is_gone_from_every_list_that_could_offer_it():
    """It used to be the one page in neither the rail nor the moved table.

    Removed outright on 2026-09-04 rather than relocated -- the maintainer took the
    chat panel out of the dashboard and talks to the assistant on Telegram
    only. A redirect would have said the feature lives somewhere else, and it
    does not live anywhere, so this asserts the absence instead.
    """
    from aki_agent.dashboard import navigation

    in_rail = {page.path for group in navigation.GROUPS
               for page in group.pages}
    assert "/chat" not in in_rail
    assert "/chat" not in navigation.MOVED

    source = (PACKAGE_ROOT / "src" / "aki_agent" / "dashboard"
              / "app.py").read_text(encoding="utf-8")
    assert '@app.route("/chat' not in source


def test_the_theme_note_can_actually_be_true():
    """`_theme.html` has always had `{% if note %}` and nothing ever passed
    one, so the branch could not fire. Choosing a theme redirects to a page
    that looks identical apart from one highlighted card — which, if you pick
    a theme close to the one you were on, reads as nothing having happened."""
    page = (TEMPLATES / "_theme.html").read_text(encoding="utf-8")
    assert "{% if note %}" in page

    source = (PACKAGE_ROOT / "src" / "aki_agent" / "dashboard" /
              "app.py").read_text(encoding="utf-8")
    view = source[source.index("def theme_page("):]
    view = view[:view.index("@app.route", 1)]
    assert "note=" in view, "the page that renders the note never passes one"

    chooser = source[source.index("def theme_choose("):]
    chooser = chooser[:chooser.index("@app.route", 1)]
    assert "note=" in chooser, "choosing a theme says nothing"


def test_three_classes_that_were_written_have_a_rule():
    """`muted`, `removes` and `wrapped` were in the markup with no rule
    anywhere — invisible in review, and in the browser it looks deliberate."""
    css = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    for name in ("muted", "removes", "wrapped"):
        # Built by concatenation rather than as an f-string. An `rf""` pattern
        # containing both a backslash escape and a replacement field produced
        # a doubled backslash here, so the regex never matched and the test
        # reported a missing rule that was in fact present.
        pattern = re.compile(r"\." + name + r"\b[^{;]*\{")
        assert pattern.search(css), (
            f".{name} is used in the markup and styled nowhere")


# ---------------------------------------------------------------------------
# Skills must call commands, not paste Python into a shell
# ---------------------------------------------------------------------------

def test_no_skill_pastes_python_into_a_shell():
    """`connect-telegram` used `python -c "from aki_agent import ..."` six
    times. That `python` is whichever the shell resolves, not the assistant's
    environment, so every one died with ModuleNotFoundError mid-conversation.

    The path is not the only reason. A skill that pastes Python into a shell
    is a skill that can be talked into pasting different Python; a subcommand
    takes an argument and does one thing.
    """
    offenders = []
    for skill in sorted((PACKAGE_ROOT / "skills").glob("*/SKILL.md")):
        for line in skill.read_text(encoding="utf-8").splitlines():
            if "python -c" in line:
                offenders.append(f"{skill.parent.name}: {line.strip()[:70]}")
    assert not offenders, "\n".join(offenders)


def test_the_command_the_telegram_skill_now_calls_exists():
    """Replacing an inline snippet with a command that does not exist would
    trade a visible failure for a confusing one."""
    from aki_agent import cli

    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is None:
        source = (PACKAGE_ROOT / "src" / "aki_agent" / "cli.py").read_text(
            encoding="utf-8")
        assert '"connect-telegram"' in source
        assert "def cmd_connect_telegram(" in source

    skill = (PACKAGE_ROOT / "skills" / "connect-telegram" /
             "SKILL.md").read_text(encoding="utf-8")
    for flag in ("--describe", "--token", "--allow"):
        assert f"connect-telegram {flag}" in skill


def test_a_missing_library_is_reported_rather_than_shown_as_empty(monkeypatch):
    """`pyproject.toml` ships only `src/`, so a plain `pip install .` leaves
    the library out. `catalogue()` then globs a folder that is not there, gets
    `[]`, and the page renders as "nothing here" with no error anywhere."""
    from aki_agent import doctor, library

    assert doctor.check_the_library_is_there().ok

    monkeypatch.setattr(library, "library_dir",
                        lambda: Path("/nowhere-at-all"))

    check = doctor.check_the_library_is_there()
    assert not check.ok
    assert "nowhere-at-all" in check.detail
    assert "show nothing at all" in check.fix
