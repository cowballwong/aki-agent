"""Web push, so the assistant can reach somebody who is not looking at it.

WHY THIS EXISTS
---------------
Dropping Telegram removed the transport and it also removed the tap on the
shoulder. A web page nobody has open cannot notify anybody. Before this, the
assistant could reach the maintainer at the school gate; without it, it can only wait
until he opens the dashboard -- which trades an agent that reaches you for one
that waits for you.

He chose the PWA route on 2026-09-01: installable from the dashboard, works on
Android and on iOS 16.4+ once added to the Home Screen, and **no third-party
account anywhere**. The VAPID keypair is generated on this machine, by this
module, and identifies this installation to the browser's push service. There
is nothing to register and nobody to sign up with, which is the promise the
whole package is built on.

THE DEPENDENCY, AND WHY IT IS OPTIONAL
--------------------------------------
Web push is not something to hand-roll. It needs ECDSA P-256 signing for VAPID
and ECDH + HKDF + AES128GCM for the payload, and hand-written cryptography is
a bad idea in every context including this one. Python's standard library has
none of it.

So `pywebpush` is an **optional extra**, exactly like the dashboard's Flask.
Everything here degrades honestly without it: the app still installs, the panel
still works, and asking to be notified says plainly that the piece is missing
and how to add it. The core install stays at one runtime dependency.

WHAT IS SECRET HERE
-------------------
The **private key**. Anyone holding it can send notifications that arrive
looking like this assistant. It lives in the state folder with the same care as
the rest, it is never sent anywhere, and only the PUBLIC key is handed to the
browser -- that is what a public key is for.

A subscription is not a secret but it is personal: it names a browser on a
device. Losing one is nothing; leaking a list of them is a list of somebody's
devices, so it stays local like everything else.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import atomic, paths

KEY_FILE = "push-keys.json"
SUBSCRIPTIONS_FILE = "push-subscriptions.json"

# The browser's push service wants a way to reach the operator of the
# application. It is never contacted; it is a formality of the protocol.
CONTACT = "mailto:aki-agent@localhost"

# A notification is a tap on the shoulder, not the message. The panel holds
# the message, and a push that tries to be the whole conversation is a push
# that leaks it to a lock screen.
MAX_BODY = 180


class PushUnavailable(Exception):
    """The optional piece is not installed. Says what to do about it."""


def _library():
    """The push library, or a sentence a person can act on."""
    try:
        from pywebpush import WebPushException, webpush   # noqa: PLC0415
    except ImportError as error:                          # pragma: no cover
        raise PushUnavailable(
            "Notifications on your phone need one extra piece. Install it "
            "with:  pip install aki-agent[push]"
        ) from error
    return webpush, WebPushException


def available() -> bool:
    """Can this installation send a push at all?"""
    try:
        _library()
    except PushUnavailable:
        return False
    return True


# ---------------------------------------------------------------------------
# The keypair
# ---------------------------------------------------------------------------

def key_file() -> Path:
    return paths.state_dir() / KEY_FILE


def _b64(raw: bytes) -> str:
    """URL-safe base64 without padding, which is what VAPID uses."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def keys() -> dict[str, str]:
    """This installation's VAPID keypair, generated once and then kept.

    Generated rather than configured. A key somebody has to obtain from a
    service is exactly the step this package exists to avoid.
    """
    existing = atomic.read_json(key_file(), default={}) or {}
    if existing.get("private") and existing.get("public"):
        return existing

    try:
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    except ImportError as error:
        raise PushUnavailable(
            "Notifications on your phone need one extra piece. Install it "
            "with:  pip install aki-agent[push]"
        ) from error

    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key()

    made = {
        "private": _b64(private.private_numbers().private_value.to_bytes(
            32, "big")),
        "public": _b64(public.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint)),
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
    }

    paths.ensure_app_dirs()
    atomic.write_json(key_file(), made)
    return made


def public_key() -> str:
    """What the browser needs. Safe to hand out -- that is the point of it."""
    return keys()["public"]


# ---------------------------------------------------------------------------
# Who has asked to be told
# ---------------------------------------------------------------------------

def subscriptions_file() -> Path:
    return paths.state_dir() / SUBSCRIPTIONS_FILE


@dataclass
class Subscription:
    endpoint: str
    p256dh: str
    auth: str
    added: str
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"endpoint": self.endpoint, "p256dh": self.p256dh,
                "auth": self.auth, "added": self.added, "label": self.label}

    def as_webpush(self) -> dict[str, Any]:
        return {"endpoint": self.endpoint,
                "keys": {"p256dh": self.p256dh, "auth": self.auth}}


def _read() -> list[Subscription]:
    data = atomic.read_json(subscriptions_file(), default={}) or {}
    found = []
    for row in data.get("subscriptions") or []:
        if not isinstance(row, dict) or not row.get("endpoint"):
            continue
        found.append(Subscription(
            endpoint=str(row.get("endpoint")),
            p256dh=str(row.get("p256dh") or ""),
            auth=str(row.get("auth") or ""),
            added=str(row.get("added") or ""),
            label=str(row.get("label") or ""),
        ))
    return found


def _write(rows: list[Subscription]) -> None:
    """Caller holds the lock."""
    atomic.write_json(subscriptions_file(),
                      {"subscriptions": [one.as_dict() for one in rows]})


def listing() -> list[Subscription]:
    return _read()


def subscribe(raw: dict, label: str = "") -> Subscription:
    """Remember a browser that has asked to be notified.

    Read-modify-write under the lock, because several sessions can be running
    and a device registered from a phone must not erase one registered from a
    laptop a moment earlier. That failure was already made once today in the
    working state; it is not being made again here.
    """
    endpoint = str((raw or {}).get("endpoint") or "").strip()
    keys_in = (raw or {}).get("keys") or {}
    p256dh = str(keys_in.get("p256dh") or "").strip()
    auth = str(keys_in.get("auth") or "").strip()

    if not endpoint or not p256dh or not auth:
        raise ValueError(
            "That subscription is missing something the browser should have "
            "provided. Try turning notifications off and on again.")
    if not endpoint.startswith("https://"):
        # Push services are HTTPS without exception, so anything else is
        # either a mistake or somebody pointing this at their own listener.
        raise ValueError("A push endpoint must be https.")

    made = Subscription(endpoint=endpoint, p256dh=p256dh, auth=auth,
                        added=_dt.datetime.now().isoformat(timespec="seconds"),
                        label=str(label or "")[:60])

    paths.ensure_app_dirs()
    with atomic.lock(subscriptions_file()):
        rows = [one for one in _read() if one.endpoint != endpoint]
        rows.append(made)
        _write(rows)
    return made


def unsubscribe(endpoint: str) -> bool:
    """Forget one. Returns whether there was anything to forget."""
    endpoint = str(endpoint or "").strip()
    with atomic.lock(subscriptions_file()):
        rows = _read()
        left = [one for one in rows if one.endpoint != endpoint]
        if len(left) == len(rows):
            return False
        _write(left)
        return True


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send(title: str, body: str = "", *, url: str = "/") -> dict[str, int]:
    """Tap every registered device on the shoulder.

    Returns how many were reached and how many were dropped. A subscription
    the push service rejects as gone is REMOVED rather than retried for ever:
    a device that has been wiped or a browser whose permission was revoked is
    not a temporary failure, and a list that only grows is a list that
    eventually sends every notification eight times.
    """
    webpush, WebPushException = _library()
    pair = keys()

    rows = _read()
    if not rows:
        return {"sent": 0, "dropped": 0, "devices": 0}

    payload = json.dumps({
        "title": (title or "Aki")[:80],
        "body": (body or "")[:MAX_BODY],
        "url": url or "/",
    }, ensure_ascii=False)

    sent = 0
    gone: list[str] = []

    for one in rows:
        try:
            webpush(
                subscription_info=one.as_webpush(),
                data=payload,
                vapid_private_key=pair["private"],
                vapid_claims={"sub": CONTACT},
                timeout=10,
            )
            sent += 1
        except WebPushException as error:
            status = getattr(getattr(error, "response", None),
                             "status_code", 0)
            # 404/410 is the push service saying this endpoint is finished.
            if status in (404, 410):
                gone.append(one.endpoint)
        except Exception:                                 # noqa: BLE001
            # A network blip is not a reason to forget somebody's phone.
            continue

    for endpoint in gone:
        unsubscribe(endpoint)

    return {"sent": sent, "dropped": len(gone), "devices": len(rows)}


def notify_quietly(title: str, body: str = "", *, url: str = "/") -> None:
    """Send if it is possible, and never raise if it is not.

    Wired into the notification gate, where the message has already been
    delivered to the panel by the time this runs. A push that fails must not
    turn a delivered message into a failed one.
    """
    try:
        send(title, body, url=url)
    except Exception:                                     # noqa: BLE001
        return
