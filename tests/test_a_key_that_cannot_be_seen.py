"""A key that was saved and cannot be found, which is not the same as no key.

A key entered on the dashboard's API keys page, and an assistant that went on
saying it was missing: the service stayed unavailable, and the user was sent
to fetch a key they already had.

There are two ways that happens and only one of them is "no key":

  1. the two halves of the package disagree about where secrets live. The
     dashboard runs from the engine's environment; a session runs from
     whichever Python started it. One imports `keyring` and writes to the
     password manager, the other does not and reads a file. Both succeed.
  2. the credential store is there and cannot be read from this session -- no
     interactive logon, over SSH, from a scheduled context.

Neither raises anything, and `has_key` answered False for both.
"""

from __future__ import annotations

import json

import pytest

from aki_agent import apis, secrets


@pytest.fixture
def no_keyring(monkeypatch):
    """A process that cannot import a keyring: the file half."""
    monkeypatch.setattr(secrets, "_keyring_or_none", lambda: None)


class _Keyring:
    """The other half: a working password manager, holding nothing."""

    def __init__(self, held=None):
        self.held = held or {}

    def get_password(self, service, key):
        return self.held.get(key)

    def set_password(self, service, key, value):
        self.held[key] = value


def test_a_key_written_by_the_file_half_is_found_by_the_keyring_half(
        monkeypatch, tmp_path):
    """The bug. Saved by one process, invisible to the other, no error."""
    monkeypatch.setattr(secrets, "_fallback_path", lambda: tmp_path / "keys.json")
    (tmp_path / "keys.json").write_text(
        json.dumps({"api:minimax": "written-without-a-keyring"}), encoding="utf-8")

    monkeypatch.setattr(secrets, "_keyring_or_none", lambda: _Keyring())

    assert secrets.get_secret("api:minimax") == "written-without-a-keyring"
    assert apis.has_key("minimax")


def test_where_it_is_can_be_reported_without_reading_it(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets, "_fallback_path", lambda: tmp_path / "keys.json")
    (tmp_path / "keys.json").write_text(
        json.dumps({"api:minimax": "secret"}), encoding="utf-8")
    monkeypatch.setattr(secrets, "_keyring_or_none", lambda: _Keyring())

    assert secrets.where_is("api:minimax") == "file"
    assert secrets.where_is("api:nothing_here") == ""


def test_the_password_manager_still_wins_when_it_has_the_key(monkeypatch, tmp_path):
    """The fallback is a second place to look, never a replacement."""
    monkeypatch.setattr(secrets, "_fallback_path", lambda: tmp_path / "keys.json")
    (tmp_path / "keys.json").write_text(
        json.dumps({"api:minimax": "the-old-one"}), encoding="utf-8")
    monkeypatch.setattr(
        secrets, "_keyring_or_none", lambda: _Keyring({"api:minimax": "the-real-one"}))

    assert secrets.get_secret("api:minimax") == "the-real-one"
    assert secrets.where_is("api:minimax") == "os"


def test_nothing_anywhere_is_still_nothing(monkeypatch, tmp_path):
    """The fix must not turn a missing key into a found one."""
    monkeypatch.setattr(secrets, "_fallback_path", lambda: tmp_path / "keys.json")
    monkeypatch.setattr(secrets, "_keyring_or_none", lambda: _Keyring())

    assert secrets.get_secret("api:minimax") is None
    assert not apis.has_key("minimax")


def test_the_listing_says_which_store_holds_it(monkeypatch, tmp_path):
    """So the reader can tell "you have no key" from "this half cannot see it"."""
    from aki_agent.config import ApiTool, Config

    monkeypatch.setattr(secrets, "_fallback_path", lambda: tmp_path / "keys.json")
    (tmp_path / "keys.json").write_text(
        json.dumps({"api:minimax": "secret"}), encoding="utf-8")
    monkeypatch.setattr(secrets, "_keyring_or_none", lambda: _Keyring())

    config = Config()
    config.connections.apis = (ApiTool(tool="minimax", jobs=("speech",)),)

    row = apis.listing(config)[0]

    assert row["has_key"] is True
    assert row["key_where"] == "file"
    assert "secret" not in json.dumps(row), "the value must never be in the row"
