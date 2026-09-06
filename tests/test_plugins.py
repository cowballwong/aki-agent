"""Third-party plugins: a folder somebody else wrote, doing real work.

The promise ( — not
"a seam I can edit from inside the package", but a folder that arrives from
outside, is installed by a command, and adds a provider the built-in code has
never heard of.

The centrepiece is `test_a_plugin_from_outside_adds_a_working_calendar`: it
writes a plugin to a temporary folder, installs it through the ordinary
command, and then reads its events through `agenda` — the command that knows
nothing about plugins. If that passes, the system is real rather than
plumbing.

The rest of this file is about the two things that make such a system safe to
have: nothing installs without an explicit yes, and no plugin can stop the
assistant starting.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aki_agent import calendar_seam, channels, paths, plugins, seams


GOOD_PLUGIN = '''
class Pretend:
    name = "pretend"

    def available(self, config=None):
        return True, ""

    def capabilities(self):
        return frozenset({"read"})

    def read(self, limit=25, config=None, upcoming_only=True):
        import datetime as dt

        from aki_agent import calendar_seam

        return [calendar_seam.Entry(
            summary="From a plugin",
            start=dt.datetime(2026, 12, 1, 14, 0),
            source="Pretend",
        )], []


def register(seams):
    seams.seam("calendar").register(Pretend())
'''

MANIFEST = """---
name: pretend-calendar
version: 1.2.3
description: A calendar that exists only in a test
provides: [calendar]
---

Prose a person would read.
"""


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


@pytest.fixture(autouse=True)
def clean_state():
    """Plugins register into module-level registries and load once per process.

    Both have to be reset around every test, or the first one to install
    something silently changes every test after it.
    """
    plugins.forget_loaded()
    channels.reset_to_defaults()
    calendar_seam.reset_to_defaults()
    seams.clear_chosen()
    yield
    plugins.forget_loaded()
    channels.reset_to_defaults()
    calendar_seam.reset_to_defaults()
    seams.clear_chosen()


def _write_plugin(folder, manifest=MANIFEST, code=GOOD_PLUGIN, entry="plugin.py"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "PLUGIN.md").write_text(manifest, encoding="utf-8")
    if code is not None:
        (folder / entry).write_text(code, encoding="utf-8")
    return folder


def _args(action, name="", yes=False):
    return SimpleNamespace(action=action, name=str(name), yes=yes)


# ---------------------------------------------------------------------------
# The promise
# ---------------------------------------------------------------------------

def test_a_plugin_from_outside_adds_a_working_calendar(tmp_path, capsys,
                                                       monkeypatch):
    """The acceptance test for the whole thing.

    A folder is written somewhere unrelated, installed through the command,
    and its events come out of `agenda` — which has never heard of plugins,
    and was not edited to make this work.
    """
    from aki_agent import cli

    source = _write_plugin(tmp_path / "elsewhere" / "pretend-calendar")

    assert cli.cmd_plugin(_args("add", source, yes=True)) == 0
    capsys.readouterr()

    # A fresh look, exactly as the next command in a new process would take.
    plugins.forget_loaded()
    seams.load_every_seam()

    assert "pretend" in calendar_seam.registered_names()

    monkeypatch.setattr(cli, "_load_config", lambda: (
        SimpleNamespace(connections=SimpleNamespace(calendars=())), ""))
    assert cli.cmd_agenda(SimpleNamespace(limit=5)) == 0

    printed = capsys.readouterr().out
    assert "From a plugin" in printed
    assert "Pretend:" in printed


def test_loading_plugins_first_still_gives_them_their_seams(tmp_path):
    """Found while recording the demo, by running `plugin list`.

    That command loads plugins directly rather than through
    `load_every_seam`. The plugin asked for `seam("calendar")`, nothing had
    imported `calendar_seam` in that path, and it got `None` — so a working
    plugin reported `AttributeError: 'NoneType' object has no attribute
    'register'` and read as broken. `agenda` and `inspect` were fine, which
    is what made it look like the plugin's fault.
    """
    _write_plugin(plugins.plugins_dir() / "pretend-calendar")

    found, problems = plugins.load_all(force=True)

    assert problems == []
    assert found[0].problem == ""
    assert found[0].registered == ("calendar:pretend",)


def test_reloading_still_reports_what_a_plugin_added(tmp_path):
    """Found on the dashboard, which reloads plugins when the page opens.

    The first version worked out what a plugin added by diffing the
    registries before and after. The second time it ran the provider was
    already registered, so nothing looked new — and a working plugin was
    reported as "added nothing" on the page, beside its own working calendar.

    Recording at the moment of registration is exact rather than inferred.
    """
    _write_plugin(plugins.plugins_dir() / "pretend-calendar")

    first, _ = plugins.load_all(force=True)
    second, _ = plugins.load_all(force=True)

    assert first[0].registered == ("calendar:pretend",)
    assert second[0].registered == ("calendar:pretend",)


def test_a_plugin_that_replaces_a_built_in_is_still_attributed_to_it(tmp_path):
    """A diff could never see this one: the name was already there."""
    _write_plugin(
        plugins.plugins_dir() / "shadow",
        manifest=MANIFEST.replace("pretend-calendar", "shadow"),
        code=GOOD_PLUGIN.replace('name = "pretend"', 'name = "ics"'))

    found, _ = plugins.load_all(force=True)

    assert found[0].registered == ("calendar:ics",)


def test_a_plugin_provider_is_indistinguishable_from_a_built_in_one(tmp_path):
    """Nothing downstream may be able to tell them apart — that is what makes
    the seam worth having rather than a lookup table."""
    _write_plugin(plugins.plugins_dir() / "pretend-calendar")
    seams.load_every_seam()

    registry = seams.seam("calendar")
    assert sorted(registry.names()) == ["google", "ics", "pretend"]

    provider = registry.get("pretend")
    assert provider.capabilities() == frozenset({"read"})


def test_a_plugin_provider_can_be_switched_off_from_the_configuration(tmp_path):
    """The `providers:` list does not care where a provider came from."""
    _write_plugin(plugins.plugins_dir() / "pretend-calendar")
    seams.load_every_seam()

    problems = seams.apply(SimpleNamespace(providers={"calendar": ["ics"]}))

    assert problems == []
    assert calendar_seam.registered_names() == ("ics",)
    assert seams.seam("calendar").switched_off() == ("google", "pretend")


# ---------------------------------------------------------------------------
# Nothing installs without a yes
# ---------------------------------------------------------------------------

def test_add_without_yes_shows_what_it_found_and_installs_nothing(tmp_path,
                                                                  capsys):
    from aki_agent import cli

    source = _write_plugin(tmp_path / "incoming" / "pretend-calendar")

    assert cli.cmd_plugin(_args("add", source)) == 0

    printed = capsys.readouterr().out
    assert "pretend-calendar 1.2.3" in printed
    assert "Nothing was installed" in printed
    assert not (plugins.plugins_dir() / "pretend-calendar").exists()


def test_the_consent_text_says_plainly_that_there_is_no_sandbox(tmp_path):
    """DeepSeek says of its own dynamic plugins that the sandbox "is not a
    security boundary… treat this toolset like bash access". There is not even
    a sandbox here, so the honesty has to be louder, not quieter."""
    source = _write_plugin(tmp_path / "incoming" / "pretend-calendar")
    candidate = plugins.examine(source)

    said = plugins.consent_text(candidate)
    assert "no sandbox" in said
    assert "runs as you" in said
    assert "trust whoever wrote it" in said


def test_replacing_an_installed_plugin_is_warned_about(tmp_path):
    _write_plugin(plugins.plugins_dir() / "pretend-calendar")
    source = _write_plugin(tmp_path / "newer" / "pretend-calendar")

    candidate = plugins.examine(source)

    assert any("already installed" in one for one in candidate.warnings)


def test_a_zip_installs_and_its_wrapper_folder_is_seen_through(tmp_path):
    """Every zip wraps its contents in one extra folder. Refusing that would
    mean telling people their correct plugin is not a plugin."""
    import zipfile

    source = _write_plugin(tmp_path / "build" / "pretend-calendar")
    archive = tmp_path / "pretend-calendar.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in source.rglob("*"):
            zipped.write(path, f"pretend-calendar/{path.name}")

    candidate = plugins.examine(archive)
    assert candidate.plugin is not None
    assert candidate.plugin.name == "pretend-calendar"

    ok, message = plugins.install(candidate)
    assert ok, message
    assert (plugins.plugins_dir() / "pretend-calendar" / "plugin.py").is_file()


def test_removing_one_deletes_the_folder_and_nothing_else(tmp_path):
    _write_plugin(plugins.plugins_dir() / "pretend-calendar")
    _write_plugin(plugins.plugins_dir() / "another",
                  manifest=MANIFEST.replace("pretend-calendar", "another"))

    ok, message = plugins.remove("pretend-calendar")

    assert ok
    assert "Removed" in message
    assert not (plugins.plugins_dir() / "pretend-calendar").exists()
    assert (plugins.plugins_dir() / "another").exists()


def test_removing_one_that_is_not_there_lists_the_ones_that_are(tmp_path):
    _write_plugin(plugins.plugins_dir() / "pretend-calendar")

    ok, message = plugins.remove("typo")

    assert ok is False
    assert "no plugin called 'typo'" in message
    assert "pretend-calendar" in message


# ---------------------------------------------------------------------------
# Nothing a plugin does may stop the assistant
# ---------------------------------------------------------------------------

def test_a_plugin_that_throws_on_import_is_reported_not_raised(tmp_path):
    """A plugin somebody wrote at midnight must not be able to stop the
    morning summary."""
    _write_plugin(plugins.plugins_dir() / "angry",
                  manifest=MANIFEST.replace("pretend-calendar", "angry"),
                  code="raise RuntimeError('I fell over on import')\n")

    found, problems = plugins.load_all(force=True)

    assert [one.name for one in found] == ["angry"]
    assert found[0].loaded is False
    assert "I fell over on import" in found[0].problem
    assert any("I fell over on import" in one for one in problems)


def test_one_broken_plugin_does_not_stop_a_good_one_loading(tmp_path):
    _write_plugin(plugins.plugins_dir() / "angry",
                  manifest=MANIFEST.replace("pretend-calendar", "angry"),
                  code="raise RuntimeError('nope')\n")
    _write_plugin(plugins.plugins_dir() / "pretend-calendar")

    seams.load_every_seam()

    assert "pretend" in calendar_seam.registered_names()


def test_a_plugin_with_no_register_function_says_which_thing_is_missing(tmp_path):
    _write_plugin(plugins.plugins_dir() / "pretend-calendar",
                  code="VALUE = 1\n")

    found, _problems = plugins.load_all(force=True)

    assert "register(seams)" in found[0].problem


def test_a_plugin_with_no_entry_file_says_so_rather_than_importing_nothing(
        tmp_path):
    _write_plugin(plugins.plugins_dir() / "pretend-calendar", code=None)

    found, _problems = plugins.load_all(force=True)

    assert "plugin.py is missing" in found[0].problem


def test_a_package_carrying_only_skills_is_not_called_broken(tmp_path):
    """The bug the package model exposed.

    Before `docs/PACKAGES.md` was written the code knew only about tools, so a
    plugin that carried skills and no `plugin.py` was reported as broken on
    every single load -- software calling a working thing broken.
    """
    folder = plugins.plugins_dir() / "pretend-calendar"
    _write_plugin(folder, code=None)
    (folder / "skills" / "measure-a-site").mkdir(parents=True)
    (folder / "skills" / "measure-a-site" / "SKILL.md").write_text(
        "---\nname: measure-a-site\n---\nPace it out.\n", encoding="utf-8")

    found, _problems = plugins.load_all(force=True)

    assert found[0].problem == ""
    assert found[0].contents == {"skills": 1}


def test_a_package_reports_what_it_holds_counted_from_disk(tmp_path):
    """Counted, not declared: the number shown before installing has to be
    the number you get, so a manifest cannot overpromise."""
    folder = plugins.plugins_dir() / "pretend-calendar"
    _write_plugin(folder)
    (folder / "workflows" / "a-job").mkdir(parents=True)
    (folder / "workflows" / "a-job" / "WORKFLOW.md").write_text(
        "---\nname: a-job\n---\n", encoding="utf-8")
    (folder / "panels").mkdir()
    (folder / "panels" / "one.md").write_text("x\n", encoding="utf-8")

    held = plugins.contents(folder)

    assert held == {"workflows": 1, "panels": 1, "tools": 1}


def test_a_folder_with_no_manifest_is_reported_rather_than_ignored(tmp_path):
    """Somebody who unzipped one level too deep should be told, not left
    wondering why nothing happened."""
    (plugins.plugins_dir() / "loose").mkdir(parents=True)
    (plugins.plugins_dir() / "loose" / "plugin.py").write_text("x = 1\n",
                                                               encoding="utf-8")

    _found, problems = plugins.load_all(force=True)

    assert any("no PLUGIN.md" in one for one in problems)


def test_two_plugins_may_both_call_their_module_plugin_py(tmp_path):
    """They are entitled to. A shared `sys.path` would make the second one
    silently get the first one's module."""
    _write_plugin(plugins.plugins_dir() / "first")
    _write_plugin(
        plugins.plugins_dir() / "second",
        manifest=MANIFEST.replace("pretend-calendar", "second"),
        code=GOOD_PLUGIN.replace('name = "pretend"', 'name = "second-one"'))

    seams.load_every_seam()

    names = calendar_seam.registered_names()
    assert "pretend" in names
    assert "second-one" in names


# ---------------------------------------------------------------------------
# Seeing it
# ---------------------------------------------------------------------------

def test_inspect_lists_a_plugin_and_what_it_registered(tmp_path):
    from aki_agent import inspect_report

    _write_plugin(plugins.plugins_dir() / "pretend-calendar")

    report = inspect_report.gather(None)
    entry = report["plugins"]["installed"][0]

    assert entry["name"] == "pretend-calendar"
    assert entry["version"] == "1.2.3"
    assert entry["registered"] == ["calendar:pretend"]
    assert entry["problem"] == ""

    printed = inspect_report.render(report)
    assert "pretend-calendar 1.2.3 → calendar:pretend" in printed


def test_inspect_shows_a_broken_plugin_as_installed_and_broken(tmp_path):
    """Reported beside the seams, not inside them: a plugin that failed to
    load registers nothing, so a per-seam listing would show it nowhere — and
    "installed but broken" is exactly the state this command is for."""
    from aki_agent import inspect_report

    _write_plugin(plugins.plugins_dir() / "angry",
                  manifest=MANIFEST.replace("pretend-calendar", "angry"),
                  code="raise RuntimeError('nope')\n")

    printed = inspect_report.render(inspect_report.gather(None))

    assert "! angry" in printed
    assert "nope" in printed


def test_the_example_folder_actually_travels_with_a_release():
    """Found by installing 0.36.0 on the Surface and having the command fail.

    The example was in the zip and not in the engine, because `engine.COPIED`
    decides which top-level folders an upgrade carries and nothing had added
    `examples` to it. That docstring already records this exact failure once
    before — `library` was missing from a 0.5.0 manifest and a hundred files
    quietly did not arrive. Doctor passed then too.
    """
    from aki_agent import engine

    assert "examples" in engine.COPIED


def test_the_shipped_example_plugin_is_a_valid_plugin():
    """`examples/plugins/local-ics-calendar` is what somebody copies to start.
    If it stops parsing, the first thing anybody tries stops working."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    folder = root / "examples" / "plugins" / "local-ics-calendar"

    plugin, problem = plugins.read_manifest(folder)

    assert plugin is not None, problem
    assert plugin.name == "local-ics-calendar"
    assert plugin.provides == ("calendar",)
    assert (folder / plugin.entry).is_file()
