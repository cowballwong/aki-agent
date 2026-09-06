"""The notification gate — everything the assistant says to its user goes here.

FOUR RULES, EACH LEARNED BY SOMETHING GOING WRONG
--------------------------------------------------

**1. An unregistered channel defaults to ON.**
A new sender that is silently off goes missing for weeks and nobody finds out
it existed. A new sender that is too noisy announces itself and gets switched
off in one click. Those failures are not symmetrical, so the default is not
symmetrical either. Fail towards being heard.

**2. A suppressed message is held, not dropped.**
When suppression lifts, everything held is delivered as one digest. A message
that vanishes during quiet hours is worse than a noisy one, because the user
never learns it existed and cannot even know to ask.

**3. Suppression stops the broadcast, never the work.**
Being quiet is a delivery decision. Scheduled work carries on; only the
outbound message waits. If muting the assistant also stopped it working, a
user would have to choose between a quiet evening and a working assistant.

**4. A static check is not a runtime guarantee.**
The source system enforces "every sender goes through the gate" with a lint
rule, and it is worth being precise about what that buys: it catches every
sender we know about, and fails when a new one appears. It does NOT make it
impossible to send while muted -- any code can import a transport directly and
bypass this module entirely.

That distinction is stated here rather than glossed, because "it cannot send
while muted" is a promise this design does not actually make, and a safety
promise that is not quite true is worse than an honest limitation.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, asdict
from pathlib import Path

from . import atomic, channels, events, paths
from .channels import Message


def held_queue_path() -> Path:
    return paths.state_dir() / "held-messages.json"


@dataclass
class Decision:
    """What the gate decided, and why. The `why` is shown in the dashboard."""

    deliver: bool
    reason: str
    channel: str = ""


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

def decide(message: Message, config, channel_name: str,
           now: _dt.datetime | None = None, mode=None) -> Decision:
    """Should this go out right now?

    Pure function: no IO, no side effects. That is what makes the gate's
    behaviour testable without a machine that can actually send anything --
    which is also why `mode` arrives as an argument rather than being looked
    up here. `send()` does the reading; this decides.

    `mode` is the `quiet.Mode` this particular message's task has been given,
    or None for the one window that applies to everything. A task's own mode
    replaces the global window rather than adding to it: two overlapping
    silences would be impossible to reason about from the page.
    """
    now = now or _dt.datetime.now()
    notifications = config.notifications

    if not notifications.enabled:
        if _is_urgent(message, config):
            return Decision(True, "urgent, so it breaks through the mute",
                            channel_name)
        return Decision(False, "notifications are switched off", channel_name)

    # RULE 1: a channel nobody has registered an opinion about is ON.
    if not notifications.channel_enabled(channel_name):
        return Decision(False, f"the {channel_name} channel is switched off",
                        channel_name)

    quiet_now = (mode.holds(now) if mode is not None
                 else _in_quiet_hours(notifications.quiet_hours, now))
    if quiet_now:
        named = f"quiet: {mode.name}" if mode is not None else "quiet hours"
        if _is_urgent(message, config):
            return Decision(True, f"urgent, so it breaks through {named}",
                            channel_name)
        return Decision(False, named, channel_name)

    return Decision(True, "no reason to hold it", channel_name)


def _mode_for(origin: str):
    """The quiet mode belonging to whichever task sent this, if any.

    `tasks.run_one` stamps every scheduled result with `origin="task:<key>"`,
    which is the only thread connecting a message back to the row on the
    Schedule page. Reading it here keeps `decide()` pure and means nothing
    had to change in the signature of what sends.
    """
    if not origin.startswith("task:"):
        return None
    key = origin.split(":", 1)[1].strip()
    if not key:
        return None
    try:
        from . import quiet

        # A task nobody has decided about falls through to the global quiet
        # hours. That is C11, and it made the whole setting inert.
        #
        # `mode_for` answers ALWAYS for a task with no assignment, which is
        # the right default for "should this be held by a named mode". Used
        # here it meant something else: `decide()` reads a non-None mode as
        # "this task has its own rule", so the global window was never
        # consulted for any scheduled message — and scheduled messages are
        # very nearly all of them.
        #
        # So somebody could type 22:00 to 07:00 into Notifications, see it
        # saved, see it displayed back, and be messaged at midnight. Never
        # assigned and deliberately assigned "always" are different answers,
        # and only the second one should override.
        if key not in quiet.read_assignments():
            return None

        chosen = quiet.mode_for(key)
        if chosen == quiet.ALWAYS:
            # Chosen deliberately: this one is never held, not even by the
            # global window. "Always tell me" has to mean it.
            return quiet.Mode(key=quiet.ALWAYS, name="always",
                              start="", end="")
        return quiet.get_mode(chosen)
    except Exception:                                        # noqa: BLE001
        # A missing or unreadable assignment file must not stop a message.
        return None


def _is_urgent(message: Message, config) -> bool:
    if message.urgent:
        return True
    words = config.notifications.urgent_keywords
    if not words:
        return False
    haystack = message.text.casefold()
    return any(word.casefold() in haystack for word in words if word)


def _in_quiet_hours(window: tuple[str, str] | None,
                    now: _dt.datetime) -> bool:
    """Is `now` inside the quiet window?

    Handles a window that crosses midnight, which is the normal case and the
    one a naive implementation gets wrong: 22:00 to 07:00 is not "greater than
    22 and less than 7", it is "greater than 22 OR less than 7".
    """
    if not window:
        return False

    try:
        start_hour, start_minute = (int(part) for part in window[0].split(":"))
        end_hour, end_minute = (int(part) for part in window[1].split(":"))
    except (ValueError, AttributeError, IndexError):
        return False        # a malformed window must not mute everything

    start = _dt.time(start_hour, start_minute)
    end = _dt.time(end_hour, end_minute)
    current = now.time()

    if start <= end:
        return start <= current < end
    return current >= start or current < end


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send(text: str, config, channel_name: str = "file", *,
         urgent: bool = False, origin: str = "",
         now: _dt.datetime | None = None) -> Decision:
    """Deliver a message, or hold it. Never drops it.

    Every path out of this function either delivers or records the message in
    the held queue. There is no branch that discards one, and that is checked
    by a test.
    """
    message = Message(text=text, urgent=urgent, origin=origin,
                      created_at=now or _dt.datetime.now())
    decision = decide(message, config, channel_name, now=now,
                      mode=_mode_for(origin))

    if not decision.deliver:
        _hold(message, channel_name, decision.reason)
        return decision

    channel = channels.get(channel_name)
    if channel is None:
        # An unknown channel name is a configuration mistake, not a reason to
        # lose the message.
        _hold(message, channel_name, f"no channel called '{channel_name}'")
        return Decision(False, f"there is no channel called '{channel_name}'",
                        channel_name)

    if not channel.available():
        _hold(message, channel_name, f"{channel_name} is not available")
        return Decision(False, f"{channel_name} is not available right now",
                        channel_name)

    delivered, explanation = channel.deliver(message)
    if not delivered:
        _hold(message, channel_name, explanation)
        return Decision(False, explanation, channel_name)

    _mirror(message, channel_name, delivered=True)
    _tap_on_the_shoulder(message)
    events.record("said", message.safe_text(), source=origin or "assistant",
                  detail={"channel": channel_name})
    return Decision(True, explanation, channel_name)


def _tap_on_the_shoulder(message: Message) -> None:
    """Push it to the person's phone, if they asked to be told.

    AFTER the message is already in the conversation, and never able to undo
    that. The push is a tap on the shoulder; the panel holds the message, and
    a push that fails must not turn a delivered message into a failed one.

    It carries only enough to be worth looking at. The whole message would end
    up on a lock screen, which is a place a conversation should not be.
    """
    try:
        from . import push

        push.notify_quietly("Aki", message.safe_text(), url="/")
    except Exception:                                     # noqa: BLE001
        return


def _mirror(message: Message, channel_name: str, delivered: bool) -> None:
    """Put every outbound message into the one conversation log.

    Everything the assistant says goes through here on the way out, so this is
    the one place that can put all of it in front of the person -- including
    the half of it nobody typed a question for, which is the scheduled work.

    **One gate for everything that goes out.** That is what this line now does. Until today a scheduled job was
    a stranger: it ran, spoke on its own channel, and the live agent found out
    only because a hook injected a summary of what its own background jobs had
    done. An entire reconciliation layer existed for no reason except that
    scheduled work happened outside the conversation.

    Writing into `chat` puts it inside. The word "mirror" is now wrong and
    kept only because renaming it is not this change: nothing is being copied
    anywhere. This IS the conversation, and it is written once.

    Deliberately never raises. Recording is a convenience; failing to record
    must not stop a message being delivered.
    """
    try:
        from . import chat

        chat.say("assistant", message.text, session=chat.MAIN, meta={
            "origin": getattr(message, "origin", "") or "",
            "channel": channel_name,
            "delivered": "yes" if delivered else "no",
        })
    except Exception:  # noqa: BLE001 -- see above
        pass


# ---------------------------------------------------------------------------
# The held queue
# ---------------------------------------------------------------------------

def _hold(message: Message, channel_name: str, reason: str) -> None:
    # Held messages are mirrored too, marked as held. A user looking at the
    # dashboard should see that the assistant tried to tell them something and
    # is waiting -- that is exactly the information the quiet-hours rule
    # exists to preserve.
    _mirror(message, channel_name, delivered=False)

    queue = read_held()
    queue.append({
        "text": message.text,
        "urgent": message.urgent,
        "origin": message.origin,
        "created_at": message.created_at.isoformat(timespec="seconds"),
        "channel": channel_name,
        "reason": reason,
    })
    atomic.write_json(held_queue_path(), queue)


def read_held() -> list[dict]:
    # `read_json_for_update`, not `read_json`: every caller of this reads the
    # queue, changes it, and writes it back. A plain read cannot tell "the
    # file is not there" from "the file is there and would not open", and
    # answering the second with an empty list is how the whole queue used to
    # be erased by the next write.
    return atomic.read_json_for_update(held_queue_path(), default=[]) or []


def held_count() -> int:
    return len(read_held())


def release(config, channel_name: str = "file",
            now: _dt.datetime | None = None) -> tuple[int, Decision | None]:
    """Deliver everything held, as one digest.

    Returns (how many were held, the decision for the digest).

    If the digest itself cannot go out — still quiet hours, channel down — the
    queue is left untouched and tried again later. Nothing is cleared until it
    has actually been delivered, because clearing on an unverified send is how
    held messages disappear.
    """
    queue = read_held()
    if not queue:
        return 0, None

    lines = [f"While I was quiet, {len(queue)} thing"
             f"{'s' if len(queue) != 1 else ''} came up:", ""]
    for entry in queue:
        stamp = entry.get("created_at", "")[11:16]
        marker = "! " if entry.get("urgent") else ""
        lines.append(f"- {stamp} {marker}{entry.get('text', '')}")

    digest = Message(text="\n".join(lines), origin="held digest",
                     created_at=now or _dt.datetime.now())

    # Asked before it is handed over.
    #
    # This called `send`, which holds whatever it cannot deliver -- so a
    # release attempted during quiet hours appended its own digest to the
    # queue it was trying to empty. The 08:05 task runs every day; a stretch
    # of quiet mornings would leave a queue of digests of digests, each one
    # longer than the last, and "Waiting to send: N" climbing for a reason
    # nobody could have worked out from the page.
    #
    # That is the same fault this whole feature was built to fix, one level
    # up. So the gate is consulted first, and the digest only enters the
    # sending path once the answer is yes. Nothing is held twice, and the
    # queue is unchanged unless it was genuinely delivered.
    decision = decide(digest, config, channel_name, now=now,
                      mode=_mode_for("held digest"))
    if not decision.deliver:
        return len(queue), decision

    decision = send(digest.text, config, channel_name,
                    origin="held digest", now=now)

    if decision.deliver:
        atomic.write_json(held_queue_path(), [])

    return len(queue), decision


def clear_held() -> int:
    """Empty the queue without delivering. Returns how many were discarded.

    Exists because a user may genuinely want to bin a backlog. It is a
    separate, explicitly-named function rather than an option on `release`,
    so that discarding messages can never happen as a side effect of trying
    to deliver them.
    """
    count = held_count()
    atomic.write_json(held_queue_path(), [])
    return count
