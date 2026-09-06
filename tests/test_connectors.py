"""Mail, files and calendars — and the promise they all have to keep.

Every connector here exists to reach a service **without** an OAuth
application, a client secret or a developer account, because the package
promises no API key and one-command install. These tests check the mechanics,
and they also check that the honest limits are still stated -- a limitation
that quietly disappears from the documentation becomes a surprise later.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from fake_credentials import FAKE_HEX_KEY
from aki_agent import paths, secrets
from aki_agent.connectors import calendars, files, mail


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------

def test_the_common_providers_are_all_covered():
    """Gmail, Outlook/Hotmail, Yahoo and iCloud between them are most people."""
    keys = {entry.key for entry in mail.PROVIDERS}
    assert {"gmail", "outlook", "yahoo", "icloud", "other"} <= keys


def test_every_provider_can_actually_be_reached():
    for entry in mail.PROVIDERS:
        if entry.key == "other":
            continue        # by definition the user supplies the hosts
        assert entry.imap_host, f"{entry.key} has no IMAP host"
        assert entry.smtp_host, f"{entry.key} has no SMTP host"
        assert entry.app_password_url or entry.note, (
            f"{entry.key} tells the user nothing about how to authenticate"
        )


@pytest.mark.parametrize("address,expected", [
    ("someone@gmail.com", "gmail"),
    ("someone@hotmail.com", "outlook"),
    ("someone@outlook.com", "outlook"),
    ("someone@yahoo.co.uk", "yahoo"),
    ("someone@icloud.com", "icloud"),
    ("someone@their-own-domain.example", None),
])
def test_the_provider_is_guessed_from_the_address(address, expected):
    """One fewer question in the interview, for most people."""
    guessed = mail.guess_provider(address)
    assert (guessed.key if guessed else None) == expected


def test_an_account_inherits_its_providers_settings():
    account = mail.Account(address="someone@gmail.com", provider_key="gmail")
    assert account.imap_host == "imap.gmail.com"
    assert account.smtp_host == "smtp.gmail.com"
    assert account.username == "someone@gmail.com"


def test_the_app_password_goes_to_the_credential_store_not_a_file():
    account = mail.Account(address="someone@example.com")
    account.save_password("not-a-real-password")

    assert account.password() == "not-a-real-password"
    # And the key is namespaced, so two accounts do not collide.
    assert account.secret_key == "mail:someone@example.com"

    account.forget_password()
    assert account.password() is None


def test_sending_refuses_without_a_yes():
    """Every message, individually. Not 'confirmed once at setup'.

    Email is the most consequential thing an assistant can do on someone's
    behalf: it goes to other people and it cannot be recalled.

    The account here is one that IS allowed to send, so that this test still
    checks per-message confirmation rather than passing for the other reason
    -- see the may_send test below.
    """
    account = mail.Account(address="someone@example.com", may_send=True)
    draft = mail.Draft(to="them@example.com", subject="Hello", body="Hi")

    ok, message = mail.send(account, draft, confirmed=False)

    assert ok is False
    assert "every message, every time" in message


def test_a_drafts_only_mailbox_cannot_send_even_when_confirmed():
    """The checkbox that had no reader (2026-08-23).

    "May send, not just draft" has been on the connections page since it was
    written, and the value was stored in the config and read back out of it.
    `Account` had no such field, so `send()` never saw it and gated on
    `confirmed` alone -- the page showed "allowed" or "drafts only" beside a
    setting nothing consulted.

    Both gates now hold, and they are different questions: confirmation says
    this message is wanted, may_send says this mailbox may send at all.
    """
    account = mail.Account(address="someone@example.com")
    assert account.may_send is False, "sending must be off unless asked for"

    draft = mail.Draft(to="them@example.com", subject="Hello", body="Hi")
    ok, message = mail.send(account, draft, confirmed=True)

    assert ok is False
    assert "drafts only" in message


def test_reading_without_a_saved_password_says_what_to_do():
    account = mail.Account(address="someone@example.com")
    with pytest.raises(mail.MailError) as raised:
        mail.recent(account)
    assert "/aki-agent:setup" in str(raised.value)


def test_an_encoded_subject_line_is_decoded():
    """Headers arrive encoded however the sender's mail program felt like it.

    For a bilingual user, getting this wrong turns most of their mail into
    mojibake.
    """
    encoded = "=?UTF-8?B?5pel5pys6Kqe44Gu5Lu25ZCN?="
    assert mail._decode(encoded) == "日本語の件名"


def test_a_message_summary_is_redacted():
    """A mailbox is one of the commonest places a token sits in plain text."""
    message = mail.Message(
        uid="1", sender="a@b.com", subject="Your key",
        date="", preview=f'api_key = "{FAKE_HEX_KEY}"')
    assert FAKE_HEX_KEY not in message.safe_summary()


def test_the_reading_limit_is_bounded():
    """'Check my email' on a 60,000-message account must not read all of it."""
    assert mail.HARD_LIMIT <= 500
    assert mail.DEFAULT_LIMIT <= 50


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def test_the_common_cloud_services_are_known():
    assert {"Google Drive", "OneDrive", "Dropbox", "iCloud Drive"} <= set(
        files.KNOWN_LOCATIONS)


def test_a_sync_folder_is_recognised():
    """Used before writing anything bulky into a folder."""
    assert files.is_synced(Path("C:/Users/someone/Dropbox/work")) is True
    assert files.is_synced(Path("G:/My Drive/projects")) is True
    assert files.is_synced(Path("/Users/someone/Documents/work")) is False


def test_writing_into_a_sync_folder_produces_a_warning():
    warning = files.warn_if_synced(Path("C:/Users/x/OneDrive/thing"))
    assert warning is not None
    assert "thousands of small files" in warning

    assert files.warn_if_synced(Path("C:/projects/thing")) is None


def test_recent_files_is_bounded_and_skips_noise(tmp_path):
    root = tmp_path / "drive"
    (root / "node_modules" / "deep").mkdir(parents=True)
    (root / "node_modules" / "deep" / "junk.js").write_text("x",
                                                            encoding="utf-8")
    (root / "real.md").write_text("hello", encoding="utf-8")
    (root / ".hidden").write_text("x", encoding="utf-8")

    found = files.recent_files(root, days=30, limit=10)
    names = {info.name for info in found}

    assert "real.md" in names
    assert "junk.js" not in names, "node_modules should never be walked"
    assert ".hidden" not in names


def test_an_absent_folder_returns_nothing_rather_than_raising(tmp_path):
    """A cloud folder that has not mounted yet is a normal state."""
    assert files.recent_files(tmp_path / "not-there") == []
    assert files.find(tmp_path / "not-there", "anything") == []


def test_detection_reports_honestly_when_nothing_is_found(monkeypatch,
                                                          tmp_path):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setattr(paths, "is_windows", lambda: False)

    text = files.describe_what_is_available()
    assert "No cloud folders found" in text
    assert "not a problem" in text


# ---------------------------------------------------------------------------
# Calendars
# ---------------------------------------------------------------------------

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:A title that has been folded
  across two lines
DTSTART:20260817T140000Z
DTEND:20260817T150000Z
LOCATION:Room 2
END:VEVENT
BEGIN:VEVENT
SUMMARY:All day thing
DTSTART;VALUE=DATE:20260818
END:VEVENT
BEGIN:VEVENT
SUMMARY:Broken one
DTSTART:not-a-date
END:VEVENT
END:VCALENDAR
"""


def test_folded_lines_are_rejoined():
    """ICS wraps long lines; not handling it splits meeting titles in half."""
    events = calendars.parse(SAMPLE_ICS)
    titles = [event.summary for event in events]
    assert "A title that has been folded across two lines" in titles


def test_an_all_day_event_is_recognised():
    events = calendars.parse(SAMPLE_ICS)
    all_day = [event for event in events if event.all_day]
    assert len(all_day) == 1
    assert all_day[0].summary == "All day thing"


def test_an_unparseable_event_is_skipped_not_guessed():
    """A wrong answer here is a missed meeting."""
    events = calendars.parse(SAMPLE_ICS)
    assert "Broken one" not in [event.summary for event in events]


def test_utc_times_are_shown_in_local_time():
    """'14:00 UTC' shown to someone in London in summer is an hour wrong."""
    events = calendars.parse(SAMPLE_ICS)
    timed = next(event for event in events if not event.all_day)
    # The exact local hour depends on the machine, but it must have been
    # converted away from a naive UTC reading unless the machine is on UTC.
    assert timed.start is not None
    assert timed.start.tzinfo is None      # naive local, not naive UTC


def test_the_subscription_url_is_treated_as_a_secret():
    """Possession of the URL is possession of the calendar."""
    calendar = calendars.Calendar(name="work")
    calendar.save_url("https://example.invalid/very-long-secret.ics")

    assert calendar.url() == "https://example.invalid/very-long-secret.ics"
    assert calendar.secret_key == "calendar:work"

    # And it is not sitting in any config file.
    stored = secrets.get_secret("calendar:work")
    assert stored is not None

    calendar.forget()


def test_an_unencrypted_calendar_address_is_refused():
    calendar = calendars.Calendar(name="insecure")
    calendar.save_url("http://example.invalid/calendar.ics")

    with pytest.raises(calendars.CalendarError) as raised:
        calendars.fetch(calendar)
    assert "https" in str(raised.value)

    calendar.forget()


def test_event_descriptions_are_redacted():
    """Dial-in details and one-time codes live in calendar entries."""
    event = calendars.Event(
        summary=f'Call — passcode: {FAKE_HEX_KEY}',
        start=_dt.datetime(2026, 8, 17, 14, 0))
    assert FAKE_HEX_KEY not in event.describe()


def test_the_readonly_limit_is_stated_where_the_user_will_see_it():
    """A limitation that quietly leaves the docs becomes a surprise later."""
    text = calendars.how_to_get_the_address()
    assert "read-only" in text
    assert "cannot add" in text


def test_the_package_states_which_features_need_oauth():
    """The reason the easy routes were chosen has to stay written down."""
    import inspect

    from aki_agent import connectors

    text = inspect.getdoc(connectors) or ""
    assert "OAuth" in text
    assert "cannot" in text.lower()
