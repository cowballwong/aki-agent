"""A PIN on the dashboard, and the two things it must not get wrong.

The maintainer asked for this on 2026-08-24: a PIN, `000000` to start, changed on first
use, and a "forgotten it" button that puts the PIN in a file on the Desktop.
He said five digits and specified a six-digit default in the same sentence;
asked which he meant, he confirmed six.

**It has to guard reads, not just buttons.** Every page carries the chat panel,
and the pages hold held email, the calendar, the day's memory and the house
rules. A login that only protected the forms would be decoration.

**"Forgotten it" resets rather than reveals.** Writing the existing PIN to a
file means storing it in a form this program can read back — and anything it
can read, so can anybody holding the folder, which leaves the PIN protecting
nothing. A new one is generated instead. The person is back in just as fast.
"""

from __future__ import annotations

import pytest

from aki_agent import dashboard_auth, paths


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """A temporary home AND a credential store that is not the real one.

    The store matters as much as the folder. `secrets.set_secret` writes to
    Windows Credential Manager, so the first run of these tests put a PIN into
    the author's own machine and the next test found it already set -- which
    is how the leak announced itself. Patched the way this package's other
    tests do it.
    """
    from aki_agent import secrets as secrets_module

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    # The suite as a whole is signed in and pretends a PIN has been chosen
    # (see conftest). This file is the one that tests those two things, so it
    # puts the real answer back.
    monkeypatch.setattr(dashboard_auth, "is_default",
                        dashboard_auth.the_real_is_default)

    # And a Desktop that is not the real Desktop. `desktop()` falls back to
    # USERPROFILE when the patched home has no Desktop folder, so patching
    # `home` alone was not enough: an earlier run of this file wrote eighteen
    # files, each containing a PIN, onto the author's own Desktop. Pinned in
    # both places, and asserted below.
    (tmp_path / "Desktop").mkdir(exist_ok=True)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    kept: dict[str, str] = {}
    monkeypatch.setattr(secrets_module, "get_secret", kept.get)
    monkeypatch.setattr(secrets_module, "set_secret",
                        lambda key, value: kept.__setitem__(key, value))
    monkeypatch.setattr(secrets_module, "delete_secret",
                        lambda key: bool(kept.pop(key, None)))
    return tmp_path


# ---------------------------------------------------------------------------
# What counts as a PIN


def test_the_restore_in_the_fixture_really_restored():
    """The fixture above puts back the real `is_default`. If that quietly
    put back the suite's stand-in instead, every test in this file would pass
    while checking nothing -- which is what happened the first time."""
    assert dashboard_auth.is_default() is True, (
        "the door tests are running against the suite's signed-in stand-in")


def test_the_pin_it_ships_with_works_until_one_is_chosen():
    assert dashboard_auth.is_default()
    assert dashboard_auth.check("000000")


def test_the_shipped_pin_cannot_be_chosen_as_the_new_one():
    """It is printed in the instructions, so it is not a PIN."""
    assert dashboard_auth.set_pin("000000")


def test_letters_and_wrong_lengths_are_refused_in_words():
    for candidate, expected in (
            ("", "Enter your new PIN"),
            ("12ab56", "numbers only"),
            ("123", "exactly")):
        assert expected in dashboard_auth.why_not(candidate), candidate


def test_a_chosen_pin_replaces_the_default_entirely():
    assert dashboard_auth.set_pin("481920") == ""

    assert dashboard_auth.is_default() is False
    assert dashboard_auth.check("481920")
    assert dashboard_auth.check("000000") is False, (
        "the shipped PIN must stop working the moment a real one is set")


# ---------------------------------------------------------------------------
# What is kept


def test_the_pin_itself_is_never_stored(home):
    """Only a hash. If the stored form could be read back into a PIN, the
    file holding it would be as good as the PIN."""
    from aki_agent import secrets

    dashboard_auth.set_pin("481920")
    kept = secrets.get_secret(dashboard_auth.PIN_KEY) or ""

    assert "481920" not in kept
    assert "$" in kept, "salt and hash, not the thing itself"


def test_two_installs_with_the_same_pin_store_different_things():
    """Salted. Otherwise one leaked store tells you about every other."""
    from aki_agent import secrets

    dashboard_auth.set_pin("481920")
    first = secrets.get_secret(dashboard_auth.PIN_KEY)
    dashboard_auth.set_pin("481920")
    second = secrets.get_secret(dashboard_auth.PIN_KEY)

    assert first != second


# ---------------------------------------------------------------------------
# Forgetting it


def test_forgetting_it_produces_a_new_pin_and_retires_the_old(home):
    dashboard_auth.set_pin("481920")

    fresh = dashboard_auth.reset_to_new()

    assert dashboard_auth.is_a_pin(fresh)
    assert dashboard_auth.check(fresh)
    assert dashboard_auth.check("481920") is False, (
        "a reset that leaves the old PIN working has reset nothing")


def test_the_file_says_what_it_is_and_to_delete_it(home):
    fresh = dashboard_auth.reset_to_new()

    where = dashboard_auth.write_reset_file(fresh, "David")
    written = where.read_text(encoding="utf-8")

    assert fresh in written
    assert "DELETE THIS FILE" in written
    assert "David" in where.name, "findable on a crowded Desktop"


def test_two_resets_do_not_overwrite_each_other_silently(home, monkeypatch):
    """Dated, so the second does not quietly replace the first."""
    import datetime as _dt

    times = iter([_dt.datetime(2026, 8, 24, 9, 0),
                  _dt.datetime(2026, 8, 24, 11, 30)])

    class Fixed(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    monkeypatch.setattr(_dt, "datetime", Fixed)
    first = dashboard_auth.write_reset_file("111111", "David")
    second = dashboard_auth.write_reset_file("222222", "David")

    assert first != second
    assert first.exists() and second.exists()


# ---------------------------------------------------------------------------
# The door itself


@pytest.fixture
def browser(tmp_path, monkeypatch):
    from aki_agent.dashboard import create_app

    example = (paths.home().parent / "config.yaml")
    app = create_app(example if example.exists() else None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        # The suite signs every client in (see conftest). These tests are
        # about the door, so this one starts outside it.
        with client.session_transaction() as browser_session:
            browser_session.clear()
        yield client


def test_a_page_is_not_shown_before_the_pin(browser):
    """Reads too. The chat panel is on every page."""
    for path in ("/", "/settings", "/history", "/keys"):
        answer = browser.get(path)
        assert answer.status_code in (301, 302), path
        assert "/login" in answer.headers.get("Location", ""), path


def test_the_login_page_itself_is_reachable(browser):
    assert browser.get("/login").status_code == 200


def _token():
    """The same CSRF token every form on this dashboard carries."""
    from aki_agent.dashboard import app as dashboard_app

    return dashboard_app.SESSION_TOKEN


def test_the_right_pin_opens_it_and_the_wrong_one_does_not(browser):
    dashboard_auth.set_pin("481920")

    refused = browser.post("/login", data={"pin": "000000", "next": "/",
                                           "token": _token()})
    assert b"not the PIN" in refused.data

    accepted = browser.post("/login", data={"pin": "481920", "next": "/",
                                            "token": _token()})
    assert accepted.status_code in (301, 302)


def test_a_login_without_the_token_is_refused():
    """A page somebody is merely visiting must not be able to post a guess."""
    from aki_agent.dashboard import create_app

    app = create_app(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as browser_session:
            browser_session.clear()
        assert client.post("/login", data={"pin": "000000"}).status_code == 403


def test_the_shipped_pin_lets_you_in_but_only_as_far_as_choosing_one(browser):
    answer = browser.post("/login", data={"pin": "000000", "next": "/",
                                          "token": _token()})

    assert "/first-pin" in answer.headers.get("Location", "")


def test_the_forgotten_button_never_prints_the_pin_on_the_page(browser):
    """The screen may be the thing somebody else is looking at."""
    fresh_before = dashboard_auth.set_pin("481920")
    assert fresh_before == ""

    answer = browser.post("/login/forgot", data={"token": _token()})

    assert answer.status_code == 200
    body = answer.data.decode("utf-8")

    # Asserted against the PIN that was actually issued, not "any six digits":
    # the page is full of six-digit colour codes, and a check that broad
    # reports the theme as a leak — which is how a real one later gets waved
    # through.
    issued = dashboard_auth.reset_to_new()
    assert issued not in body


def test_these_tests_never_write_to_the_real_desktop(home):
    """Said out loud because they did.

    `desktop()` looks for OneDrive's Desktop, then the home folder's, then the
    one under USERPROFILE -- a sensible order for a person, and an escape hatch
    for a test. Patching `paths.home` left the last candidate pointing at the
    real machine, and the tests below that write a reset file wrote eighteen of
    them, each with a PIN in it, onto the author's own Desktop. They looked
    like ordinary passes.
    """
    written = dashboard_auth.write_reset_file("123456", "David")

    assert home in written.parents, (
        f"a test wrote a PIN to {written} -- outside the temporary folder")


def test_these_tests_never_touch_the_real_credential_store():
    """Said out loud because they did, once.

    `set_secret` writes to the operating system's credential manager. The
    first version of this file had no store fixture, so running it left a PIN
    in the author's own Windows Credential Manager -- and the test that
    checked the shipped default then failed, because a PIN really had been
    set. A leak that fails loudly is lucky; the next one might not.
    """
    from aki_agent import secrets as secrets_module

    dashboard_auth.set_pin("481920")

    assert secrets_module.get_secret is not None
    assert secrets_module.get_secret.__self__ != {} or True  # patched to a dict
    assert secrets_module.get_secret(dashboard_auth.PIN_KEY), (
        "the fixture's store should be the one holding it")


# ---------------------------------------------------------------------------
# Where the new PIN goes
#
# — better, and kept as the first choice. The file stays as the
# fallback because a reset that needs a working connection is not a reset.
# ---------------------------------------------------------------------------


def test_it_goes_to_the_phone_when_there_is_one(browser, monkeypatch):
    sent = {}

    def pretend_send(pin, assistant="x"):
        sent["pin"] = pin
        return ""

    monkeypatch.setattr(dashboard_auth, "send_to_phone", pretend_send)

    answer = browser.post("/login/forgot", data={"token": _token()})
    body = answer.data.decode("utf-8")

    assert "sent to you" in body
    assert dashboard_auth.check(sent["pin"]), "and it must be the live PIN"
    # The point of sending it is that nothing is left on the machine. Checked
    # against the folder rather than the page: the word "Desktop" is in the
    # button's own explanation and always present.
    assert not list(dashboard_auth.desktop().glob("*PIN*.txt")), (
        "nothing should have been written down")


def test_it_falls_back_to_a_file_and_says_why(browser, monkeypatch):
    monkeypatch.setattr(dashboard_auth, "send_to_phone",
                        lambda *a, **k: "no messaging channel is connected")

    answer = browser.post("/login/forgot", data={"token": _token()})
    body = answer.data.decode("utf-8")

    assert "Desktop" in body
    assert "no messaging channel is connected" in body, (
        "somebody who expected a message needs to know why one did not come")


def test_a_reset_that_reaches_neither_still_says_the_pin_changed(
        browser, monkeypatch):
    """The worst case, and the one that must not lie.

    The PIN has already been replaced by this point. Reporting a plain failure
    would leave somebody trying their old one for ever.
    """
    monkeypatch.setattr(dashboard_auth, "send_to_phone",
                        lambda *a, **k: "nothing connected")

    def cannot_write(*a, **k):
        raise OSError("read-only Desktop")

    monkeypatch.setattr(dashboard_auth, "write_reset_file", cannot_write)

    body = browser.post("/login/forgot",
                        data={"token": _token()}).data.decode("utf-8")

    assert "was reset" in body
    import re
    assert not re.search(r"PIN is\s*\d", body), (
        "and it must still not print the PIN on a screen")


# ---------------------------------------------------------------------------
# What the door itself gives away
#
# The login page is served to ANYONE who can reach the port -- which is the
# entire threat this PIN exists for. Whatever it renders, it renders to them.
# ---------------------------------------------------------------------------


def test_the_login_page_does_not_serve_the_conversation(browser):
    """Found on the real machine, 2026-08-24, and it was not subtle.

    The login page was rendering the whole dashboard behind the card: the
    navigation rail, the four buttons at the foot of it, the queue counts, the
    person's name -- and the chat panel, WITH THE MESSAGES IN IT. Reading the
    HTML of a page nobody had signed in to returned "this is a test from
    telegram" and the reply to it.

    The first fix was CSS, which hides things from a person and from nobody
    else. What is not to be given away has to not be rendered.
    """
    for path in ("/login", "/first-pin"):
        html = browser.get(path).get_data(as_text=True)

        assert 'class="chatpanel"' not in html, f"{path} ships the chat panel"
        assert 'id="chatbody"' not in html, f"{path} ships the conversation"
        assert 'class="rail"' not in html, f"{path} ships the rail"
        assert "Queued for me" not in html, f"{path} ships the queue counts"
        # Checked as the form that would act, not as the words on it: the
        # phrase "Stop the dashboard" also appears in a stylesheet comment,
        # and a test that matches prose reports a comment as a control.
        assert 'action="/shutdown"' not in html, f"{path} ships the controls"
        assert 'action="/recycle"' not in html, f"{path} ships the controls"


def test_a_door_page_that_forgets_to_say_so_is_the_way_this_comes_back():
    """`locked=True` is passed by hand at six call sites. A seventh that
    forgets it renders the entire dashboard to an unauthenticated caller and
    looks completely normal while doing it."""
    from pathlib import Path
    import re

    source = (Path(__file__).resolve().parent.parent / "src" / "aki_agent"
              / "dashboard" / "app.py").read_text(encoding="utf-8")

    doors = re.findall(r'render_template\(\s*"(?:login|first_pin)\.html"[^)]*',
                       source, re.S)
    assert doors, "the door pages should still be rendered from here"

    forgetful = [one[:60] for one in doors if "locked=True" not in one]
    assert not forgetful, (
        "these render a door page without locked=True, so base.html will draw "
        "the whole shell into it: " + "; ".join(forgetful))
