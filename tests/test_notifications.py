"""The notification gate's four rules, each tested directly.

Every rule here was learned by something going wrong. A test per rule means
that when someone later "simplifies" the gate, they find out which lesson they
just deleted.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from fake_credentials import FAKE_HEX_KEY
from aki_agent import channels, notify, paths
from aki_agent.channels import Message
from aki_agent.config import Config, Notifications


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Give every test its own home folder, so nothing touches the real one."""
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    channels.reset_to_defaults()
    yield


def make_config(**kwargs) -> Config:
    config = Config()
    config.notifications = Notifications(**kwargs)
    return config


# ---------------------------------------------------------------------------
# RULE 1 — an unregistered channel defaults to ON
# ---------------------------------------------------------------------------

def test_a_channel_nobody_configured_is_on():
    """Fail towards being heard.

    A sender that is silently off goes missing for weeks. A sender that is too
    noisy gets switched off in one click. Those are not symmetrical failures,
    so the default is not symmetrical either.
    """
    config = make_config(enabled=True, channels={})
    decision = notify.decide(Message("anything"), config, "brand-new-channel")
    assert decision.deliver is True


def test_a_channel_explicitly_switched_off_stays_off():
    config = make_config(enabled=True, channels={"file": False})
    decision = notify.decide(Message("anything"), config, "file")
    assert decision.deliver is False
    assert "switched off" in decision.reason


# ---------------------------------------------------------------------------
# RULE 2 — suppressed means held, never dropped
# ---------------------------------------------------------------------------

def test_a_suppressed_message_is_held_not_lost():
    config = make_config(enabled=False)

    decision = notify.send("the roof is leaking", config, "file")

    assert decision.deliver is False
    held = notify.read_held()
    assert len(held) == 1
    assert held[0]["text"] == "the roof is leaking"
    assert held[0]["reason"]


def test_everything_held_comes_back_as_one_digest():
    config = make_config(enabled=False)
    for index in range(3):
        notify.send(f"thing {index}", config, "file")
    assert notify.held_count() == 3

    # Suppression lifts.
    config.notifications.enabled = True
    count, decision = notify.release(config, "file")

    assert count == 3
    assert decision.deliver is True
    assert notify.held_count() == 0

    delivered = (paths.log_dir() / "messages.md").read_text(encoding="utf-8")
    for index in range(3):
        assert f"thing {index}" in delivered


def test_the_queue_is_not_cleared_when_the_digest_could_not_be_sent():
    """Clearing on an unverified send is exactly how held messages vanish."""
    config = make_config(enabled=False)
    notify.send("something", config, "file")

    # Still suppressed: the digest cannot go out either.
    count, decision = notify.release(config, "file")

    assert decision.deliver is False
    assert notify.held_count() >= 1, (
        "the queue was cleared even though the digest was never delivered"
    )


def test_no_path_through_send_loses_a_message():
    """Whatever happens, the message is either delivered or queued."""
    config = make_config(enabled=True)

    class BrokenChannel:
        name = "broken"

        def available(self):
            return True

        def deliver(self, message):
            return False, "the transport fell over"

    channels.register(BrokenChannel())
    decision = notify.send("important", config, "broken")

    assert decision.deliver is False
    assert notify.held_count() == 1


def test_an_unknown_channel_name_holds_rather_than_discards():
    config = make_config(enabled=True)
    decision = notify.send("important", config, "not-a-real-channel")
    assert decision.deliver is False
    assert notify.held_count() == 1


# ---------------------------------------------------------------------------
# RULE 3 — urgency breaks through, and quiet hours are handled properly
# ---------------------------------------------------------------------------

def test_urgent_breaks_through_a_mute():
    config = make_config(enabled=False)
    decision = notify.decide(Message("fire", urgent=True), config, "file")
    assert decision.deliver is True


def test_configured_urgent_words_break_through():
    config = make_config(enabled=True, quiet_hours=("22:00", "07:00"),
                         urgent_keywords=("burst pipe",))
    middle_of_the_night = _dt.datetime(2026, 8, 16, 3, 0)

    routine = notify.decide(Message("weekly summary"), config, "file",
                            now=middle_of_the_night)
    urgent = notify.decide(Message("there is a burst pipe"), config, "file",
                           now=middle_of_the_night)

    assert routine.deliver is False
    assert urgent.deliver is True


def test_quiet_hours_that_cross_midnight_work():
    """22:00-07:00 is 'after 22 OR before 7', not 'after 22 AND before 7'.

    The naive version of this check is always false, so quiet hours simply
    never apply and nobody notices until they are woken up.
    """
    config = make_config(enabled=True, quiet_hours=("22:00", "07:00"))

    def deliver_at(hour):
        return notify.decide(Message("hello"), config, "file",
                             now=_dt.datetime(2026, 8, 16, hour, 0)).deliver

    assert deliver_at(23) is False       # after the start
    assert deliver_at(3) is False        # after midnight, before the end
    assert deliver_at(9) is True         # daytime
    assert deliver_at(21) is True        # before the start


def test_a_malformed_quiet_window_does_not_mute_everything():
    """A typo in the config must not silence the assistant entirely."""
    config = make_config(enabled=True, quiet_hours=("not a time", "07:00"))
    decision = notify.decide(Message("hello"), config, "file")
    assert decision.deliver is True


# ---------------------------------------------------------------------------
# RULE 4 — honesty about what the gate does and does not guarantee
# ---------------------------------------------------------------------------

def test_the_module_states_its_own_limitation():
    """The gate cannot stop code that bypasses it, and says so.

    'It cannot send while muted' would be a stronger claim and an untrue one.
    A safety promise that is not quite true is worse than an honest limit,
    because people rely on it.
    """
    import inspect

    text = inspect.getdoc(notify) or ""
    assert "bypass" in text.lower()


# ---------------------------------------------------------------------------
# Redaction at the boundary
# ---------------------------------------------------------------------------

def test_a_credential_never_leaves_in_a_notification():
    """The one thing in the system designed to leave the machine."""
    config = make_config(enabled=True)
    notify.send(f'api_key = "{FAKE_HEX_KEY}"', config, "file")

    delivered = (paths.log_dir() / "messages.md").read_text(encoding="utf-8")
    assert FAKE_HEX_KEY not in delivered
    assert "redacted" in delivered
