"""The dashboard's control surface, and the guard that makes it safe.

A dashboard that can only display things is a safe dashboard. This one can
create scheduled tasks, write skill files and add documents -- which is what
makes it useful and what makes the guard load-bearing rather than decorative.
"""

from __future__ import annotations

import re

from pathlib import Path

import pytest

from aki_agent import knowledge, paths, schedule, skills_store
from aki_agent.dashboard import app as dashboard_app
from aki_agent.dashboard import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "configs" / "examples" / "architecture.yaml"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


@pytest.fixture
def browser(tmp_path):
    # A COPY, never the example itself. `/settings/save` and
    # `/notifications/quiet` write back to whatever path the app was built
    # with, and the autouse isolation above only moves `paths.home()` -- it
    # says nothing about the config file. Pointed at the repo's own example,
    # a saving test edits a file that ships to students. It already had:
    # `notifications.quiet_hours` in `architecture.yaml` is `['23:00', 06:30]`,
    # the unquoted second half giving away YAML written by a machine -- the
    # residue of this very test, from back when the save worked.
    config_copy = tmp_path / "architecture.yaml"
    config_copy.write_bytes(CONFIG_A.read_bytes())
    app = create_app(config_copy)
    app.config["TESTING"] = True
    with app.test_client() as testing_client:
        yield testing_client


def token() -> str:
    return dashboard_app.SESSION_TOKEN


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

def test_a_change_without_the_token_is_refused(browser):
    """Cross-site request forgery is the real threat to a localhost app.

    "It only listens on 127.0.0.1" protects against the network. It does not
    protect against the browser: any page the user visits can POST to
    localhost, and does not need to read the response to do damage.
    """
    response = browser.post("/skills/save", data={
        "name": "Sneaky", "description": "x", "body": "y"})

    assert response.status_code == 403
    assert skills_store.read_all() == []


def test_a_change_with_a_wrong_token_is_refused(browser):
    response = browser.post("/skills/save", data={
        "token": "not-the-right-token",
        "name": "Sneaky", "description": "x", "body": "y"})

    assert response.status_code == 403
    assert skills_store.read_all() == []


def test_a_change_from_a_foreign_origin_is_refused(browser):
    response = browser.post(
        "/skills/save",
        data={"token": token(), "name": "Sneaky", "description": "x",
              "body": "y"},
        headers={"Origin": "https://somewhere-else.example"},
    )

    assert response.status_code == 403
    assert skills_store.read_all() == []


def test_reading_needs_no_token(browser):
    """Only changes are guarded. Reading is not, and does not need to be.

    Followed to the end since 2026-09-05: `/skills` is a redirect into the
    Tools tab now, and a 302 would satisfy "not 403" without proving the
    page it points at is readable either.
    """
    for url in ("/", "/skills", "/knowledge", "/schedule"):
        answer = browser.get(url, follow_redirects=True)
        assert answer.status_code == 200, url


def test_the_token_is_not_a_fixed_string():
    """A token baked into the source would be no protection at all."""
    assert len(dashboard_app.SESSION_TOKEN) >= 20
    source = Path(dashboard_app.__file__).read_text(encoding="utf-8")
    assert dashboard_app.SESSION_TOKEN not in source


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def test_a_skill_can_be_created_and_appears(browser):
    response = browser.post("/skills/save", data={
        "token": token(),
        "name": "Weekly update",
        "description": "Use when I ask for my weekly update or Monday report.",
        "body": "Do the thing.",
    }, follow_redirects=True)

    assert response.status_code == 200
    saved = skills_store.read_all()
    assert len(saved) == 1
    assert saved[0].name == "Weekly update"
    assert "Weekly update" in response.get_data(as_text=True)


def test_a_skill_lands_where_claude_code_actually_reads_it(tmp_path, browser):
    """The bug this test exists for: saved, listed, and never loaded.

    The first version wrote skills to `~/.aki-agent/skills/`, which is
    tidier and completely useless — Claude Code reads `~/.claude/skills/`.
    A user could write a skill, see it on the dashboard, and their assistant
    would never once load it. Nothing errored; the only symptom was absence.

    The earlier test asserted only that the file was outside the package,
    which stayed true while the skill was inert. Asserting the *effect*, not
    the location, is what catches this class of bug.
    """
    browser.post("/skills/save", data={
        "token": token(), "name": "Mine",
        "description": "Use when I say mine.", "body": "x"})

    saved = skills_store.read_all()[0]

    assert saved.path == tmp_path / ".claude" / "skills" / "mine" / "SKILL.md"
    assert saved.path.exists()
    # Still never inside the package: an update must not overwrite their work.
    #
    # Asked of the package's real location rather than of a folder name typed
    # into the test. The folder gets renamed -- it already has been once -- and
    # a hardcoded name turns this into an assertion that passes because the
    # string it looks for no longer exists anywhere.
    package_root = Path(skills_store.__file__).resolve().parent.parent.parent
    assert package_root not in saved.path.resolve().parents


def test_somebody_elses_skill_is_never_listed_or_deleted(tmp_path, browser):
    """`~/.claude/skills/` is shared. Other tools put skills there too."""
    theirs = tmp_path / ".claude" / "skills" / "not-ours"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text(
        "---\nname: Theirs\ndescription: Someone else's.\n---\nbody",
        encoding="utf-8")

    assert skills_store.read_all() == []
    assert skills_store.delete("not-ours") is False
    assert (theirs / "SKILL.md").exists()

    # And it is still visible when explicitly asked for.
    everything = skills_store.read_all(include_others=True)
    assert [skill.key for skill in everything] == ["not-ours"]
    assert everything[0].ours is False


def test_saving_over_somebody_elses_skill_is_refused(tmp_path):
    """Quietly replacing another tool's skill would be a nasty thing to do."""
    theirs = tmp_path / ".claude" / "skills" / "shared-name"
    theirs.mkdir(parents=True)
    original = ("---\nname: Theirs\ndescription: Someone else's.\n---\n"
                "their body")
    (theirs / "SKILL.md").write_text(original, encoding="utf-8")

    _, problems = skills_store.save(
        name="Shared name", description="Use when mine.", body="my body")

    assert any("was not created here" in problem for problem in problems)
    assert (theirs / "SKILL.md").read_text(encoding="utf-8") == original


def test_a_skill_with_a_weak_description_is_saved_but_flagged(browser):
    """Saving somebody's half-finished work is right. Staying quiet is not."""
    skill, problems = skills_store.save(
        name="Vague", description="does stuff", body="x")

    assert skill.path.exists()
    assert problems
    assert any("when" in problem for problem in problems)


def test_a_skill_can_be_deleted(browser):
    browser.post("/skills/save", data={
        "token": token(), "name": "Temporary",
        "description": "Use when testing.", "body": "x"})
    key = skills_store.read_all()[0].key

    browser.post("/skills/delete", data={"token": token(), "key": key})
    assert skills_store.read_all() == []


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------

def test_a_document_that_does_not_exist_is_refused(browser, tmp_path):
    response = browser.post("/knowledge/add", data={
        "token": token(), "title": "Handbook", "kind": "document",
        "target": str(tmp_path / "nope.pdf"),
    })

    assert "There is no file at" in response.get_data(as_text=True)
    assert knowledge.read_all() == []


def test_a_real_document_is_accepted(browser, tmp_path):
    real = tmp_path / "handbook.md"
    real.write_text("rules", encoding="utf-8")

    browser.post("/knowledge/add", data={
        "token": token(), "title": "Handbook", "kind": "document",
        "target": str(real), "why": "the rules", "tags": "reference, safety",
    })

    entries = knowledge.read_all()
    assert len(entries) == 1
    assert entries[0].tags == ("reference", "safety")
    assert entries[0].available is True


def test_a_link_must_be_a_url(browser):
    response = browser.post("/knowledge/add", data={
        "token": token(), "title": "Rules", "kind": "link",
        "target": "just some words",
    })
    assert "must start with http" in response.get_data(as_text=True)


def test_a_document_that_later_disappears_is_reported(tmp_path):
    """A stale pointer looks identical to a working one unless you say so."""
    real = tmp_path / "gone.md"
    real.write_text("x", encoding="utf-8")
    knowledge.add("Gone", "document", str(real))

    real.unlink()

    broken = knowledge.broken()
    assert len(broken) == 1
    assert "MISSING" in broken[0].status()


# ---------------------------------------------------------------------------
# Scheduled tasks
# ---------------------------------------------------------------------------

def test_a_user_task_can_be_created_with_each_trigger(browser):
    for trigger in ("time", "interval", "login"):
        browser.post("/schedule/save", data={
            "token": token(),
            "title": f"Task {trigger}",
            "why": "because",
            "prompt": "do something",
            "t0_kind": trigger,
            "t0_hour": "7", "t0_minute": "30", "t0_every": "45",
        })

    tasks = schedule.read_user_tasks()
    assert ({one.kind for task in tasks for one in task.triggers}
            == {"time", "interval", "login"})


def test_the_built_in_tasks_cannot_be_deleted(browser):
    """They ship with the package; deleting one from the user store is a no-op."""
    # Returns (deleted, note). A shipped task is not the user's to
    # delete, so nothing happens and there is nothing to report.
    assert schedule.delete_user_task("morning-summary") == (False, "")
    assert any(task.key == "morning-summary" for task in schedule.all_tasks())


def test_a_nonsense_time_does_not_produce_a_server_error(browser):
    """A typo in a form field must not read as 'the software is broken'."""
    response = browser.post("/schedule/save", data={
        "token": token(), "title": "Odd", "why": "x", "prompt": "y",
        "t0_kind": "time", "t0_hour": "not a number", "t0_minute": "99",
    }, follow_redirects=True)

    assert response.status_code == 200
    one = schedule.read_user_tasks()[0].triggers[0]
    assert 0 <= one.hour <= 23
    assert 0 <= one.minute <= 59


def test_an_impossible_interval_is_flagged_rather_than_accepted_silently():
    task = schedule.ScheduledTask(key="k", title="T", why="w", prompt="p",
                                  triggers=(schedule.Trigger(
                                      kind="interval", every_minutes=1),))
    problems = task.problems()
    assert any("five minutes" in problem for problem in problems)


def test_weekdays_come_through_from_the_form(browser):
    browser.post("/schedule/save", data={
        "token": token(), "title": "Weekdays", "why": "x", "prompt": "y",
        "t0_kind": "time", "t0_hour": "8", "t0_minute": "0",
        "t0_day_MON": "on", "t0_day_WED": "on",
    })

    task = schedule.read_user_tasks()[0]
    assert task.triggers[0].weekdays == ("MON", "WED")


def test_the_watch_trigger_is_honest_about_windows(monkeypatch):
    """No `schtasks` equivalent exists, so it falls back to polling -- and says so."""
    monkeypatch.setattr(paths, "is_macos", lambda: False)
    monkeypatch.setattr(paths, "is_windows", lambda: True)

    described = schedule.supported_triggers()["watch"]
    assert "not instant" in described


def test_a_login_task_says_only_that_it_is_a_logon_trigger():
    """No time boundary on a logon trigger.

    The command-line version of this rule was that `/SC ONLOGON /ST ...` is
    rejected outright by Windows. In XML the same mistake is quieter -- a
    StartBoundary on a LogonTrigger means "not before this date" -- so it is
    still worth a test.
    """
    task = schedule.ScheduledTask(key="k", title="T", why="w", prompt="p",
                                  triggers=(schedule.Trigger(
                                      kind="login"),))
    xml = schedule.windows_task_xml(task, Path("/run"))

    assert "<LogonTrigger>" in xml
    assert "<StartBoundary>" not in xml
    assert "<CalendarTrigger>" not in xml


# ---------------------------------------------------------------------------
# Phase 1 of "alive at install": the happening page, the phone surface, and
# the rule that a tunnel cannot change anything.


def test_the_happening_page_renders_the_event_bus(tmp_path, monkeypatch):
    from aki_agent import events, paths

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    events.record("task", "Morning summary ran", source="schedule")

    client = create_app().test_client()
    page = client.get("/events")

    assert page.status_code == 200
    assert b"Morning summary ran" in page.data


def test_the_phone_summary_answers_in_one_request(tmp_path, monkeypatch):
    """A phone on mobile data should not have to make six."""
    from aki_agent import paths

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    client = create_app().test_client()
    payload = client.get("/api/mobile/summary").get_json()

    for key in ("items", "held_messages", "scheduled", "handoff", "recent"):
        assert key in payload


def test_the_phone_menu_comes_from_the_server(tmp_path, monkeypatch):
    """So adding a page never requires shipping a new build of an app."""
    from aki_agent import paths

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    client = create_app().test_client()
    pages = client.get("/api/mobile/pages").get_json()["pages"]

    assert {"label", "path", "group"} <= set(pages[0])
    assert any(entry["path"] == "/events" for entry in pages)


def test_a_change_arriving_through_a_tunnel_is_refused():
    """Loopback binding stops the network, not a proxy in front of it.

    On the reference system that arrangement left a control surface — the
    house lights among it — reachable from outside with no password. Found
    afterwards, which is the wrong time.
    """
    client = create_app().test_client()

    refused = client.post("/schedule/install",
                          headers={"X-Forwarded-For": "203.0.113.9"})
    assert refused.status_code == 403

    # And a read is deliberately left alone -- the danger is writes.
    assert client.get("/api/mobile/pages").status_code == 200


# ---------------------------------------------------------------------------
# The built-in check on the specialists page
# ---------------------------------------------------------------------------

def test_the_specialists_page_shows_the_check_before_anything_is_created(browser):
    """"No specialists yet" was true and gave the wrong impression: there has
    been one since installation, and the page has to say so."""
    page = browser.get("/specialists", follow_redirects=True).get_data(as_text=True)

    assert "Sentinel" in page
    assert "built in" in page
    assert "Turn it off" in page


def test_the_check_can_be_switched_off_and_on_from_the_page(browser):
    from aki_agent import sentinel

    browser.post("/specialists/sentinel",
                 data={"token": token(), "state": "off"})
    assert sentinel.is_on() is False
    assert "Turn it back on" in browser.get(
        "/specialists", follow_redirects=True).get_data(as_text=True)

    browser.post("/specialists/sentinel",
                 data={"token": token(), "state": "on"})
    assert sentinel.is_on() is True


def test_switching_the_check_off_needs_the_token(browser):
    from aki_agent import sentinel

    response = browser.post("/specialists/sentinel", data={"state": "off"})

    assert response.status_code == 403
    assert sentinel.is_on(), "a forged request must not disable the check"


def test_the_page_offers_no_way_to_delete_the_built_in_check(browser):
    """It is turned off, not deleted. A delete button that quietly means
    "off" is something a user finds out by being surprised."""
    page = browser.get("/specialists", follow_redirects=True).get_data(as_text=True)

    assert 'value="sentinel"' not in page


# ---------------------------------------------------------------------------
# The session guard, on the page a person actually opens
# ---------------------------------------------------------------------------

def test_the_guard_is_on_the_sessions_page(browser):
    """Built as a CLI first and nearly shipped that way. The people this is
    for are exactly the people who never open a terminal."""
    page = browser.get("/sessions").get_data(as_text=True)

    assert "Session guard" in page
    assert "Context" in page and "Idle" in page
    assert "Recycle now" in page


def test_the_row_that_does_not_decide_is_marked_and_dimmed(browser):
    """Rule 3: a number that looks like a threshold and is not one gets read
    as the reason something happened."""
    page = browser.get("/sessions").get_data(as_text=True)

    assert "not a trigger" in page
    assert 'class="dim"' in page
    assert ">noted<" in page


def test_the_switches_save(browser):
    from aki_agent import guard

    browser.post("/sessions/recycling", data={
        "token": token(), "nightly_recycle": "on", "recycle_hour": "6"})

    saved = guard.settings()
    assert saved["auto_recycle"] is False, "an unticked box means off"
    assert saved["nightly_recycle"] is True
    assert saved["recycle_hour"] == 6


def test_an_impossible_hour_is_clamped_not_stored(browser):
    from aki_agent import guard

    browser.post("/sessions/recycling", data={
        "token": token(), "auto_recycle": "on", "recycle_hour": "99"})

    assert guard.settings()["recycle_hour"] == 23


def test_changing_the_switches_needs_the_token(browser):
    from aki_agent import guard

    response = browser.post("/sessions/recycling", data={"auto_recycle": "on"})

    assert response.status_code == 403
    assert not guard.settings_file().exists()


def test_the_recycle_button_needs_the_token(browser):
    assert browser.post("/sessions/recycle-now").status_code == 403


def test_the_button_still_refuses_while_the_session_is_busy(browser,
                                                            monkeypatch):
    """Pressing it says you want a restart. It does not say you want to lose
    whatever the session was in the middle of."""
    from aki_agent import recycle

    asked = {}

    def watch(command, **kwargs):
        asked.update(kwargs)
        return recycle.RecycleReport(reason="busy")

    monkeypatch.setattr(recycle, "perform", watch)

    browser.post("/sessions/recycle-now", data={"token": token()})

    if asked:               # only if a launcher existed to call it with
        assert asked["idle_seconds_required"] > 0


def test_a_refusal_is_shown_and_not_swallowed(browser, monkeypatch):
    """Found on a real machine, 2026-09-03: the button correctly declined --
    the session was not idle -- and the page said nothing at all. A correct
    decision delivered in silence is indistinguishable from a dead button,
    and the owner reported it as one."""
    from aki_agent import launcher as launcher_module, recycle

    script = launcher_module.launcher_path()
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("echo hello\n", encoding="utf-8")

    monkeypatch.setattr(
        recycle, "perform",
        lambda command, **kwargs: recycle.RecycleReport(reason="still busy"))

    response = browser.post("/sessions/recycle-now", data={"token": token()})

    assert response.status_code in (302, 303)
    assert "still+busy" in response.headers["Location"].replace("%20", "+")


def test_a_missing_launcher_says_so_rather_than_doing_nothing(browser):
    """The other silent path out of the same route."""
    from aki_agent import launcher as launcher_module

    script = launcher_module.launcher_path()
    if script.exists():
        script.unlink()

    response = browser.post("/sessions/recycle-now", data={"token": token()})

    assert response.status_code in (302, 303)
    assert "said=" in response.headers["Location"]


# ---------------------------------------------------------------------------
# The Telegram credentials, and the line between them
# ---------------------------------------------------------------------------

def test_the_bot_token_is_never_rendered_into_the_page(browser, monkeypatch):
    """Reported as a bug ("I cannot see the token") and it is not one.

    A bot token is a password. A value printed into a web page lands in the
    browser cache, in every screenshot of that page, and on screen during any
    screen share — and this package's users are learners being taught over
    screen shares. There is no way to un-leak one.
    """
    from aki_agent import telegram_setup

    from fake_credentials import FAKE_BOT_TOKEN

    monkeypatch.setattr(telegram_setup, "read_token", lambda: FAKE_BOT_TOKEN)

    page = browser.get("/connections").get_data(as_text=True)

    assert FAKE_BOT_TOKEN not in page
    assert FAKE_BOT_TOKEN.split(":")[1] not in page


def test_but_it_says_which_token_is_saved(browser, monkeypatch):
    """"Saved" alone is a poor answer, because the question behind it is
    *which* token."""
    from aki_agent import telegram_setup

    from fake_credentials import FAKE_BOT_TOKEN

    monkeypatch.setattr(telegram_setup, "read_token", lambda: FAKE_BOT_TOKEN)

    page = browser.get("/connections").get_data(as_text=True)

    # Derived, not typed out. A test that hard-codes a value computed from a
    # constant breaks whenever the constant changes, for no reason -- and the
    # literal would itself be a token-shaped string in a file that is not the
    # allowlisted one.
    number, _, rest = FAKE_BOT_TOKEN.partition(":")
    assert f"{number}:...{rest[-4:]}" in page


def test_the_fingerprint_is_short_enough_to_be_useless(monkeypatch):
    from aki_agent import telegram_setup

    from fake_credentials import FAKE_BOT_TOKEN

    monkeypatch.setattr(telegram_setup, "read_token", lambda: FAKE_BOT_TOKEN)

    shown = telegram_setup.token_fingerprint()

    assert shown.count("...") == 1
    assert len(shown.split("...")[-1]) == 4


def test_no_token_shows_no_fingerprint(monkeypatch):
    from aki_agent import telegram_setup

    monkeypatch.setattr(telegram_setup, "read_token", lambda: "")
    assert telegram_setup.token_fingerprint() == ""


def test_the_allowed_ids_ARE_shown(browser, monkeypatch):
    """The actual defect. A chat id is not a credential — it names a
    conversation and grants nothing. Hiding it behind a count meant somebody
    who allowed the wrong id could see there was one and never find out
    which."""
    from aki_agent import telegram_setup

    monkeypatch.setattr(telegram_setup, "allowed_ids",
                        lambda: ["412587349", "998877"])

    page = browser.get("/connections").get_data(as_text=True)

    assert "412587349" in page
    assert "998877" in page


def test_somebody_can_be_taken_off_the_list(browser, tmp_path, monkeypatch):
    """Being able to add without being able to remove is not an access list,
    it is a ratchet."""
    import json

    from aki_agent import telegram_setup

    access = tmp_path / "access.json"
    access.write_text(json.dumps({"allowFrom": ["111", "222"]}),
                      encoding="utf-8")
    monkeypatch.setattr(telegram_setup, "access_file", lambda: access)

    browser.post("/connections/telegram",
                 data={"token": token(), "action": "remove",
                       "user_id": "111"})

    assert telegram_setup.allowed_ids() == ["222"]


def test_removing_the_last_person_says_what_that_means(tmp_path, monkeypatch):
    import json

    from aki_agent import telegram_setup

    access = tmp_path / "access.json"
    access.write_text(json.dumps({"allowFrom": ["111"]}), encoding="utf-8")
    monkeypatch.setattr(telegram_setup, "access_file", lambda: access)

    ok, message = telegram_setup.remove_allowed("111")

    assert ok
    assert "cannot be reached" in message


def test_removing_somebody_who_is_not_there_says_so(tmp_path, monkeypatch):
    import json

    from aki_agent import telegram_setup

    access = tmp_path / "access.json"
    access.write_text(json.dumps({"allowFrom": ["111"]}), encoding="utf-8")
    monkeypatch.setattr(telegram_setup, "access_file", lambda: access)

    ok, message = telegram_setup.remove_allowed("999")

    assert not ok
    assert "not on the list" in message


def test_the_token_field_is_masked_by_default(browser):
    """A password being pasted into a window that may be shared or
    screenshotted. Masked at rest; the button is what un-masks it."""
    page = browser.get("/connections").get_data(as_text=True)

    assert 'name="token_value" type="password"' in page
    assert "data-secret" in page
    assert "data-reveal" in page


def test_the_eye_only_switches_the_field_type(browser):
    """It must not become a way to display a *stored* secret. A value the
    browser has is a value in the page, drawn or not — masking is protection
    for the moment of entry and nothing more."""
    base = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
            / "dashboard" / "templates" / "base.html").read_text(
                encoding="utf-8")

    # Bounded to the handler itself. The first version split on the next
    # `</script>`, which swallowed everything added to that block afterwards —
    # so a `fetch` belonging to a completely unrelated feature failed this
    # test. A test that reaches past the thing it is testing will eventually
    # fail for a reason that has nothing to do with it.
    handler = base.split("data-reveal")[1].split("});")[0]

    assert "field.type" in handler
    for forbidden in ("fetch(", "XMLHttpRequest", "localStorage.setItem"):
        assert forbidden not in handler


# ---------------------------------------------------------------------------
# The UI pass the maintainer asked for, 2026-08-20
# ---------------------------------------------------------------------------

def test_there_is_no_conversation_tab(browser):
    """The chat panel is on the right of every page, so a whole page showing
    the same conversation was a click leading to what you were looking at."""
    from aki_agent.dashboard import navigation

    labels = [page.label for group in navigation.GROUPS
              for page in group.pages]
    assert "Conversation" not in labels


def test_the_inbox_left_the_rail_without_taking_its_items_with_it():
    """Inbox is decisions. Notifications is the rules about interrupting.

    They were merged on 2026-08-20 and separated again on 2026-08-21 --
    The merge
    reasoned that both answer "is anything waiting for me"; what it missed is
    that one is a queue you work through and the other is a setting you
    decide once.

    Inbox then left the rail entirely on 2026-08-23: One Inbox
    could not draw the distinction those three do -- whose move it is -- and
    an item you are waiting on somebody else for is not a thing you can work
    through today.

    What this guards is that removing it from the rail removed a *button*,
    not a route. Both of its addresses still render.
    """
    from aki_agent.dashboard import navigation

    rail = {page.path for group in navigation.GROUPS for page in group.pages}
    assert "/inbox" not in rail

    # Notifications lives inside System from 2026-08-23 -- a tab, not a rail
    # entry. It is still its own page; it is just no longer its own group.
    holder = navigation.current("/notifications")
    assert holder.key == "system"

    # Both old addresses point at Today, where the three queue buttons are.
    # /notifications is a page again, so it belongs in the rail rather than in
    # the map of what went where.
    assert navigation.MOVED["/waiting"] == "/"
    assert navigation.MOVED["/inbox"] == "/"
    assert "/notifications" not in navigation.MOVED


def test_quiet_hours_can_be_changed_where_they_are_shown(browser):
    """Shown on one page and changed on another is a value people believe is
    fixed. He read "Quiet from 22:00", could not change it, and called the
    page useless — correctly."""
    page = browser.get("/notifications").get_data(as_text=True)

    assert 'action="/notifications/quiet"' in page
    assert 'name="quiet_from"' in page


def test_saving_quiet_hours_from_that_page_works(browser):
    """Times nothing else on the page could produce.

    This test passed for a day while the save did nothing at all. It posted
    23:00 and 06:30 and then looked for them in the page -- but 23:00 is also
    the start of the seeded `Daily` quiet mode rendered further down, and
    06:30 was already sitting in the example config it read back from. Both
    halves of the assertion were satisfied by things the save never touched,
    so the only way for it to fail was for the page to stop rendering.
    01:11 and 02:22 appear nowhere unless they were written.
    """
    browser.post("/notifications/quiet", data={
        "token": token(), "notifications_present": "1",
        "notifications_enabled": "on",
        "quiet_from": "01:11", "quiet_to": "02:22"})

    page = browser.get("/notifications").get_data(as_text=True)
    assert "01:11" in page and "02:22" in page


def test_the_two_stopping_buttons_are_marked_dangerous(browser):
    """They sit among ordinary Save buttons and look exactly like them."""
    assert "danger" in browser.get("/sessions").get_data(as_text=True)

    # The BUTTON, not the form around it, and the classes rather than their
    # order -- `loud` was added on 2026-08-21 to make it bigger and red
    # without being hovered.
    #
    # A first attempt matched `class="stopform"`, which contains "stop",
    # carries no danger marking, and is the wrapper rather than the control.
    # It failed on the wrapper while the button beside it had been marked
    # correctly all along.
    home = browser.get("/").get_data(as_text=True)
    assert re.search(r'class="[^"]*stop[^"]*danger[^"]*"', home), (
        "the stop button on the front page is not marked dangerous")


def test_a_connected_thing_does_not_ask_for_what_it_already_has(browser,
                                                                monkeypatch):
    """An empty input beside a working connection reads as "not set up"."""
    from aki_agent import telegram_setup

    monkeypatch.setattr(telegram_setup, "allowed_ids", lambda: ["412587349"])

    page = browser.get("/connections").get_data(as_text=True)

    assert "Allow somebody else" in page, "the form folds behind a summary"
    assert "<details" in page


def test_the_safety_page_says_why_it_cannot_be_edited(browser):
    """A floor that can be lifted from a web page is not a floor."""
    page = browser.get("/safety").get_data(as_text=True)

    assert "not editable, and that is the point" in page
    assert "CLAUDE.md" in page, "and it says where the editable rules are"


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

def test_every_theme_is_offered_with_a_reason(browser):
    from aki_agent import themes

    page = browser.get("/theme").get_data(as_text=True)

    for one in themes.THEMES:
        assert one.name in page
        assert one.why, f"{one.key} has no reason to pick it"


def test_choosing_one_writes_the_accent(browser):
    from aki_agent import themes

    browser.post("/theme/choose", data={"token": token(), "theme": "moss"})

    page = browser.get("/theme").get_data(as_text=True)
    assert themes.by_key("moss").accent in page


def test_an_unknown_theme_falls_back_rather_than_failing():
    """A config naming a theme that no longer exists is a reason to show the
    default, never a reason for the page not to load — somebody whose page
    will not open cannot use the page to fix it."""
    from aki_agent import themes

    assert themes.by_key("does-not-exist") is themes.DEFAULT
    assert themes.by_key("") is themes.DEFAULT


def test_a_hand_picked_colour_is_not_rounded_to_the_nearest_theme():
    from aki_agent import themes

    assert themes.matching("#123456") is None
    assert themes.ground_for("#123456") == "dark"


def test_a_light_theme_asks_for_the_light_ground(browser):
    from aki_agent import themes

    browser.post("/theme/choose", data={"token": token(), "theme": "paper"})

    assert themes.ground_for(themes.by_key("paper").accent) == "light"
    assert 'class="light"' in browser.get("/theme").get_data(as_text=True)


def test_changing_the_theme_needs_the_token(browser):
    assert browser.post("/theme/choose",
                        data={"theme": "ember"}).status_code == 403


def test_the_chat_panel_width_is_not_a_fixed_pixel_count(browser):
    """reported 2026-08-20: "covering the whole screen". 340px is unremarkable
    on a wide monitor and most of a window on a laptop with a terminal beside
    it — a fixed pixel width is a width chosen for the author's monitor."""
    page = browser.get("/").get_data(as_text=True)

    assert "--chat-width: clamp(" in page
    assert "--chat-width: 340px" not in page


def test_every_css_variable_the_page_uses_is_defined_on_plain_root(browser):
    """The canary for a class of bug no other test here can see.

    On 2026-08-20 a theme change opened `:root.light` by moving `:root`'s
    closing brace upwards, which left `--chat-width` and `--head` defined only
    for the light ground. On the default dark ground they did not exist, so
    `width: var(--chat-width)` was invalid, and a `position: fixed` panel with
    no width sized itself to its content — the chat panel covered the whole
    page and pushed the text off the left edge.

    742 tests passed throughout. None of them can read a stylesheet. This one
    can: every `var(--x)` in the page must have an `--x:` on plain `:root`,
    which is exactly the invariant that broke.
    """
    import re

    page = browser.get("/").get_data(as_text=True)
    style = page.split("<style>")[1].split("</style>")[0]

    # `:root { ... }` — the first block only, deliberately: a variable that is
    # only defined under a theme class is the defect being looked for.
    root_block = re.search(r":root\s*\{(.*?)\n\}", style, re.DOTALL)
    assert root_block, "the base :root block should be findable"
    defined = set(re.findall(r"(--[\w-]+)\s*:", root_block.group(1)))

    used = set(re.findall(r"var\((--[\w-]+)", style))
    # Anything with a fallback -- var(--x, 1rem) -- is allowed to be absent.
    with_fallback = set(re.findall(r"var\((--[\w-]+)\s*,", style))

    missing = sorted(used - defined - with_fallback)
    assert not missing, (
        "these are used but not defined on plain :root, so they are undefined "
        "on the default ground: " + ", ".join(missing))


def test_the_chat_panel_has_a_width_at_all(browser):
    """The specific symptom: a fixed panel with no width sizes to its content
    and swallows the page."""
    page = browser.get("/").get_data(as_text=True)
    style = page.split("<style>")[1].split("</style>")[0]
    root_block = style.split(":root {")[1].split("\n}")[0]

    assert "--chat-width" in root_block
    assert "--head" in root_block


def test_which_tasks_reach_you_is_asked_on_the_notifications_page(browser):
    """It used to be a column on Schedule.

    That is right: Schedule is
    about when work happens, Notifications about when you get interrupted,
    and the switch was answering the second question on the first page.
    """
    schedule_page = browser.get("/schedule").get_data(as_text=True)
    assert "Tells you" not in schedule_page
    assert "/schedule/announce" not in schedule_page
    # but it says where the question went, rather than dropping it silently
    assert "/notifications" in schedule_page

    notifications = browser.get("/notifications").get_data(as_text=True)
    assert "Quiet Time" in notifications
    assert "/notifications/assign" in notifications


def test_the_switch_saves(browser):
    """Posted to the endpoint the page actually uses.

    This used to drive `/schedule/announce`, which was the copy left behind
    when the switch moved to Notifications on 2026-08-21 -- so the test kept
    a route alive that no page had posted to since. `/notifications/assign`
    is the real one, and it does more: it sets the quiet mode as well as the
    announce flag, which the other never did.
    """
    from aki_agent import schedule

    assert schedule.announces("morning-summary")

    browser.post("/notifications/assign",
                 data={"token": token(), "key": "morning-summary",
                       "mode": "never"})

    assert not schedule.announces("morning-summary")


def test_changing_it_needs_the_token(browser):
    from aki_agent import schedule

    response = browser.post("/notifications/assign",
                            data={"key": "checkpoint", "mode": "never"})

    assert response.status_code == 403
    assert not schedule.announces("checkpoint")


def test_the_health_page_offers_a_button_not_only_a_command(browser):
    """reported 2026-08-20: "where to type the command??"

    That question is the whole answer. This package's premise is that its
    users do not open a terminal, and a fix offered only as a command line is
    a fix not offered to the people it is for.
    """
    page = browser.get("/health").get_data(as_text=True)

    assert 'action="/health/repair"' in page
    assert ">Repair<" in page


def test_repair_needs_the_token(browser):
    assert browser.post("/health/repair").status_code == 403


def test_repair_reports_what_it_did(browser):
    response = browser.post("/health/repair", data={"token": token()})

    assert response.status_code == 302
    assert "note=" in response.headers["Location"]


def test_no_template_nests_one_block_inside_another():
    """A page whose `body` block sits inside its `heading` block renders its
    whole body twice, wherever the base template puts each one.

    THE BUG, AND WHY A TEST DID NOT CATCH IT (2026-08-20)
    -----------------------------------------------------
    An edit meant to move two paragraphs inside `{% block body %}` cut at the
    first `{% endblock %}` it found — which belonged to `heading`. The schedule
    page then rendered its entire contents twice, and the maintainer was looking at a
    doubled task list.

    The test written at the same time asserted that one of those paragraphs
    appeared in the page. It passed: the paragraph was there, in the second
    copy. A presence check cannot see a duplicate, and "it renders" is not the
    same as "it renders once".

    So this checks the structure instead: blocks must close in order, and none
    may contain another.
    """
    import re
    from pathlib import Path

    folder = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
              / "dashboard" / "templates")
    offences = []

    for path in sorted(folder.glob("*.html")):
        if path.name == "base.html":
            continue                      # the base legitimately holds blocks
        depth = 0
        for tag in re.findall(r"{%-?\s*(block|endblock)\b", path.read_text(
                encoding="utf-8")):
            depth += 1 if tag == "block" else -1
            if depth > 1:
                offences.append(f"{path.name}: a block inside another block")
                break
            if depth < 0:
                offences.append(f"{path.name}: an endblock with no block")
                break
        else:
            if depth != 0:
                offences.append(f"{path.name}: {depth} block(s) never closed")

    assert not offences, "; ".join(offences)


def test_the_schedule_page_renders_its_tasks_once(browser):
    page = browser.get("/schedule").get_data(as_text=True)

    assert page.count("Morning summary") == 1
    assert page.count("<table>") == 1


# ---------------------------------------------------------------------------
# The queue sheet, reworked 2026-08-24
#
# The maintainer, after using it: it should rise to two thirds of the screen, close on
# a click outside as well as on the cross, carry the three buttons up with it,
# be wider and centred, and float over everything.
# ---------------------------------------------------------------------------


def test_the_sheet_rises_to_two_thirds_and_the_number_lives_in_one_place(
        browser):
    page = browser.get("/").get_data(as_text=True)

    assert "--sheet-height: 66vh" in page
    # The button row's OPEN position is derived rather than restated. Two
    # copies of this number drift, and the drift shows as a button row that
    # stops short of the sheet it is supposed to be sitting on.
    #
    # It used to be the closed position that was derived, because the row
    # only existed while the sheet was open. Since 2026-09-04 the row is
    # always at the bottom of the window -- so it
    # is the travel upwards that has to be exactly the sheet's height.
    assert "translateY(calc(-1 * var(--sheet-height)))" in page
    assert "height: var(--sheet-height)" in page


def test_clicking_outside_closes_it(browser):
    """A backdrop element rather than a document-level click listener that has
    to decide whether a click was 'inside'. That decision is easy to get
    wrong once, and wrong once means the sheet shutting while somebody is
    clicking a row in it."""
    page = browser.get("/").get_data(as_text=True)

    assert 'id="queue-scrim"' in page
    assert "scrim.addEventListener('click', shut)" in page


def test_the_button_row_is_always_at_the_foot_of_the_window(browser):
    """Two instructions, a fortnight apart, and both still hold.

     -- the row rides up with
    the sheet rather than being slid over.

     -- and until then the row only became
    a fixed bar once the sheet was already open. It sat in the page, a screen
    and a half down, which is backwards: the row is how the panel is opened,
    so it is the part that must never need finding.

    So it is fixed at the bottom at all times, and rises by exactly the
    sheet's height when the sheet does. Checked in a browser rather than
    inferred: with the sheet up, the bar's bottom edge and the sheet's top
    edge were both at 258.
    """
    page = browser.get("/").get_data(as_text=True)

    assert "position: fixed; left: var(--rail-width, 0); right: 0;" in page, (
        "the row must be fixed whether or not the sheet is open")
    assert "bottom: 0; z-index: 93;" in page
    assert "body.queueup .pilltabs {" in page
    assert "main:has(.pilltabs) { padding-bottom: 5.5rem; }" in page, (
        "a fixed bar over the page needs the page to end above it")


def test_the_backdrop_covers_the_page_and_not_only_the_rail(browser):
    """Two bugs, opposite ways round, from the same stacking context.

    `main` carries `z-index: 1`, which makes it one. On 2026-08-24 the sheet
    lived inside it, so every z-index on the sheet was measured within main's
    1 and lost to the rail (20): `elementFromPoint` over the rail returned
    the rail's own buttons while the sheet was up. The fix was to raise main
    to 91 for the duration, lifting the whole layer together.

    On 2026-09-04 the sheet moved OUT of main, so the bar could be on every
    page -- and that rule inverted: main at 91 now sat above the backdrop at
    90, so the page content was the one thing the backdrop did not dim.
    Nothing was lit; everything around it was dimmed.

    So the rule is gone, and this checks it stays gone. Measured after the
    change: over the content, over the rail and over the top bar, the topmost
    element is the backdrop.
    """
    import re

    page = browser.get("/").get_data(as_text=True)
    style = page.split("<style>")[1].split("</style>")[0]
    # Comments only, because the one above the deleted rule quotes it in
    # full -- the same trap this evening set three times over.
    declarations = re.sub(r"/\*.*?\*/", "", style, flags=re.S)

    assert "body.queueopen main" not in declarations, (
        "raising main above the backdrop leaves the page undimmed; the sheet "
        "is outside main now and needs no lift")
    assert "z-index: 90;" in declarations   # the backdrop
    assert "bottom: 0; z-index: 93;" in declarations  # the bar above it


# ---------------------------------------------------------------------------
# Readers that had no writer -- 2026-09-05 audit


def test_working_hours_can_be_set_from_the_settings_page(browser):
    """Three fields with three readers and, until now, no writer.

    `User.is_working()`, `User.working_hours_sentence()` and the CLAUDE.md the
    scaffold writes all read these. Nothing set them -- not this page, not the
    setup interview, not the CLI -- so every install ran on MON-FRI
    09:00-17:30 and the only way to change it was finding the YAML.
    """
    browser.post("/settings/save", data={
        "token": token(),
        "working_days": "tue, wed", "working_from": "10:15",
        "working_to": "16:45"})

    page = browser.get("/settings").get_data(as_text=True)
    assert "10:15" in page and "16:45" in page
    assert "TUE, WED" in page          # upper-cased, the form `is_working` compares


def test_a_time_that_is_not_a_time_is_refused_rather_than_stored(browser):
    """Silently wrong hours is the failure this audit was about.

    Written first as "post nonsense, assert it is not in the page", which
    passed with the whole feature removed -- nothing was ever stored, so
    nothing could come back. It now saves a real time first and asserts THAT
    survives the bad one, which is only true if saving works at all.
    """
    browser.post("/settings/save", data={
        "token": token(), "working_from": "10:15", "working_to": "16:45"})
    browser.post("/settings/save", data={
        "token": token(), "working_from": "half nine"})

    page = browser.get("/settings").get_data(as_text=True)
    assert "half nine" not in page
    assert "10:15" in page


def test_every_channel_that_exists_gets_a_switch(browser):
    """The chips iterated the config, whose only writer was the chips.

    `Notifications.channels` starts empty, so on a fresh install nothing
    rendered -- while the paragraph beside it said a noisy sender "gets
    switched off in one click". The click did not exist until the YAML was
    edited by hand.
    """
    from aki_agent import channels

    channels.reset_to_defaults()
    page = browser.get("/notifications").get_data(as_text=True)

    for name in channels.registered_names():
        assert f'name="name" value="{name}"' in page, f"no switch for {name}"
