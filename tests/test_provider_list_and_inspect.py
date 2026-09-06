"""The `providers:` list, and the command that says what is actually loaded.

Two phases of the same idea. The list decides what loads; `inspect` is the
only honest way to find out whether it worked, because it reads the live
registries rather than reading the file back and repeating it.

The rules being held down here are the ones that are cheap to write and
expensive to get wrong months later:

* a seam the block says nothing about keeps everything it has, so a config
  written before any of this existed behaves exactly as it did;
* naming a seam **replaces** its list rather than adding to it;
* a name nothing answers to is a loud refusal, not a silent switch-off;
* and `inspect` still works when the block is the thing that is broken.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aki_agent import calendar_seam, channels, config as config_module
from aki_agent import inspect_report, paths, seams


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


@pytest.fixture(autouse=True)
def no_configured_list():
    """No test may leave a list behind on a module-level registry."""
    seams.clear_chosen()
    channels.reset_to_defaults()
    calendar_seam.reset_to_defaults()
    yield
    seams.clear_chosen()
    channels.reset_to_defaults()
    calendar_seam.reset_to_defaults()


def _config(**providers):
    return SimpleNamespace(providers=providers or {},
                           connections=SimpleNamespace(mail=(), calendars=(),
                                                       apis=()),
                           source_path="")


# ---------------------------------------------------------------------------
# Saying nothing
# ---------------------------------------------------------------------------

def test_a_config_with_no_providers_block_loads_everything():
    """The upgrade path. Every install that exists today has no such block,
    and every one of them has to behave on the next version exactly as it did
    on this one."""
    assert seams.apply(_config()) == []
    assert channels.registered_names() == ("file", "telegram")
    assert calendar_seam.registered_names() == ("google", "ics")


def test_a_seam_the_block_ignores_keeps_everything():
    """Naming one seam must not quietly narrow the others."""
    assert seams.apply(_config(channel=["file"])) == []

    assert channels.registered_names() == ("file",)
    assert calendar_seam.registered_names() == ("google", "ics")


# ---------------------------------------------------------------------------
# Replacing, not merging
# ---------------------------------------------------------------------------

def test_the_list_replaces_the_defaults_rather_than_adding_to_them():
    """DeepSeek's rule, and the one worth being strict about: an override
    whose effect cannot be read off the page defeats the page."""
    seams.apply(_config(channel=["file"]))

    assert channels.registered_names() == ("file",)
    assert channels.get("telegram") is None


def test_something_left_out_is_still_installed_and_says_so():
    """Filtered, not unregistered. `inspect` has to be able to tell a person
    they have Telegram and switched it off — "you do not have Telegram" would
    send them to install something they already own."""
    seams.apply(_config(channel=["file"]))
    registry = seams.seam("channel")

    assert [one.name for one in registry.registered()] == ["file", "telegram"]
    assert registry.switched_off() == ("telegram",)
    assert registry.chosen() == ("file",)


def test_putting_it_back_in_the_file_brings_it_back():
    """The dashboard reloads its configuration in a long-running process. A
    provider removed by one read has to survive being put back."""
    seams.apply(_config(channel=["file"]))
    assert channels.get("telegram") is None

    seams.apply(_config(channel=["file", "telegram"]))
    assert channels.get("telegram") is not None


# ---------------------------------------------------------------------------
# Loud, not silent
# ---------------------------------------------------------------------------

def test_a_misspelled_provider_is_refused_and_named():
    """`telegam` would otherwise turn the assistant's messages off and report
    nothing, to be discovered hours later as "why did it not tell me"."""
    problems = seams.apply(_config(channel=["telegam"]))

    assert len(problems) == 1
    assert "'telegam'" in problems[0]
    assert "file, telegram" in problems[0]


def test_the_typo_is_reported_once_and_points_at_the_right_fix():
    """A typo also empties the seam, and saying "remove the channel: line"
    would send a person to delete a line they meant to keep. One root cause,
    one instruction."""
    problems = seams.apply(_config(channel=["telegam"]))

    assert not any("Remove the" in one for one in problems)


def test_a_list_with_a_bad_name_in_it_is_discarded_rather_than_half_applied():
    """Obeying `channel: [telegam]` filters the seam down to a name nothing
    answers to, which leaves no channel at all and switches the assistant's
    messages off.

    The command line refuses to run on it. The dashboard is the process
    somebody uses to fix the file, so it has to keep working — and a
    half-applied list there is silent breakage. So the list is reported and
    thrown away, and the seam keeps everything it has.
    """
    seams.apply(_config(channel=["telegam"]))

    assert channels.registered_names() == ("file", "telegram")
    assert seams.seam("channel").chosen() is None


def test_switching_a_seam_off_entirely_is_reported():
    problems = seams.apply(_config(channel=[]))

    assert len(problems) == 1
    assert "switches off every channel" in problems[0]


def test_a_seam_that_does_not_exist_is_reported_with_the_ones_that_do():
    problems = seams.apply(_config(carrier_pigeon=["fast"]))

    assert len(problems) == 1
    assert "carrier_pigeon" in problems[0]
    assert "calendar, channel" in problems[0]


def test_every_command_refuses_while_the_block_is_wrong(monkeypatch):
    """`_load_config` is the one place every command gets its configuration,
    so it is the one place this has to be caught."""
    from aki_agent import cli

    monkeypatch.setattr(config_module, "load",
                        lambda *a, **k: _config(channel=["telegam"]))

    loaded, problem = cli._load_config()

    assert loaded is None
    assert "'telegam'" in problem


# ---------------------------------------------------------------------------
# The file itself
# ---------------------------------------------------------------------------

def test_the_block_survives_a_round_trip_through_the_file():
    written = config_module.Config.from_dict({
        "schema_version": config_module.SCHEMA_VERSION,
        "providers": {"channel": ["file"], "calendar": ["ics"]},
    })

    assert written.providers == {"channel": ("file",), "calendar": ("ics",)}
    assert written.to_dict()["providers"] == {"calendar": ["ics"],
                                              "channel": ["file"]}


def test_a_config_that_limits_nothing_does_not_grow_the_block():
    """Written only when it says something, so a file for someone who never
    limited a seam stays as short as it was."""
    plain = config_module.Config.from_dict(
        {"schema_version": config_module.SCHEMA_VERSION})

    assert "providers" not in plain.to_dict()


def test_a_malformed_block_does_not_stop_the_assistant_starting():
    """A stray `providers: yes` is a shape error, and shape errors are
    dropped. A *name* nobody answers to is the thing worth refusing over,
    and that check needs a list to look at first."""
    assert config_module.Config.from_dict({
        "schema_version": config_module.SCHEMA_VERSION,
        "providers": "yes",
    }).providers == {}

    # A single name where a list was expected is a typo worth forgiving.
    assert config_module.Config.from_dict({
        "schema_version": config_module.SCHEMA_VERSION,
        "providers": {"channel": "file"},
    }).providers == {"channel": ("file",)}


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------

def test_inspect_reports_every_seam_and_what_each_provider_can_do():
    report = inspect_report.gather(_config())

    names = [entry["seam"] for entry in report["seams"]]
    # Alphabetical, so a new seam lands wherever its name puts it. `account`
    # joined on 2026-08-28 (see accounts.py and docs/CONNECTING.md).
    assert names == ["account", "calendar", "channel", "guide"]

    calendars = next(entry for entry in report["seams"]
                     if entry["seam"] == "calendar")
    google = next(one for one in calendars["providers"]
                  if one["name"] == "google")
    assert google["capabilities"] == ["read", "write"]

    ics = next(one for one in calendars["providers"] if one["name"] == "ics")
    assert ics["capabilities"] == ["read"]


def test_inspect_reads_the_registries_rather_than_the_file():
    """The whole discipline. A provider registered in this process shows up
    even though no configuration has ever heard of it — which is what makes
    the report able to disagree with the file."""

    class Pigeon:
        name = "pigeon"

        def available(self):
            return True

    channels.register(Pigeon())
    report = inspect_report.gather(_config())

    channel = next(entry for entry in report["seams"]
                   if entry["seam"] == "channel")
    assert "pigeon" in [one["name"] for one in channel["providers"]]


def test_inspect_marks_something_installed_but_switched_off():
    report = inspect_report.gather(_config(channel=["file"]))

    channel = next(entry for entry in report["seams"]
                   if entry["seam"] == "channel")
    telegram = next(one for one in channel["providers"]
                    if one["name"] == "telegram")

    assert telegram["loaded"] is False
    assert channel["switched_off"] == ["telegram"]
    assert "switched off by your configuration" in inspect_report.render(report)


def test_inspect_still_works_when_the_block_is_the_broken_thing():
    """The one tool for diagnosing the providers block must not be a tool the
    block can switch off."""
    report = inspect_report.gather(_config(channel=["telegam"]))

    assert report["seams"]
    printed = inspect_report.render(report)
    assert "Problems with your configuration" in printed
    assert "'telegam'" in printed


def test_inspect_survives_having_no_configuration_at_all():
    """Before the setup interview has run, "what does this software carry" is
    still a question worth answering."""
    report = inspect_report.gather(None)

    assert [entry["seam"] for entry in report["seams"]] == ["account",
                                                            "calendar",
                                                            "channel",
                                                            "guide"]
    assert report["problems"] == []
    assert inspect_report.render(report)


def test_inspect_reads_a_provider_whichever_shape_it_answers_in():
    """`channels` answers `available()` with a bool; a calendar answers with
    `(usable, reason)`. Holding both here is the price of not forcing one
    protocol on seams that mean different things."""
    report = inspect_report.gather(_config())

    channel = next(entry for entry in report["seams"]
                   if entry["seam"] == "channel")
    file_channel = next(one for one in channel["providers"]
                        if one["name"] == "file")
    assert file_channel["usable"] is True
    assert file_channel["reason"] == ""

    calendars = next(entry for entry in report["seams"]
                     if entry["seam"] == "calendar")
    google = next(one for one in calendars["providers"]
                  if one["name"] == "google")
    assert google["usable"] is False
    assert "not connected" in google["reason"]


def test_a_provider_that_needs_the_configuration_is_given_it():
    """Found on the Surface, 2026-08-26.

    The first version called `available()` with nothing. `IcsFeeds` takes
    `config=None` and so did not complain — it simply answered as though
    nothing were subscribed. On the machine it was written on that was true.
    On a machine with two calendar subscriptions the same report said "no
    calendar subscriptions yet" two lines under "calendars 2".

    A report that contradicts itself is worse than no report, so this checks
    the configuration actually reaches the provider.
    """
    config = SimpleNamespace(
        providers={},
        connections=SimpleNamespace(
            mail=(), apis=(),
            calendars=(SimpleNamespace(name="Work", url=""),
                       SimpleNamespace(name="School", url=""))),
        source_path="")

    report = inspect_report.gather(config)

    calendars = next(entry for entry in report["seams"]
                     if entry["seam"] == "calendar")
    ics = next(one for one in calendars["providers"] if one["name"] == "ics")

    assert ics["usable"] is True
    assert ics["reason"] == ""
    assert len(report["connections"]["calendars"]) == 2


def test_asking_the_signature_beats_catching_the_type_error():
    """A provider that raises `TypeError` from inside `available()` must be
    reported as broken, not quietly re-called as though it took no
    configuration."""

    class Confusing:
        name = "confusing"

        def available(self):
            raise TypeError("something inside me is wrong")

    channels.register(Confusing())
    report = inspect_report.gather(_config())

    channel = next(entry for entry in report["seams"]
                   if entry["seam"] == "channel")
    confusing = next(one for one in channel["providers"]
                     if one["name"] == "confusing")
    assert confusing["usable"] is False
    assert "something inside me is wrong" in confusing["reason"]


def test_a_provider_that_throws_is_reported_rather_than_crashing_the_report():
    """One broken provider must not take out the command whose whole job is
    telling you which one is broken."""

    class Angry:
        name = "angry"

        def available(self):
            raise RuntimeError("the socket is on fire")

    channels.register(Angry())
    report = inspect_report.gather(_config())

    channel = next(entry for entry in report["seams"]
                   if entry["seam"] == "channel")
    angry = next(one for one in channel["providers"]
                 if one["name"] == "angry")
    assert angry["usable"] is False
    assert "on fire" in angry["reason"]


def test_inspect_never_prints_a_whole_mail_address():
    """Everything printed lands in a session transcript, which is written to
    disk and read back by a model later. `tools` refuses to print a key for
    the same reason."""
    config = SimpleNamespace(
        providers={},
        connections=SimpleNamespace(
            mail=(SimpleNamespace(address="anzon@example.com", label=""),),
            calendars=(), apis=()),
        source_path="")

    report = inspect_report.gather(config)

    assert report["connections"]["mail"] == ["example.com"]
    assert "anzon@example.com" not in inspect_report.render(report)


def test_the_command_returns_one_when_the_configuration_is_wrong(
        capsys, monkeypatch):
    """An exit code a script can act on, not just words on a screen."""
    from aki_agent import cli

    monkeypatch.setattr(config_module, "load",
                        lambda *a, **k: _config(channel=["telegam"]))

    assert cli.cmd_inspect(SimpleNamespace(json=False)) == 1
    assert "'telegam'" in capsys.readouterr().out


def test_the_command_offers_machine_readable_output(capsys, monkeypatch):
    """The dashboard needs the same facts without parsing prose."""
    import json

    from aki_agent import cli

    monkeypatch.setattr(config_module, "load", lambda *a, **k: _config())

    assert cli.cmd_inspect(SimpleNamespace(json=True)) == 0

    parsed = json.loads(capsys.readouterr().out)
    assert [entry["seam"] for entry in parsed["seams"]] == ["account",
                                                            "calendar",
                                                            "channel",
                                                            "guide"]
