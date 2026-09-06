"""Invented credential shapes, kept in one place on purpose.

WHY THIS FILE EXISTS
--------------------
Several tests need something that *looks* like a credential — to prove the
redactor catches it, to prove a notification cannot carry one out, to prove a
trace does not record one.

Those strings trip the repository's own credential scan, which is exactly what
that scan is for. The scan has an allowlist, and the allowlist has a hard
limit of two files, because every entry is a place a real secret could hide.

When a third test needed a fake credential, the choice was: widen the
allowlist, or stop scattering the fakes. Widening an allowlist to make a check
quieter is how checks stop meaning anything. So the fakes live here, in one
file, which is the single allowlisted place, and every test imports from it.

**Nothing in this file is real.** Every value was made up while writing the
tests. None has ever authenticated anything, and none is derived from a real
credential.
"""

from __future__ import annotations

# A 32-character hex-shaped value: the commonest API-key shape.
FAKE_HEX_KEY = "9f8c2b7a4e1d6035ab9c8e7f2d1a4b6c"

# A second one, so tests can tell two apart.
FAKE_HEX_TOKEN = "4f3a9b2c8e7d1650fa3b9c2e8d7f1a64"

# A base64-shaped value with no word structure at all.
FAKE_OPAQUE_TOKEN = "aGVsbG8gd29ybGQgdGhpcyBpczEyMzQ1Njc4OTAxMg"

# A JWT-shaped header value.
FAKE_BEARER = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"

# Complete lines as they would appear in a config file or a log.
LINES_THAT_MUST_BE_REDACTED = [
    f'api_key = "{FAKE_HEX_KEY}"',
    f"API_KEY: {FAKE_HEX_KEY}",
    'password = "hunter2-not-a-real-one"',
    f"token: {FAKE_HEX_TOKEN}",
    f"Authorization: Bearer {FAKE_BEARER}",
    "secret=abcd1234efgh5678",
    f"the value is {FAKE_OPAQUE_TOKEN}",
]

# Ordinary text that must survive untouched. Over-redaction makes logs
# unreadable, which gets the redactor switched off, which causes the leak it
# was meant to prevent.
LINES_THAT_MUST_SURVIVE = [
    "test_engine_source_contains_no_profession_vocabulary",
    "test_credential_shapes_are_hidden",
    "MINIMUM_SUPPORTED_PYTHON_VERSION_FOR_THIS_PACKAGE",
    "a-very-long-kebab-case-file-name-for-something",
    "supercalifragilisticexpialidocious",
    "C:/Users/someone/.aki-agent/config.yaml",
    "Everything is working, and the workspace folder was found as expected.",
]

# A Telegram-bot-shaped token: digits, a colon, then a long secret.
# Invented. It has never existed on Telegram.
FAKE_BOT_TOKEN = "1234567890:AAH" + "fakefakefakefakefakefakefake"

# A key sitting in a URL's query string -- the leak the URL exemption in
# `secrets.scan_for_committed_secrets` must keep catching, now that plain
# citation links are exempt from the bare-token rule.
FAKE_URL_WITH_KEY = (
    "https://api.example.com/v1/thing?api_key=" + FAKE_HEX_KEY)

# The same, in the other common shape.
FAKE_URL_WITH_TOKEN = (
    "https://example.dev/callback?token=sk-ant-api03-" + FAKE_HEX_TOKEN)

# A long, entirely innocent citation URL: a government PDF with a descriptive
# file name. Flagging this is what would drive somebody to widen the
# allowlist, so there is a test proving it is not flagged.
INNOCENT_LONG_URL = (
    "https://www.example.gov.hk/content/dam/data/publications/media/"
    "reports/2026/Construction-Manpower-Forecast-Results_e20260410.pdf")
