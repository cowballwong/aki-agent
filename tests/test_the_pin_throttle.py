"""The wait behind the PIN, which is the part that survives being on the internet.

reported 2026-08-28, wanting users to reach their dashboard through a tunnel,
then.

It was already six — he decided that on 2026-08-24 and the constant records it.
So the answer was not to change the length. Six digits is a million
combinations: against somebody typing that is plenty, and against a script over
a tunnel with nothing slowing it down a million is an afternoon.

What changes that arithmetic is refusing to answer quickly. Five wrong tries,
then a wait that grows. These tests are about that wait, and about the two ways
it could be quietly useless:

  * it must survive a restart, or an attacker who can bounce the process gets
    unlimited tries;
  * it must not answer while it is holding, or each rejected attempt still
    leaks whether the PIN was right.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from aki_agent import dashboard_auth, paths


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    dashboard_auth.clear_failures()
    yield
    dashboard_auth.clear_failures()


# ---------------------------------------------------------------------------
# The length was already settled
# ---------------------------------------------------------------------------

def test_the_pin_is_six_digits():
    """Decided 2026-08-24, re-confirmed 2026-08-28. Recorded, not re-litigated."""
    assert dashboard_auth.PIN_LENGTH == 6
    assert dashboard_auth.is_a_pin("123456")
    assert not dashboard_auth.is_a_pin("12345")
    assert not dashboard_auth.is_a_pin("1234567")


# ---------------------------------------------------------------------------
# The wait
# ---------------------------------------------------------------------------

def test_a_person_who_fumbles_a_digit_notices_nothing():
    """Four wrong tries is a human having a bad morning, not an attack."""
    for _ in range(4):
        dashboard_auth.record_failure()
    held, seconds = dashboard_auth.locked_out()
    assert held is False
    assert seconds == 0


def test_the_fifth_wrong_try_starts_the_wait():
    for _ in range(5):
        dashboard_auth.record_failure()
    held, seconds = dashboard_auth.locked_out()
    assert held is True
    assert 0 < seconds <= 60


def test_the_wait_grows_rather_than_staying_put():
    """A fixed wait is a rate limit an attacker simply budgets for."""
    for _ in range(5):
        dashboard_auth.record_failure()
    _, first = dashboard_auth.locked_out()
    for _ in range(5):
        dashboard_auth.record_failure()
    _, second = dashboard_auth.locked_out()
    for _ in range(10):
        dashboard_auth.record_failure()
    _, third = dashboard_auth.locked_out()
    assert first < second < third


def test_the_wait_ends():
    """A throttle that never lets go is a lock-out, not a throttle."""
    for _ in range(5):
        dashboard_auth.record_failure()
    later = time.time() + 61
    held, _ = dashboard_auth.locked_out(now=later)
    assert held is False


def test_the_right_pin_forgives_everything_before_it():
    for _ in range(9):
        dashboard_auth.record_failure()
    dashboard_auth.clear_failures()
    assert dashboard_auth.locked_out() == (False, 0)


def test_the_count_survives_a_restart():
    """The point of a file rather than a variable.

    An attacker who can cause a restart -- and the watchdog restarts this
    dashboard on its own every ten minutes -- must not be able to clear the
    count by causing one.
    """
    for _ in range(6):
        dashboard_auth.record_failure()

    import importlib
    importlib.reload(dashboard_auth)

    held, seconds = dashboard_auth.locked_out()
    assert held is True and seconds > 0


def test_the_wait_is_said_in_words_a_person_can_act_on():
    assert "seconds" in dashboard_auth.how_long(30)
    assert "minutes" in dashboard_auth.how_long(300)
    assert "hours" in dashboard_auth.how_long(3600)


# ---------------------------------------------------------------------------
# Through the door itself
# ---------------------------------------------------------------------------

CONFIG = (Path(__file__).resolve().parents[1] / "configs" / "examples"
          / "architecture.yaml")


def _browser(monkeypatch):
    """A client with the real door in place.

    conftest disables the PIN for the rest of the suite, which is right there
    and wrong here: this file is about the door.
    """
    monkeypatch.setattr(dashboard_auth, "is_default", lambda: False)
    from aki_agent.dashboard import create_app

    app = create_app(CONFIG)
    app.config["TESTING"] = True
    return app.test_client()


def _token() -> str:
    """The anti-forgery token every POST must carry.

    Supplied properly rather than worked around. A test that reached past this
    guard would be testing a door the product does not have.
    """
    from aki_agent.dashboard import app as dashboard_app

    return dashboard_app.SESSION_TOKEN


def test_a_wrong_pin_is_refused_and_counted(monkeypatch):
    browser = _browser(monkeypatch)
    page = browser.post("/login", data={"pin": "111111", "next": "/", "token": _token()})
    assert page.status_code == 200
    assert "not the PIN" in page.get_data(as_text=True)


def test_once_it_is_holding_it_stops_saying_whether_the_pin_was_right(monkeypatch):
    """Otherwise the wait leaks a bit per attempt and buys nothing."""
    browser = _browser(monkeypatch)
    for _ in range(6):
        browser.post("/login", data={"pin": "111111", "next": "/", "token": _token()})
    page = browser.post("/login", data={"pin": "111111", "next": "/", "token": _token()})
    html = page.get_data(as_text=True)
    assert "Too many wrong tries" in html
    assert "That is not the PIN." not in html


# ---------------------------------------------------------------------------
# When the count cannot be kept at all (2026-09-05)
# ---------------------------------------------------------------------------

def test_a_count_that_cannot_be_written_says_so(monkeypatch):
    """The throttle's own failure has to be reportable, or it is invisible.

    `_save_attempts` used to swallow this and return nothing, which made "the
    wait is working" and "there is no wait" the same value to every caller.
    """
    from aki_agent import atomic

    assert dashboard_auth.record_failure() is True

    def refuse(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(atomic, "write_text", refuse)
    assert dashboard_auth.record_failure() is False


def test_an_unwritable_count_still_lets_the_owner_keep_trying(monkeypatch):
    """On this machine the old trade stands: a broken throttle must not be a
    door that will not open. The refusal added for remote access is in the
    login route, not here, precisely so this stays true."""
    from aki_agent import atomic

    monkeypatch.setattr(atomic, "write_text",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    dashboard_auth.record_failure()
    held, _seconds = dashboard_auth.locked_out()
    assert not held


def test_a_wrong_pin_from_away_is_refused_when_it_cannot_be_counted(
        tmp_path, monkeypatch):
    """The finding this pair of changes exists for (2026-09-05).

    Remote access on + a count that will not write = a six-digit PIN facing
    the internet with nothing slowing anything down. The door has to close
    rather than answer quickly and imply a limit it is not keeping.
    """
    import shutil
    from pathlib import Path as _Path

    from aki_agent import (atomic, config as config_module,
                           exposure as exposure_module, secrets as secrets_module)
    from aki_agent.dashboard import app as app_module
    from aki_agent.dashboard import create_app

    kept: dict[str, str] = {}
    monkeypatch.setattr(secrets_module, "get_secret", kept.get)
    monkeypatch.setattr(secrets_module, "set_secret",
                        lambda key, value: kept.__setitem__(key, value))
    dashboard_auth.set_pin("481920")

    example = (_Path(__file__).resolve().parents[1]
               / "configs" / "examples" / "architecture.yaml")
    target = tmp_path / "config.yaml"
    shutil.copy(example, target)
    loaded = config_module.load(target)
    loaded.layout.root = example.parent
    config_module.save(loaded, target)

    assert exposure_module.turn_on("away.example.org")[0]

    app = create_app(target)
    app.config["TESTING"] = True

    def post_a_wrong_pin(host):
        with app.test_client() as browser:
            return browser.post(
                "/login",
                data={"pin": "000001", "token": app_module.SESSION_TOKEN},
                headers={"Host": host},
            )

    # The count still writes: the door answers in the ordinary way.
    assert b"not the PIN" in post_a_wrong_pin("away.example.org").data

    monkeypatch.setattr(atomic, "write_text",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))

    away = post_a_wrong_pin("away.example.org")
    assert b"Remote sign-in is closed" in away.data
    assert b"not the PIN" not in away.data, (
        "a refused remote attempt must not also report whether the PIN was "
        "right -- that is one bit per try, which is what the wait denies")

    # And the person at the keyboard is not shut out by the same fault.
    assert b"not the PIN" in post_a_wrong_pin("127.0.0.1").data
