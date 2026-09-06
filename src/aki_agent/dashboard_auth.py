"""A PIN on the dashboard, and an honest account of what it is for.

WHAT THIS PROTECTS AGAINST, AND WHAT IT DOES NOT
------------------------------------------------
The dashboard binds to loopback, so by default it is not on the network. What
it is open to is everything already on the machine: somebody else who uses it,
a family member, the five minutes the screen is unlocked and unattended, and
any other program on the box that can reach a local port.

WHEN SOMEBODY PUTS IT ON THE INTERNET
-------------------------------------
reported 2026-08-28, wants users to be able to reach their dashboard from outside
through a tunnel. That changes the threat: a door that only ever faced a room
now faces the street, and the paragraph above stops being the whole story.

Six digits is a million combinations. Against somebody typing, that is plenty.
Against a script over a tunnel with nothing slowing it down, a million is an
afternoon — so the length was never the part that mattered. **The throttle
below is.** Five wrong tries, then a wait that grows: at that rate a million
guesses takes months rather than an afternoon.

It is still not a safe. Exposing the dashboard means a stranger who guesses can
read everything the assistant knows, so the throttle raises the cost of
guessing — it does not remove the consequence of a bad PIN. Anybody publishing
this should choose a PIN nobody would guess first, and let the tunnel do
authentication of its own if it can.

It does NOT protect the data. The configuration, the memory, the day's log and
the house rules are ordinary files in an ordinary folder. Anybody with the
machine and the path reads them without going near this. A PIN here is a door
on a room, not a safe -- worth having, and worth not overselling.

WHY THE PIN IS NOT KEPT
-----------------------
The maintainer asked for a "forgot my PIN" button that writes the PIN to a file on the
Desktop. Written literally, that requires storing it in a form this program
can read back -- and anything this program can read, so can anyone holding the
folder, which would leave the PIN protecting nothing.

So only a hash is kept, in the operating system's credential store, and
"forgot" RESETS rather than reveals: a new PIN is generated and the old one
stops working.

WHERE THE NEW ONE GOES
----------------------
To their phone if a channel is connected -- the maintainer's own improvement on the
file, and better in the way that matters: nothing touches the disk, it lands
on a device only they hold, and there is nothing left behind to remember to
delete.

The file on the Desktop stays as the fallback, because a reset that needs a
working connection is not a reset. It would fail exactly when the assistant is
already unwell, which is when somebody is most likely to be trying to get in
and find out why.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets as _stdlib_secrets
from pathlib import Path

from . import paths, secrets

# Six. The maintainer asked for five and, in the same sentence, for `000000` as the
# default -- so it was built as six and the disagreement put to him rather
# than resolved quietly. He confirmed six on 2026-08-24. A rule that disagrees
# with its own default is one people meet as an error message.
PIN_LENGTH = 6
DEFAULT_PIN = "0" * PIN_LENGTH

# Where the hash lives. The OS credential store, through this package's own
# wrapper, so it is not a file sitting beside the thing it protects.
PIN_KEY = "dashboard_pin"

ROUNDS = 240_000


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt.encode("utf-8"), ROUNDS).hex()


def is_a_pin(candidate: str) -> bool:
    candidate = (candidate or "").strip()
    return len(candidate) == PIN_LENGTH and candidate.isdigit()


def why_not(candidate: str) -> str:
    """Why this is not a usable PIN, in the words somebody would use.

    Returns "" when it is fine. Said as one sentence: a list of rules under a
    box is read after the second failure, never before the first.
    """
    candidate = (candidate or "").strip()
    if not candidate:
        return "Enter your new PIN."
    if not candidate.isdigit():
        return f"{PIN_LENGTH} numbers only — no letters or spaces."
    if len(candidate) != PIN_LENGTH:
        return f"It needs to be exactly {PIN_LENGTH} numbers."
    if candidate == DEFAULT_PIN:
        return "That is the one it came with. Pick another."
    return ""


def _stored() -> tuple[str, str] | None:
    """(salt, hash), or None when nothing has been set yet."""
    kept = secrets.get_secret(PIN_KEY)
    if not kept or "$" not in kept:
        return None
    salt, _, digest = kept.partition("$")
    return (salt, digest) if salt and digest else None


def is_default() -> bool:
    """Has anybody chosen a PIN yet?

    True on a fresh install, which is what the first-run change is for.
    """
    return _stored() is None


def check(pin: str) -> bool:
    """Is this the right PIN? Constant-time, and the default counts."""
    pin = (pin or "").strip()
    kept = _stored()
    if kept is None:
        return hmac.compare_digest(pin, DEFAULT_PIN)
    salt, digest = kept
    return hmac.compare_digest(_hash(pin, salt), digest)


def set_pin(pin: str) -> str:
    """Store a new PIN. Returns "" on success, or why it was refused."""
    problem = why_not(pin)
    if problem:
        return problem
    salt = _stdlib_secrets.token_hex(16)
    secrets.set_secret(PIN_KEY, f"{salt}${_hash(pin.strip(), salt)}")
    return ""


def reset_to_new() -> str:
    """Generate a PIN, store its hash, and return it once.

    The only moment the new PIN exists in readable form is this return value
    and the file the caller writes from it. Nothing keeps it afterwards --
    including this program.
    """
    while True:
        fresh = "".join(_stdlib_secrets.choice("0123456789")
                        for _ in range(PIN_LENGTH))
        if not why_not(fresh):
            break
    set_pin(fresh)
    return fresh


def send_to_phone(pin: str, assistant: str = "your assistant") -> str:
    """Message the new PIN to them instead of writing it down. "" if it went.

    The maintainer's own suggestion, and better than the file in the way that matters:
    nothing touches the disk, it arrives on a device only they hold, and there
    is no "remember to delete this" left behind.

    Returns why it could not be sent, so the caller can fall back rather than
    leave somebody locked out. A reset path that depends on a working
    connection is not a reset path -- it fails exactly when the assistant is
    already unwell, which is when somebody is most likely to be trying to get
    in and look.
    """
    from . import channels

    channel = channels.get("telegram")
    if channel is None or not channel.available():
        return "no messaging channel is connected"

    # Deliberately NOT through `notify`: quiet hours must not hold this, and a
    # digest tomorrow morning is no use to somebody standing at a login box.
    message = (f"{assistant}: your new dashboard PIN is {pin}"
               "\n\nThe previous one no longer works. "
               "Nothing else has changed.")
    ok, detail = channel.deliver(channels.Message(text=message))
    return "" if ok else detail


def desktop() -> Path:
    """Their Desktop, or their home folder if there is not one.

    OneDrive moves the Desktop on a lot of Windows machines, so the real one
    is looked for before the obvious one -- a file written to a Desktop that
    is not the Desktop they are looking at is the same as no file.
    """
    home = paths.home()
    candidates = [home / "Desktop"]
    for name in ("OneDrive", "OneDrive - Personal"):
        candidates.insert(0, home / name / "Desktop")
    profile = os.environ.get("USERPROFILE", "")
    if profile:
        candidates.append(Path(profile) / "Desktop")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return home


def write_reset_file(pin: str, assistant: str = "your assistant") -> Path:
    """Put the new PIN somewhere they will find it, and say to delete it.

    Named so it is obvious on a crowded Desktop, and dated so a second reset
    does not overwrite the first without anybody noticing.
    """
    import datetime as _dt

    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H%M")
    target = desktop() / f"{assistant} PIN {stamp}.txt"
    target.write_text(
        f"Your new dashboard PIN is:  {pin}\n"
        "\n"
        "It was reset just now, so the previous one no longer works.\n"
        "\n"
        "DELETE THIS FILE once you have it. Anyone who can see your Desktop\n"
        "can read it, and it is the only place this PIN is written down.\n",
        encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# The throttle
# ---------------------------------------------------------------------------
#
# Kept in a file rather than in memory, because the dashboard is restarted --
# by the watchdog, by an upgrade, by the user closing it -- and an attacker who
# can cause a restart should not be able to clear the count by doing so.
#
# Counted per machine, not per address. The dashboard sits behind a tunnel when
# it is exposed at all, so every request arrives wearing the proxy's address or
# a header the client itself can set. Trusting either would make the throttle
# bypassable by the one party it exists to stop.
#
# The cost of that choice, stated because it is real: one attacker locks the
# owner out too. That is the right way round -- a locked-out owner has the
# machine in front of them and a reset button; a throttle that can be shrugged
# off protects nobody.

# Failures allowed before the first wait, then how long each further failure
# costs. Chosen so that a person who fat-fingers a digit twice notices nothing.
FREE_TRIES = 5
WAITS = ((5, 60), (10, 300), (20, 3600))   # (failures reached, seconds locked)


def _attempts_path() -> Path:
    return paths.app_dir() / "dashboard-pin-attempts.json"


def _load_attempts() -> dict:
    try:
        import json
        return json.loads(_attempts_path().read_text(encoding="utf-8"))
    except Exception:                                      # noqa: BLE001
        return {"failures": 0, "last": 0.0}


def _save_attempts(state: dict) -> bool:
    """Save the count. Returns whether it actually got written.

    THE RETURN VALUE IS THE WHOLE POINT (2026-09-05)
    -----------------------------------------------
    "A throttle that cannot write must not be a door that cannot open" is the
    right trade on a machine somebody is sitting at: the worst case is one
    person, in the room, trying PINs by hand. It stops being the right trade
    the moment remote access is on, because then the same silence means an
    unmetered six-digit PIN facing the internet -- a million combinations, and
    a script has all night. Same code, opposite consequence, decided by a
    setting this function cannot see.

    So it no longer decides. It reports, and the caller -- which does know
    whether the request came from this machine -- chooses. See the login
    route in `dashboard/app.py`.
    """
    import json

    from . import atomic
    try:
        atomic.write_text(_attempts_path(),
                          json.dumps(state, sort_keys=True))
        return True
    except Exception:                                      # noqa: BLE001
        # Still not fatal on this machine. The caller decides.
        return False


def _wait_for(failures: int) -> int:
    """Seconds to hold the door after this many consecutive failures."""
    seconds = 0
    for reached, hold in WAITS:
        if failures >= reached:
            seconds = hold
    return seconds


def locked_out(now: float | None = None) -> tuple[bool, int]:
    """Is the door held shut, and for how many more seconds?"""
    import time

    now = time.time() if now is None else now
    state = _load_attempts()
    failures = int(state.get("failures", 0) or 0)
    if failures < FREE_TRIES:
        return False, 0
    hold = _wait_for(failures)
    if not hold:
        return False, 0
    passed = now - float(state.get("last", 0.0) or 0.0)
    left = int(hold - passed)
    return (left > 0), max(left, 0)


def record_failure(now: float | None = None) -> bool:
    """Count one wrong PIN. Returns whether the count survived.

    False means the next attempt starts from the same number this one did --
    i.e. there is no throttle at all. Harmless at the keyboard, and the reason
    a remote login is refused outright; see `_save_attempts`.
    """
    import time

    now = time.time() if now is None else now
    state = _load_attempts()
    return _save_attempts({"failures": int(state.get("failures", 0) or 0) + 1,
                           "last": now})


def clear_failures() -> None:
    """A correct PIN forgives everything before it."""
    _save_attempts({"failures": 0, "last": 0.0})


# ---------------------------------------------------------------------------
# The throttle on RESETS, which is a separate door
# ---------------------------------------------------------------------------
#
# Found 2026-09-06. `/login/forgot` needs no PIN -- it cannot, it is the way
# in when the PIN is the thing you have lost -- and it had no limit of any
# kind. So anything that could reach the port could press it, over and over:
#
#   * every press invalidates the PIN the owner has just been sent, so a
#     script pressing it in a loop means the owner can never log in again,
#     no matter how many times they read the new one off their phone
#   * every press either messages their phone or writes another file to
#     their Desktop, so the lockout arrives wearing a stream of notifications
#
# Neither of those needs to guess anything, which is why the login throttle
# did not cover it.
#
# Ten minutes. Long enough that a loop achieves nothing, short enough that
# somebody who has genuinely lost the PIN and mistyped the new one is not
# stuck: the reset they already did stands, and they can just read it again.
RESET_EVERY_SECONDS = 600


def _resets_path() -> Path:
    return paths.app_dir() / "dashboard-pin-resets.json"


def reset_allowed(now: float | None = None) -> tuple[bool, int]:
    """May the PIN be reset right now, and if not, how long until it may?"""
    import json
    import time

    now = time.time() if now is None else now
    try:
        last = float(json.loads(
            _resets_path().read_text(encoding="utf-8")).get("last", 0.0))
    except Exception:                                      # noqa: BLE001
        return True, 0
    left = int(RESET_EVERY_SECONDS - (now - last))
    return (left <= 0), max(left, 0)


def record_reset(now: float | None = None) -> None:
    import json
    import time

    from . import atomic
    try:
        atomic.write_text(_resets_path(),
                          json.dumps({"last": time.time() if now is None
                                      else now}))
    except Exception:                                      # noqa: BLE001
        # Unlike the login throttle, a reset that cannot be counted is not
        # left to the caller: the route refuses anyway. A reset the software
        # cannot rate-limit is the one thing this door must not offer.
        raise


def how_long(seconds: int) -> str:
    """The wait, in words somebody can act on."""
    if seconds >= 3600:
        hours = round(seconds / 3600, 1)
        return f"about {hours:g} hours"
    if seconds >= 60:
        return f"about {max(1, round(seconds / 60))} minutes"
    return f"{max(1, seconds)} seconds"
