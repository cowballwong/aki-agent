"""The dashboard chat box, signed in as the user.

The point of these is the *shape*: one conversation, not two stores kept in
step by hand. Most of them check that nothing here invents a second copy, and
that the things which are secret stay secret.
"""

from __future__ import annotations

import pytest

from aki_agent import paths, telegram_chat


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    telegram_chat._BOT_USERNAME = None
    telegram_chat._AUTH.update({"phone": None, "hash": None})
    yield


# ---------------------------------------------------------------------------
# The two values from my.telegram.org
# ---------------------------------------------------------------------------

def test_the_api_id_must_look_like_an_id():
    ok, message = telegram_chat.save_credentials("not-a-number", "x" * 32)
    assert not ok
    assert "digits only" in message


def test_the_api_hash_must_look_like_a_hash():
    ok, message = telegram_chat.save_credentials("1234567", "short")
    assert not ok
    assert "does not look like one" in message


def test_a_good_pair_is_kept_and_read_back(monkeypatch):
    store = {}
    monkeypatch.setattr(telegram_chat.secrets, "set_secret",
                        lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(telegram_chat.secrets, "get_secret", store.get)

    assert telegram_chat.save_credentials("1234567", "a" * 32)[0]
    assert telegram_chat.credentials() == (1234567, "a" * 32)


def test_credentials_go_to_the_password_store_not_the_config(monkeypatch):
    """The config file gets backed up, copied between machines and pasted into
    support conversations. These two identify the application that may sign
    somebody in."""
    seen = []
    monkeypatch.setattr(telegram_chat.secrets, "set_secret",
                        lambda key, value: seen.append(key))

    telegram_chat.save_credentials("1234567", "a" * 32)

    assert seen == ["telegram_api_id", "telegram_api_hash"]


def test_a_corrupt_stored_id_reads_as_absent(monkeypatch):
    monkeypatch.setattr(telegram_chat.secrets, "get_secret",
                        lambda key: "not-a-number")
    assert telegram_chat.credentials() == (None, None)


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def test_a_phone_without_a_country_code_is_refused():
    result = telegram_chat.send_code("07821736659")
    assert not result["ok"]
    assert "country code" in result["error"]


def test_an_empty_phone_is_refused():
    assert not telegram_chat.send_code("")["ok"]


def test_a_code_with_no_request_behind_it_is_refused():
    """The step expires. Better to say so than to fail inside Telethon."""
    result = telegram_chat.sign_in("12345")
    assert not result["ok"]
    assert "expired" in result["error"]


def test_the_phone_and_code_are_never_written_down():
    """They are used once. Only the session file survives a sign-in, and that
    is the thing the page warns about."""
    import inspect

    source = inspect.getsource(telegram_chat)
    body = source.split("def send_code")[1].split("def sign_out")[0]

    for writing in ("set_secret", "write_text", "write_json", "atomic."):
        assert writing not in body, f"sign-in must not persist anything: {writing}"


def test_the_session_file_lives_in_the_assistants_own_state():
    assert telegram_chat.session_file().parent == paths.state_dir()
    assert telegram_chat.session_file().suffix == ".session"


# ---------------------------------------------------------------------------
# Before it is set up
# ---------------------------------------------------------------------------

def test_a_missing_library_is_a_state_not_a_crash(monkeypatch):
    monkeypatch.setattr(telegram_chat, "installed", lambda: False)

    ready = telegram_chat.status()

    assert ready["library"] is False
    assert ready["signed_in"] is False
    assert "not installed" in telegram_chat.next_step(ready)


def test_every_stage_has_a_sentence_saying_what_is_missing():
    """A status page that shows three red badges and no next step is a status
    page that gets ignored."""
    stages = [
        {"library": False, "credentials": False, "signed_in": False, "bot": ""},
        {"library": True, "credentials": False, "signed_in": False, "bot": ""},
        {"library": True, "credentials": True, "signed_in": False, "bot": ""},
        {"library": True, "credentials": True, "signed_in": True, "bot": ""},
        {"library": True, "credentials": True, "signed_in": True, "bot": "x"},
    ]
    said = [telegram_chat.next_step(one) for one in stages]

    assert all(said), "every stage must say something"
    assert len(set(said)) == len(said), "and each stage a different thing"


def test_sending_with_no_bot_configured_says_so(monkeypatch):
    monkeypatch.setattr(telegram_chat, "bot_username", lambda: "")
    result = telegram_chat.send("hello")
    assert not result["ok"]
    assert "bot token" in result["error"]


def test_history_with_no_bot_returns_no_turns(monkeypatch):
    monkeypatch.setattr(telegram_chat, "bot_username", lambda: "")
    result = telegram_chat.history()
    assert result["turns"] == []


def test_the_bot_name_is_looked_up_not_asked_for(monkeypatch):
    """Asking somebody for a value the software can look up is a question that
    exists only because nobody wrote the lookup."""
    from aki_agent import telegram_setup

    monkeypatch.setattr(telegram_setup, "read_token", lambda: "")
    assert telegram_chat.bot_username() == ""


def test_a_failed_check_is_not_reported_as_not_signed_in(monkeypatch):
    """Collapsing "could not tell" into "no" cost an hour.

    The maintainer signed in, the page said `Signed in: no`, and every reasonable
    reading of that is "my sign-in failed" rather than "the check failed".
    They need different answers because they need different actions.
    """
    monkeypatch.setattr(telegram_chat, "installed", lambda: True)
    monkeypatch.setattr(telegram_chat, "credentials", lambda: (1, "x" * 32))

    def broken():
        raise OSError("the loop went away")

    monkeypatch.setattr(telegram_chat, "_client", broken)

    ready = telegram_chat.status()

    assert ready["signed_in"] is False
    assert ready["problem"], "the reason must survive"
    assert "Could not check" in telegram_chat.next_step(ready)


def test_a_clean_check_reports_no_problem(monkeypatch):
    monkeypatch.setattr(telegram_chat, "installed", lambda: True)
    monkeypatch.setattr(telegram_chat, "credentials", lambda: (1, "x" * 32))

    class Link:
        def is_user_authorized(self):
            return False

        def disconnect(self):
            pass

    monkeypatch.setattr(telegram_chat, "_client", Link)

    ready = telegram_chat.status()

    assert ready["problem"] == ""
    assert "Not signed in yet" in telegram_chat.next_step(ready)
