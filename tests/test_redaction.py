"""The secret redactor, tested from both directions.

A redactor has two ways to fail and they are not equally bad, but they are
both real:

  MISSES a secret   -> a live token ends up in a log file that gets pasted
                       into a class chat. This is the one that matters.
  EATS everything   -> the logs become unreadable, so somebody switches the
                       redactor off, and then failure one happens anyway.

So both directions are tested. The bias is deliberately towards over-redaction
when the two conflict -- but "over-redaction" has to mean tokens, not every
long word in the file.
"""

from __future__ import annotations

import pytest

from fake_credentials import (FAKE_HEX_KEY,
                              LINES_THAT_MUST_BE_REDACTED,
                              LINES_THAT_MUST_SURVIVE)
from aki_agent.secrets import redact


# ---------------------------------------------------------------------------
# Things that MUST be hidden
# ---------------------------------------------------------------------------

SHOULD_REDACT = LINES_THAT_MUST_BE_REDACTED


@pytest.mark.parametrize("line", SHOULD_REDACT)
def test_credential_shapes_are_hidden(line):
    cleaned = redact(line)
    assert "[redacted]" in cleaned, f"nothing was redacted in: {line}"


def test_the_secret_value_itself_does_not_survive():
    """Redacting must remove the value, not merely mention it."""
    secret_value = FAKE_HEX_KEY
    cleaned = redact(f'api_key = "{secret_value}"')
    assert secret_value not in cleaned


# ---------------------------------------------------------------------------
# Things that MUST survive
# ---------------------------------------------------------------------------

SHOULD_SURVIVE = LINES_THAT_MUST_SURVIVE


@pytest.mark.parametrize("line", SHOULD_SURVIVE)
def test_ordinary_text_is_left_alone(line):
    assert redact(line) == line, (
        "the redactor changed text that is not a credential. Over-redaction "
        "makes logs unreadable, which gets the redactor switched off."
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_and_none_are_safe():
    assert redact("") == ""
    assert redact(None) is None


def test_redaction_is_stable():
    """Redacting twice must not change the result again.

    Logs get processed more than once. A redactor whose output is itself
    redactable produces creeping damage that is very hard to trace back.
    """
    once = redact(f'api_key = "{FAKE_HEX_KEY}"')
    assert redact(once) == once


# ---------------------------------------------------------------------------
# A credential store that cannot be reached (2026-08-20)
# ---------------------------------------------------------------------------

def test_an_unreachable_store_reads_as_no_secret(monkeypatch):
    """Windows Credential Manager belongs to an interactive logon. Read it
    without one — over SSH, from a service — and it raises WinError 1312.

    That exception used to come straight out of `get_secret`, so asking "is a
    Telegram API id saved" produced a nine-frame traceback ending in
    `win32cred.CredRead`. To every caller, a secret that cannot be read is the
    same as one that was never stored.
    """
    from aki_agent import secrets as secrets_module

    class Refusing:
        def get_password(self, service, key):
            raise OSError("[WinError 1312] A specified logon session does not "
                          "exist")

    monkeypatch.setattr(secrets_module, "_keyring_or_none", lambda: Refusing())

    assert secrets_module.get_secret("anything") is None


def test_but_something_can_still_say_why(monkeypatch):
    """Reading a secret is forgiving; telling somebody their passwords are
    unreachable is explicit. Those are different jobs."""
    from aki_agent import secrets as secrets_module

    class Refusing:
        def get_password(self, service, key):
            raise OSError("[WinError 1312] no logon session")

    monkeypatch.setattr(secrets_module, "_keyring_or_none", lambda: Refusing())

    said = secrets_module.store_unavailable()

    assert "1312" in said
    assert "interactive logon" in said


def test_a_working_store_reports_nothing_wrong(monkeypatch):
    from aki_agent import secrets as secrets_module

    class Fine:
        def get_password(self, service, key):
            return None

    monkeypatch.setattr(secrets_module, "_keyring_or_none", lambda: Fine())

    assert secrets_module.store_unavailable() == ""
