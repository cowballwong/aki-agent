"""Secrets -- asked for at install, stored by the operating system.

THE RULE, AND WHY IT IS ABSOLUTE
--------------------------------
No credential is ever written into this package's source, its config file, or
anything that gets copied, shared, zipped or committed.

The system this package derives from broke that rule in more than one place:
plaintext credentials committed in scripts, and a hardcoded fallback login on
an endpoint its own comments admitted was exposed. That is not carried across.
It is not carried across *at all* -- not "cleaned up later", not "fine because
it's only a test token".

WHERE SECRETS GO INSTEAD
------------------------
The operating system already has a password manager, and it is better than
anything this package could write:

    Windows : Credential Manager
    macOS   : Keychain

The `keyring` package talks to both with one API. It is an optional dependency
because the agent works without any secrets at all -- you only need this once
you connect a messaging channel.

WHAT HAPPENS IF THERE IS NO PASSWORD MANAGER
--------------------------------------------
On an unusual machine, `keyring` may find no working backend. There is a
fallback, and it is deliberately *worse and louder*: a file in the user's
private folder, permissions tightened, and a warning printed every time it is
used. A silent fallback would be the dangerous thing -- the user would believe
their token was in the Keychain when it was sitting in a text file.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from . import paths

# The "service" name the OS password manager files these under. Appears in the
# user's Credential Manager / Keychain, so it should be recognisable to them.
SERVICE_NAME = "aki-agent"

# Fallback location, used only when no OS password manager is available.
_FALLBACK_FILE_NAME = "secrets.json"


class SecretsUnavailable(Exception):
    """Raised when a secret cannot be stored anywhere at all."""


def _fallback_path() -> Path:
    return paths.app_dir() / _FALLBACK_FILE_NAME


def _keyring_or_none():
    """Return a working keyring module, or None.

    Two separate failures are possible and they are not the same: the package
    is not installed, or it is installed but found no backend. Both end up
    here as None, and the caller warns -- but `doctor` reports them
    differently, because the fixes differ.
    """
    try:
        import keyring
    except ImportError:
        return None

    try:
        backend = keyring.get_keyring()
        if "fail" in type(backend).__name__.lower():
            return None
        return keyring
    except Exception:  # noqa: BLE001 -- any backend problem means "no store"
        return None


def lock_down(path: Path) -> str:
    """Make a file readable only by the account it belongs to.

    WHY `os.chmod` IS NOT ENOUGH, AND WAS THE WHOLE PROTECTION (2026-09-06)
    ----------------------------------------------------------------------
    The fallback writer called `os.chmod(0o600)` and the comment beside it
    already said the true thing -- "on Windows chmod is largely ignored" --
    and then relied on it anyway. On Windows that call sets the read-only
    attribute and nothing else: it does not change who can read the file. So
    on the platform every student is on, the file holding their email
    password in plain text had whatever permissions it inherited from the
    folder above it, which is to say the default ones.

    `icacls` is how that is actually said on Windows. Inheritance off, one
    entry, this account. The other writer -- `delete_secret` -- did not even
    have the `chmod`, which is the same lesson this codebase has written down
    twice already: a fix applied to one path in a feature is not applied to
    the feature.

    Returns "" when the file is locked down, or why it could not be.
    """
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        if not paths.is_windows():
            return str(exc)

    if not paths.is_windows():
        return ""

    account = os.environ.get("USERNAME", "")
    if not account:
        return "no USERNAME to grant this file to"
    try:
        done = subprocess.run(
            ["icacls", str(path), "/inheritance:r",
             "/grant:r", f"{account}:F"],
            capture_output=True, text=True, timeout=20,
            # No console window: this runs from a scheduled task and from the
            # dashboard, and a black box flashing up during "save my password"
            # reads as something having gone wrong.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return f"icacls could not run: {exc}"
    if done.returncode != 0:
        return (done.stderr or done.stdout or "icacls refused").strip()
    return ""


def set_secret(key: str, value: str) -> str:
    """Store a secret. Returns where it went, for the caller to tell the user.

    The return value is deliberately not a boolean. The user must be told
    *which* of the two storage routes was used, because one of them is safe
    and the other is a compromise.
    """
    if not key:
        raise ValueError("a secret needs a name")
    if value is None:
        raise ValueError("a secret needs a value")

    keyring = _keyring_or_none()
    if keyring is not None:
        # `SecretsUnavailable` existed for this from the beginning and was
        # never raised anywhere, so a credential store that refused a write
        # reached a non-technical student as a raw `WinError 1312` or a
        # backend's own exception type -- in the middle of connecting their
        # email, which is exactly the moment they are least able to read one.
        #
        # `_keyring_or_none` already handles "no backend at all". This is the
        # other case: a backend that is there and says no.
        try:
            keyring.set_password(SERVICE_NAME, key, value)
        except Exception as exc:                         # noqa: BLE001
            raise SecretsUnavailable(
                f"Your {_store_label()} would not accept the password: {exc}. "
                "Nothing has been saved. This usually means the session has "
                "no desktop attached -- over SSH, or from a scheduled task. "
                "Try it again in a normal window on this machine."
            ) from exc
        return f"your {_store_label()}"

    # Fallback. Loud on purpose.
    path = _fallback_path()
    paths.ensure_app_dirs()

    data = _read_fallback()
    data[key] = value

    # Atomic write, same rule as everywhere else: build the replacement, then
    # swap. Never truncate the live file first.
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        raise SecretsUnavailable(
            f"There is no password manager available, and the file it falls "
            f"back to could not be written either: {exc}. Nothing has been "
            f"saved, so nothing is half-connected."
        ) from exc

    # Tighten permissions before the file becomes visible under its real name,
    # so there is no moment where it exists readable. `lock_down` is the real
    # thing on Windows as well as on macOS; see its docstring for what the
    # `chmod` that used to be here did not do.
    lock_down(temporary)
    temporary.replace(path)
    lock_down(path)
    return f"a file at {path} (NOT your password manager -- see below)"


def get_secret(key: str) -> str | None:
    """Fetch a secret, or None if it cannot be had.

    THE STORE BEING UNREACHABLE IS NOT AN ERROR HERE (2026-08-20)
    -------------------------------------------------------------
    Windows Credential Manager belongs to an interactive logon. Read it from a
    session that has none -- over SSH, from a service, from some scheduled
    contexts -- and it raises `WinError 1312: A specified logon session does
    not exist`, which is true and unhelpful.

    That exception used to come straight out of here. It surfaced while
    checking the dashboard's chat status over SSH: a nine-frame traceback
    ending in `win32cred.CredRead`, in answer to the question "is a Telegram
    API id saved". And every caller in the package -- the dashboard, the
    scheduled tasks, `doctor` -- would have met the same thing in the same
    situations.

    A secret that cannot be read is, to every one of those callers, the same
    as a secret that was never stored: they have no value and must carry on.
    So the answer is None, and the difference is reported by
    `store_unavailable()` for the one place that should say it out loud.

    BOTH STORES ARE READ, NOT ONE (2026-09-12)
    ------------------------------------------
    This used to read the OS store *or* the file, decided by whether a keyring
    could be imported right now. Two processes can answer that question
    differently on the same machine -- the dashboard runs from the engine's
    environment, a session runs from whichever Python started it -- and then
    one of them writes to the password manager while the other reads a file
    that has never heard of the key.

    Nothing fails. The key is saved, the save is reported, and every later
    question about it is answered "no key". A user who has just typed one in
    is told it is not there, which is the worst available answer because it
    sends them to do the thing they have already done.

    So a miss in the preferred store falls through to the other one. The file
    is this package's own fallback, in the app folder, locked down on write;
    reading it when the keyring has nothing costs no safety and is the only
    thing that makes a key survive being written by the other half.
    """
    keyring = _keyring_or_none()
    if keyring is not None:
        try:
            found = keyring.get_password(SERVICE_NAME, key)
        except Exception:  # noqa: BLE001 -- backends raise their own types
            found = None
        if found:
            return found
    return _read_fallback().get(key)


def where_is(key: str) -> str:
    """Which store actually holds this secret: "os", "file", or "".

    Exists so a caller can tell three states apart that `get_secret` collapses
    into one: stored where this process expects, stored in the *other* half
    (see the note above), and genuinely not stored at all. Reports location
    only, never the value.
    """
    keyring = _keyring_or_none()
    if keyring is not None:
        try:
            if keyring.get_password(SERVICE_NAME, key):
                return "os"
        except Exception:  # noqa: BLE001
            pass
    if _read_fallback().get(key):
        return "file"
    return ""


def store_unavailable() -> str:
    """Why the credential store cannot be reached, or "" if it can.

    Separate from `get_secret` on purpose. Reading a secret needs to be
    forgiving; *telling somebody their passwords are unreachable* needs to be
    explicit, and only `doctor` and the settings page should do it.
    """
    keyring = _keyring_or_none()
    if keyring is None:
        return ""                     # the file fallback is in use, not broken

    try:
        keyring.get_password(SERVICE_NAME, "__probe__")
    except Exception as exc:  # noqa: BLE001
        return (f"{type(exc).__name__}: {exc}. This usually means the session "
                "running the assistant has no interactive logon -- over a "
                "remote connection, or as a service.")
    return ""


def every_key_we_might_hold(config=None) -> list[str]:
    """Every credential name this package could have written.

    The OS keyring cannot be listed — that is the point of a keyring — so
    the names have to be reconstructed from what the package stores. Each
    one is derived from the module that writes it, so a new kind of
    credential is added in one place rather than remembered in two.

    THIS EXISTS BECAUSE UNINSTALL LEFT EVERYTHING BEHIND (2026-08-23)
    -----------------------------------------------------------------
    `uninstall.plan()` names what it removes and what it leaves, and the word
    "credential" appeared in neither list. So a student who removed the
    assistant kept, in Windows Credential Manager: their Gmail app password,
    their Google OAuth client secret and refresh token, their Telegram API
    id and hash, and every paid API key they had added.

    `google_calendar.forget_everything()` had been written for exactly this
    and had no callers.
    """
    from . import apis
    from .connectors import calendars, google_calendar, mail

    names = [
        google_calendar.KEY_CLIENT_ID,
        google_calendar.KEY_CLIENT_SECRET,
        google_calendar.KEY_REFRESH,
        "telegram_api_id",
        "telegram_api_hash",
    ]
    names += [apis.secret_name(one.key) for one in apis.catalogue()]

    if config is not None:
        for account in getattr(config, "mail", ()) or ():
            names.append(mail.SECRET_KEY_TEMPLATE.format(
                address=getattr(account, "address", "")))
        for feed in getattr(config, "calendars", ()) or ():
            names.append(calendars.SECRET_KEY_TEMPLATE.format(
                name=getattr(feed, "name", "")))

    return sorted({one for one in names if one})


def forget_everything(config=None) -> list[str]:
    """Remove every credential this package holds. Returns what went."""
    gone = []
    for key in every_key_we_might_hold(config):
        if delete_secret(key):
            gone.append(key)
    return gone


def delete_secret(key: str) -> bool:
    """Remove a secret. Returns True if there was one to remove."""
    keyring = _keyring_or_none()
    if keyring is not None:
        try:
            keyring.delete_password(SERVICE_NAME, key)
            return True
        except Exception:  # noqa: BLE001 -- "not found" varies by backend
            return False

    data = _read_fallback()
    if key not in data:
        return False
    del data[key]
    path = _fallback_path()
    temporary = path.with_suffix(".tmp")
    # This file still holds every OTHER secret, so it is locked down on the
    # way past exactly as the writer above is. Until 2026-09-06 this path had
    # no permission handling at all -- deleting one credential rewrote the
    # file holding the rest with whatever the folder happened to give it.
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    lock_down(temporary)
    temporary.replace(path)
    lock_down(path)
    return True


def _read_fallback() -> dict:
    path = _fallback_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        # A corrupt secrets file must not stop the software starting. The
        # user is told by `doctor`; here we behave as though nothing is stored,
        # which prompts them to enter it again.
        return {}


def _store_label() -> str:
    return "Credential Manager" if paths.is_windows() else "Keychain"


def using_os_store() -> bool:
    """True if secrets are going to the OS password manager."""
    return _keyring_or_none() is not None


def fallback_warning() -> str | None:
    """The warning to show the user when the fallback is in use, else None."""
    if using_os_store():
        return None
    return (
        "WARNING: no password manager was found on this machine, so secrets "
        f"are being kept in a plain file at {_fallback_path()}.\n"
        "Anyone who can read your user account can read that file. Do not "
        "copy, sync or share that folder."
    )


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

# Shapes that look like credentials, whoever issued them. Deliberately
# vendor-agnostic: a list of specific providers goes out of date, and the point
# is to catch the token you did not anticipate.
#
# This is used before anything is logged, traced or shown on a dashboard.
import re as _re  # noqa: E402 -- kept beside the patterns it serves

_SECRET_PATTERNS = (
    # key = value / key: value, where the key name suggests a credential
    _re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|auth|bearer|"
        r"credential)\b\s*[:=]\s*[\"']?([^\s\"',;]{8,})",
    ),
    # Anything that looks like an authorization header value
    _re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{10,}"),
)

# Long strings with no label around them. Most tokens look like this.
_BARE_TOKEN = _re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")

# ...but so do long function names, and that matters.
#
# The first version of this redactor blanked out
# `test_engine_source_contains_no_profession_vocabulary` because it is 52
# characters long. A redactor that eats its own log messages is not a safety
# feature, it is noise -- and noise gets switched off, which is how the real
# leak eventually gets through.
#
# So a bare long string is only treated as a secret if it does NOT look like
# something a programmer typed on purpose.
_IDENTIFIER_SHAPES = (
    _re.compile(r"[a-z0-9]+([_-][a-z0-9]+)+"),   # snake_case, kebab-case
    _re.compile(r"[A-Z0-9]+([_-][A-Z0-9]+)+"),   # CONSTANT_CASE
    _re.compile(r"[A-Za-z]+"),                   # one long word, no digits
)


def _looks_like_an_identifier(token: str) -> bool:
    return any(shape.fullmatch(token) for shape in _IDENTIFIER_SHAPES)


def redact(text: str) -> str:
    """Replace anything that looks like a credential with a marker.

    Applied to log lines, traces and dashboard output. It will sometimes hide
    something harmless that merely looks like a token -- that trade is
    deliberate and the right way round. A false positive costs a moment of
    confusion; a false negative writes a live token into a log file that gets
    pasted into a class chat.
    """
    if not text:
        return text

    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_replace_match, redacted)
    redacted = _BARE_TOKEN.sub(_replace_bare_token, redacted)
    return redacted


def _replace_bare_token(match: "_re.Match[str]") -> str:
    candidate = match.group(0)
    if _looks_like_an_identifier(candidate):
        return candidate
    return "[redacted]"


# ---------------------------------------------------------------------------
# Scanning source code for committed credentials
#
# This is a DIFFERENT job from redact(), and conflating the two produced two
# false positives worth recording, because both are instructive:
#
#   redact() is for OUTPUT -- logs, traces, dashboards. It should be
#   aggressive: in a log line, `token = 4f3a9b...` is a secret, full stop.
#
#   this is for SOURCE -- a repository being checked before it ships. Source
#   code is full of lines like `token = match.group(0)`, which is a variable
#   assignment, not a leak. Running the log rule over source flagged this very
#   file.
#
# So the scan rule is narrower: a credential is only reported when the value
# is a *literal* someone typed, not an expression the program computes.
# ---------------------------------------------------------------------------

_COMMITTED_SECRET = _re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|auth[_-]?token|"
    r"bearer|credential)\b\s*[:=]\s*"
    r"[\"']([^\"'\s]{8,})[\"']",          # quoted literal only
)

# Values that are obviously not real, so that examples and templates can still
# say what shape a thing is without tripping the check.
_OBVIOUS_PLACEHOLDERS = _re.compile(
    r"(?i)^(x{3,}|\.{3,}|<.*>|"
    r"\{[^}]*\}|\{\{.*\}\}|"      # {placeholder}, {{handlebars}}, f-strings
    r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|"   # $VAR and ${VAR}
    r"%[A-Za-z_]+%|"                     # %WINDOWS_VAR%
    r"your[_-].*|placeholder.*|example.*|changeme.*|redacted|paste.*|todo.*"
    r")$"
)
# The f-string case was found by this very scanner reporting three test files
# that contained `api_key = "{FAKE_HEX_KEY}"`. The quoted part is fourteen
# characters, so it matched the "a quoted literal of eight or more" rule --
# but it is a placeholder the program fills in, not a secret somebody typed.
#
# Worth noticing what happened there: the scanner was working correctly and
# still needed fixing. A check that produces false alarms gets ignored, and an
# ignored check is the same as no check at all.


# A URL, and the things that make one worth scanning anyway: a credential
# handed over in a query string is a real leak and stays caught.
_URL = _re.compile(r"https?://\S+")
_URL_WITH_SECRET = _re.compile(
    r"(?i)[?&](api[-_]?key|key|token|secret|password|access[-_]?token)=|sk-")


def _without_plain_urls(line: str) -> str:
    """The line with harmless URLs removed, so they cannot trip the scan.

    A URL that carries a credential in its query string is left in place --
    that is the case worth catching, and removing it would be exactly the
    wrong exemption.
    """
    def keep_or_drop(match: "_re.Match[str]") -> str:
        url = match.group(0)
        return url if _URL_WITH_SECRET.search(url) else " "

    return _URL.sub(keep_or_drop, line)


# Prefixes that are only ever the start of a credential. Matching one is
# conclusive: no entropy judgement can improve on knowing the issuer's own
# format. Found the hard way -- `sk-ant-api03-` followed by lower-case hex
# read as a hyphenated identifier and passed the entropy check.
_KNOWN_CREDENTIAL_PREFIX = _re.compile(
    r"(?i)\b("
    r"sk-ant-[A-Za-z0-9\-_]{16,}"      # Anthropic
    r"|sk-[A-Za-z0-9\-_]{20,}"          # OpenAI and lookalikes
    r"|ghp_[A-Za-z0-9]{20,}"            # GitHub personal access token
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}"   # Slack
    r"|AIza[A-Za-z0-9\-_]{30,}"         # Google
    r"|AKIA[A-Z0-9]{16}"                # AWS access key id
    r")")


def scan_for_committed_secrets(text: str) -> list[int]:
    """Return the 1-based line numbers that look like committed credentials.

    Returns line numbers rather than the matched text on purpose: a check that
    finds a secret must not then print it into a test report or a CI log.
    """
    hits: list[int] = []
    for number, line in enumerate(text.splitlines(), start=1):
        # The one way to say "this long random-looking thing is meant to be
        # here", and it is deliberately per-line.
        #
        # The alternative was to add whole files to the test's allowlist, and
        # the first two candidates showed why that is the wrong shape: the
        # public half of the release key, and a constant out of RFC 8032.
        # Both are published values whose entire purpose is to be committed --
        # but allowlisting their files would also stop the scanner ever
        # looking at the file that verifies signatures, which is not a file
        # anybody should stop looking at.
        #
        # Written out in full rather than shortened, so that a line carrying
        # it cannot be skimmed past: it is a claim, and a reviewer should be
        # able to see the claim being made.
        if "not-a-secret: published value" in line:
            continue

        # Conclusive before anything heuristic: an issuer's own prefix is not
        # a judgement call, and this catches keys inside URLs, JSON and prose
        # that the entropy rule reads as identifiers.
        if _KNOWN_CREDENTIAL_PREFIX.search(line):
            hits.append(number)
            continue

        match = _COMMITTED_SECRET.search(line)
        if match and not _OBVIOUS_PLACEHOLDERS.fullmatch(match.group(2)):
            hits.append(number)
            continue
        # A bare high-entropy token sitting in source is suspicious whatever
        # it is labelled -- but a long URL is not a token. Citations, package
        # links and government PDFs all carry long random-looking paths, and a
        # scanner that flags them gets switched off, which is how the real
        # thing gets through later.
        scannable = _without_plain_urls(line)
        for candidate in _BARE_TOKEN.findall(scannable):
            if not _looks_like_an_identifier(candidate):
                hits.append(number)
                break
    return hits


def _replace_match(match: "_re.Match[str]") -> str:
    """Keep the label, hide the value."""
    groups = match.groups()
    if len(groups) >= 2 and groups[0]:
        return f"{match.group(1)}=[redacted]"
    return "[redacted]"
