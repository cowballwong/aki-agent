"""How to set a thing up, in one place, for every thing that needs setting up.

WHY THIS EXISTS
---------------
reported 2026-08-28, having chosen the route where each user registers their own
application with Google rather than using one shipped inside the package:

That choice is what makes this urgent. Registering an application is ten
minutes in a console built for developers, so the route the maintainer picked is only
viable if the instructions are genuinely good and genuinely findable.

The instructions were not missing. They were written, and they were good — and
they were in five places under five different names:

    connectors/google_calendar.how_to_set_up()
    connectors/mail.app_password_instructions(provider)
    connectors/calendars.how_to_get_the_address()
    connectors/files.describe_what_is_available()
    dependencies.describe_install(tool)

plus a handful of hard-coded `<details>` blocks inside `connections.html`. So a
person could find help if they happened to be on the right page, looking at the
right section — and nowhere else. The settings page had none at all.

This is the same shape of problem the `account` seam was built for, one layer
up: not an absence, a scattering.

WHAT THIS MODULE DOES, AND WHAT IT REFUSES TO DO
------------------------------------------------
It **wraps** the existing text; it does not restate it. Every built-in guide
below calls the function that already owns those words. Copying them here would
create a second copy to go stale, and the first thing to go stale in a copied
instruction is the step that changed — which is the one the reader needed.

What the module adds around that text is the structure a person actually wants
before they start: how long this takes, why they are being asked, and how to
undo it. "About ten minutes" up front is the difference between a person
starting and a person closing the tab.

WHY IT IS A SEAM
----------------
A plugin can already add a calendar or a channel without editing this package.
Until now it could not add the *instructions* for connecting the thing it
added, which meant every third-party provider arrived undocumented at exactly
the moment a user needed documentation. Registering a guide is one class and
one name, like everything else in `seams.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import seams


@dataclass(frozen=True)
class Guide:
    """One set-up explained.

    `body` is a callable rather than a string so that a guide which wraps a
    connector's own text picks up changes to that text without anyone
    remembering to update two files.
    """

    topic: str
    title: str
    # An honest estimate. Said before the steps, because somebody deciding
    # whether to start now deserves to know before they are three steps in.
    minutes: int
    # Why the assistant is asking this of them at all.
    why: str
    body: Callable[[], str] = lambda: ""
    # How to withdraw it afterwards. Every guide that asks for access must
    # answer this, and the test suite enforces it.
    undo: str = ""
    gotchas: tuple[str, ...] = ()
    links: tuple[tuple[str, str], ...] = ()

    @property
    def name(self) -> str:
        """`seams.Registry` identifies providers by `name`."""
        return self.topic

    def text(self) -> str:
        """The whole guide, as a person reads it in a terminal."""
        lines = [self.title, "=" * len(self.title), ""]
        lines.append(f"About {self.minutes} minutes." if self.minutes
                     else "This takes a moment.")
        lines.append("")
        if self.why:
            lines += [self.why, ""]
        written = (self.body() or "").strip()
        if written:
            lines += [written, ""]
        if self.gotchas:
            lines.append("Worth knowing:")
            lines += [f"  - {g}" for g in self.gotchas]
            lines.append("")
        if self.undo:
            lines += ["To undo it: " + self.undo, ""]
        for label, url in self.links:
            lines.append(f"{label}:  {url}")
        return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# The guides that ship
# ---------------------------------------------------------------------------

def _google_drive_body() -> str:
    """Why somebody would sign in when the folder already works."""
    lines = [
        "You probably do not need this. If Google Drive is installed on this "
        "computer there is already a Drive folder on the disk, and your "
        "assistant reads it as ordinary files - no account, no key, works "
        "offline, and you can see exactly what it can see by opening the "
        "folder.",
        "",
        "Sign in here only for what that cannot do:",
        "",
        "  * files that live only in the cloud and were never synced down",
        "  * searching a whole Drive rather than one folder",
        "  * a Drive on a computer with no Drive app installed",
        "",
        "  1. Set up the Google app on the Calendar tab, if you have not. It "
        "is the same app for all three.",
        "  2. Come back to the Files tab and press 'Sign in with Google'.",
        "",
        "IT IS READ ONLY. The permission asked for is 'see and download your "
        "Drive files' and there is no code here that writes, moves or deletes "
        "anything. Google has no narrower read than that: the smaller "
        "permissions either see only files this app itself made - none of "
        "yours - or can list a document's name without opening it.",
        "",
        "Your assistant reaches it with 'drive-find' to search and "
        "'drive-read' to open one. The synced folder keeps working exactly as "
        "before either way.",
    ]
    return "\n".join(lines)


def _gmail_oauth_body() -> str:
    """What signing a mailbox in with Google actually involves.

    Written out here rather than pointing at the calendar guide: the steps
    overlap, but the thing being handed over does not, and a guide that says
    "as above, but for mail" is how somebody grants a scope they did not read.
    """
    lines = [
        "This is for Gmail only, and it is optional. An app password works "
        "just as well; this exists because Google keeps trying to retire "
        "them, and because a token can be withdrawn from your Google account "
        "page without changing your password.",
        "",
        "  1. Set up the Google app first, on the Calendar tab. It is the "
        "same app - one registration covers both.",
        "  2. Come back to the Email tab and press 'Sign in with Google'.",
        "  3. Sign in as the mailbox you connected here, and allow it.",
        "",
        "BE CLEAR ABOUT WHAT YOU ARE ALLOWING. Google's consent screen will "
        "say full access to your Gmail account. That is not this assistant "
        "asking for more than it needs - it is the only permission Google "
        "offers for reading mail over IMAP, which is how mail is read here. "
        "If that is more than you want to grant, use an app password: it "
        "gives exactly the same access, with less to read on the screen.",
        "",
        "Sign in with the SAME address you added as an account. The token "
        "belongs to one mailbox, and one granted by a different Google "
        "account is refused at login.",
    ]
    return "\n".join(lines)


def _google_oauth_body() -> str:
    from .connectors import google_calendar
    return google_calendar.how_to_set_up()


def _ics_body() -> str:
    from .connectors import calendars
    return calendars.how_to_get_the_address()


def _mail_body() -> str:
    """Generic, because the provider is not known until an address is typed.

    `mail.app_password_instructions` is per-provider and better; the dashboard
    calls it directly once it knows which one. This is what to say before then.
    """
    from .connectors import mail
    # PROVIDERS is a tuple of Provider, not a mapping. Written as a dict the
    # first time, which would have raised inside a help page — the one screen
    # a person is on precisely because something already went wrong.
    known = ", ".join(sorted({p.name for p in mail.PROVIDERS}))
    base = (
        "An app password is a separate password just for this assistant, "
        "issued by your mail provider. It is not your normal password, it "
        "only works for mail, and you can cancel it at any time without "
        "changing anything else.\n"
        "\n"
        "Type your address first — the next screen links straight to the "
        "right page for your provider."
    )
    return base + (f"\n\nRecognised providers: {known}." if known else "")


def _files_body() -> str:
    from .connectors import files
    return files.describe_what_is_available()


def _telegram_body() -> str:
    return (
        "Telegram is how the assistant reaches you when you are not at the "
        "machine. It needs a bot of your own — bots are free and take about "
        "three minutes to make.\n"
        "\n"
        "  1. In Telegram, message @BotFather and send /newbot.\n"
        "  2. Give it any name and a username ending in 'bot'.\n"
        "  3. BotFather replies with a token. Paste it below.\n"
        "  4. Send your new bot any message, so it learns your chat.\n"
        "\n"
        "The token is stored in this computer's credential store, never in a "
        "file you might share."
    )


def _pin_body() -> str:
    return (
        "The dashboard runs on this machine only, and the PIN is there so "
        "that somebody who sits down at your unlocked computer cannot read "
        "your assistant's screen.\n"
        "\n"
        "It is not protection against a network attacker, and it is not "
        "pretending to be. If other people can reach this machine over a "
        "network, the PIN is not the control you want."
    )


def _semantic_body() -> str:
    """Wraps the module's own explanation, like every other guide here."""
    from . import semantic
    try:
        return semantic.explain()
    except Exception:                                      # pragma: no cover
        return ""


def _remote_body() -> str:
    from . import exposure
    lines = [
        exposure.state().describe(),
        "",
        "  1. Choose your own PIN first, if you have not. This will not "
        "turn on while the shipped one is still in place.",
        "  2. Install a tunnel (ngrok is the usual one) and point it at "
        "the port the dashboard runs on.",
        "  3. It gives you an address. Put that address in here - just "
        "the address, no https:// and no port.",
        "  4. Open it on your phone and sign in with your PIN.",
        "",
        "Only that exact address is answered. A different tunnel, a "
        "different name, or anything merely resembling it is refused.",
    ]
    return "\n".join(lines)


def defaults() -> tuple[Guide, ...]:
    """Every guide that ships in the box."""
    return (
        Guide(
            topic="google-oauth",
            title="Connecting your Google Calendar",
            minutes=10,
            # Deliberately NOT a summary of the body. The first draft opened
            # with the body's own first sentence, so the page said the same
            # thing twice before saying anything — which reads as padding and
            # teaches a reader to skip the top of every guide.
            why=("You only need this if you want the assistant to *change* "
                 "your calendar. Being told what is on needs nothing but a "
                 "subscription link."),
            body=_google_oauth_body,
            undo=("disconnect here, which deletes the sign-in from this "
                  "computer, and withdraw the permission in your Google "
                  "account"),
            gotchas=(
                "Google will warn you the app is unverified. It is your own "
                "project — you are the publisher, so that warning is about "
                "you.",
                "When Google asks what type of application this is, choose "
                "'Desktop app'. The other types ask for a website you do "
                "not have.",
                "If you only want to be told what is on, use a subscription "
                "address instead — two minutes, no account.",
            ),
            links=(("Google Cloud Console", "https://console.cloud.google.com"),),
        ),
        Guide(
            topic="google-drive",
            title="Reading Google Drive files that are not on this computer",
            minutes=5,
            why=("Only needed for cloud-only files, or to search a whole "
                 "Drive. The synced Drive folder needs no sign-in at all."),
            body=_google_drive_body,
            undo=("sign out here, and withdraw the permission in your Google "
                  "account"),
            gotchas=(
                "If your files are already in the Drive folder on this "
                "computer, you do not need this — that folder is faster and "
                "works offline.",
                "It is read only. Your assistant cannot change or delete "
                "anything in Drive through this.",
                "It needs the Google app from the Calendar tab first. One "
                "registration, three permissions, granted separately.",
            ),
            links=(("Your Google permissions",
                    "https://myaccount.google.com/permissions"),),
        ),
        Guide(
            topic="gmail-oauth",
            title="Signing a Gmail mailbox in with Google",
            minutes=5,
            why=("Optional, and only for Gmail. An app password does the "
                 "same job; this one can be withdrawn from your Google "
                 "account page instead."),
            body=_gmail_oauth_body,
            undo=("sign out here, which deletes the token from this "
                  "computer, and withdraw the permission in your Google "
                  "account"),
            gotchas=(
                "Google's screen asks for full access to the mailbox. That "
                "is the only permission it offers for IMAP — an app password "
                "grants exactly as much, more quietly.",
                "Sign in as the same address you added as an account. A "
                "token from another Google account is refused at login, and "
                "Gmail's error does not say which address it wanted.",
                "It needs the Google app from the Calendar tab first. One "
                "registration, two permissions, granted separately.",
            ),
            links=(("Your Google permissions",
                    "https://myaccount.google.com/permissions"),),
        ),
        Guide(
            topic="mail-app-password",
            title="Connecting a mailbox",
            minutes=5,
            why=("So the assistant can read what arrived and draft replies. "
                 "It never sends anything without being told to."),
            body=_mail_body,
            undo="delete the app password in your mail provider's settings",
            gotchas=(
                "An app password is not your normal password. If a page asks "
                "for your normal one, you are in the wrong place.",
                "Some providers only offer app passwords once two-factor "
                "sign-in is switched on.",
            ),
        ),
        Guide(
            topic="calendar-ics",
            title="Subscribing to a calendar by link",
            minutes=2,
            why=("The route that works everywhere and needs no account. "
                 "Read-only: the assistant can tell you what is on, and "
                 "cannot change it."),
            body=_ics_body,
            undo="remove the subscription here",
            gotchas=(
                "Anybody with the link can read that calendar. Treat it like "
                "a password.",
            ),
        ),
        Guide(
            topic="cloud-files",
            title="Letting the assistant see your files",
            minutes=1,
            why=("There is usually nothing to connect. If OneDrive, Google "
                 "Drive or Dropbox already sync to this machine, the folder "
                 "is simply there."),
            body=_files_body,
            undo="point it at a different folder, or none",
            gotchas=(
                "Files that live only in the cloud and have never been "
                "downloaded cannot be read until they are.",
            ),
        ),
        Guide(
            topic="telegram",
            title="Reaching you on your phone",
            minutes=3,
            why=("Without this, the assistant writes what it wanted to tell "
                 "you into a file, and you find it later."),
            body=_telegram_body,
            undo="delete the bot in @BotFather, or clear the token here",
            gotchas=(
                "Anyone who has your bot's token can send as your bot. Do "
                "not paste it into a chat.",
            ),
            links=(("BotFather", "https://t.me/BotFather"),),
        ),
        Guide(
            topic="dashboard-pin",
            title="The PIN on this dashboard",
            minutes=1,
            why="So a passer-by at your desk cannot read your assistant.",
            body=_pin_body,
            undo="change or clear it on this page",
        ),
        Guide(
            topic="semantic-search",
            title="Searching by meaning as well as by words",
            minutes=15,
            why=("Off by default, and staying that way. This guide is here "
                 "for the day you notice a search missing something you know "
                 "you wrote."),
            body=_semantic_body,
            undo="turn it off again; the index is a file you can delete",
            gotchas=(
                "Ordinary search matches words. It cannot match 'car' to "
                "'vehicle' — that gap is the only reason this exists.",
                "Turning it on downloads a model and its runtime, a few "
                "hundred megabytes. Nothing downloads until you say yes.",
                "Nothing is sent anywhere. The model runs on this machine.",
                "Meaning-matches are added to the word-matches and labelled "
                "as such, with their score. They never quietly replace what "
                "ordinary search would have found.",
                "Worth it once you have a lot of notes. With a few dozen, "
                "ordinary search already finds them and this only costs you "
                "the download.",
            ),
        ),
        Guide(
            topic="remote-access",
            title="Reaching the dashboard when you are out",
            minutes=10,
            why=("Off by default, and worth understanding before you turn it "
                 "on: this puts your assistant's screen on the internet."),
            body=_remote_body,
            undo="turn it off here, or run `aki-agent remote --off`",
            gotchas=(
                "Everything the assistant knows sits behind one six-digit PIN "
                "and a wait after wrong tries. That is a door, not a safe.",
                "It will not switch on while the PIN is still the shipped "
                "one. That is not a formality — the shipped PIN is printed in "
                "the instructions.",
                "Only the one address you type is answered, so a tunnel you "
                "start later under a new name will be refused until you come "
                "back and change it.",
                "Use a tunnel that gives you https. This cannot verify that "
                "for you: the header a tunnel uses to say so can be set by "
                "whoever is calling.",
                "Turn it off when you are back. Every page says so while it "
                "is on, which is there to remind you.",
            ),
            links=(("ngrok", "https://ngrok.com/download"),),
        ),
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

_REGISTRY = seams.Registry("guide")


def register(guide: Guide) -> None:
    _REGISTRY.register(guide)


def unregister(topic: str) -> None:
    _REGISTRY.unregister(topic)


def get(topic: str) -> Guide | None:
    return _REGISTRY.get(topic)


def topics() -> tuple[str, ...]:
    return _REGISTRY.names()


def every() -> tuple[Guide, ...]:
    return _REGISTRY.all()


def reset_to_defaults() -> None:
    _REGISTRY.clear()
    for guide in defaults():
        register(guide)


reset_to_defaults()
