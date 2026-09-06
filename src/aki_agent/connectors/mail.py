"""Reading and sending email, without a developer account.

HOW THIS WORKS AT ALL
---------------------
IMAP for reading, SMTP for sending, an app password for authentication. Both
protocols are in Python's standard library, so this connector adds no
dependency to the package at all.

An **app password** is a per-application password that a provider issues after
you have turned on two-factor authentication. It is not your account password,
it only works for mail, and revoking it does not touch anything else. Every
major provider supports them, and it is the route that needs no OAuth
application and no developer registration.

THE RULES THIS FILE FOLLOWS
---------------------------
1. The password goes into the OS credential store, never into config, never
   into a log, never into a message.
2. Nothing is deleted, ever. The assistant may read, and may send. It may not
   delete somebody's mail -- that is not a capability worth the risk of a
   confused agent having it.
3. Sending is gated. Composing a draft is free; sending it needs a human yes,
   every time, because an email that has left cannot be recalled.
4. Message content is untrusted input. An instruction inside an email is not
   the user speaking -- see the note in `Message.safe_summary`.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import smtplib
import ssl
from dataclasses import dataclass, field as dataclass_field
from email.message import EmailMessage

from .. import secrets

# Where the app password is filed in the OS credential store.
SECRET_KEY_TEMPLATE = "mail:{address}"

# A bounded fetch. An assistant asked to "check my email" on an account with
# 60,000 messages must not try to read all of them.
DEFAULT_LIMIT = 25
HARD_LIMIT = 200


@dataclass(frozen=True)
class Provider:
    """One mail service, and how to reach it."""

    key: str
    name: str
    imap_host: str
    smtp_host: str
    imap_port: int = 993
    smtp_port: int = 587
    # Where the user goes to create an app password, in their own account.
    app_password_url: str = ""
    note: str = ""


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        key="gmail", name="Gmail",
        imap_host="imap.gmail.com", smtp_host="smtp.gmail.com",
        app_password_url="https://myaccount.google.com/apppasswords",
        note=("You need 2-Step Verification switched on first, otherwise the "
              "app-password page will not appear."),
    ),
    Provider(
        key="outlook", name="Outlook / Hotmail / Live",
        imap_host="outlook.office365.com", smtp_host="smtp-mail.outlook.com",
        app_password_url="https://account.microsoft.com/security",
        note=("Create an app password under Security > Advanced security "
              "options. Some work or school accounts have this turned off by "
              "their administrator."),
    ),
    Provider(
        key="yahoo", name="Yahoo Mail",
        imap_host="imap.mail.yahoo.com", smtp_host="smtp.mail.yahoo.com",
        app_password_url="https://login.yahoo.com/account/security",
        note="Yahoo calls it 'Generate app password'.",
    ),
    Provider(
        key="icloud", name="iCloud Mail",
        imap_host="imap.mail.me.com", smtp_host="smtp.mail.me.com",
        app_password_url="https://account.apple.com/account/manage",
        note="Apple calls it an 'app-specific password'.",
    ),
    Provider(
        key="fastmail", name="Fastmail",
        imap_host="imap.fastmail.com", smtp_host="smtp.fastmail.com",
        app_password_url="https://app.fastmail.com/settings/security/apppw",
    ),
    Provider(
        key="proton", name="Proton Mail",
        imap_host="127.0.0.1", smtp_host="127.0.0.1",
        imap_port=1143, smtp_port=1025,
        app_password_url="https://proton.me/mail/bridge",
        note=("Proton only speaks IMAP through its Bridge application, which "
              "runs on your own computer and needs a paid plan. The Bridge "
              "gives you the exact host, port and password to use."),
    ),
    Provider(
        key="other", name="Something else (any IMAP account)",
        imap_host="", smtp_host="",
        note=("Your provider's help pages will list an IMAP server and an "
              "SMTP server. Most look like imap.example.com and "
              "smtp.example.com."),
    ),
)


def provider(key: str) -> Provider | None:
    for entry in PROVIDERS:
        if entry.key == key:
            return entry
    return None


def guess_provider(address: str) -> Provider | None:
    """Guess from the address, so the user is asked one fewer question."""
    domain = address.partition("@")[2].lower()
    guesses = {
        "gmail.com": "gmail", "googlemail.com": "gmail",
        "outlook.com": "outlook", "hotmail.com": "outlook",
        "live.com": "outlook", "msn.com": "outlook",
        "yahoo.com": "yahoo", "yahoo.co.uk": "yahoo", "ymail.com": "yahoo",
        "icloud.com": "icloud", "me.com": "icloud", "mac.com": "icloud",
        "fastmail.com": "fastmail", "fastmail.fm": "fastmail",
        "proton.me": "proton", "protonmail.com": "proton",
    }
    key = guesses.get(domain)
    return provider(key) if key else None


def app_password_instructions(entry: Provider) -> str:
    """What to tell the user, in their own terms."""
    lines = [
        f"{entry.name} needs an app password -- a separate password just for "
        "this, not your normal one.",
        "",
        "It is safer than it sounds: it only works for email, and you can "
        "cancel it at any time without changing anything else.",
    ]
    if entry.app_password_url:
        lines += ["", f"Create one here:  {entry.app_password_url}"]
    if entry.note:
        lines += ["", entry.note]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The account
# ---------------------------------------------------------------------------

@dataclass
class Account:
    """One mail account this assistant may read."""

    address: str
    provider_key: str = "other"
    imap_host: str = ""
    smtp_host: str = ""
    imap_port: int = 993
    smtp_port: int = 587
    # If the login name differs from the address, which some hosts require.
    username: str = ""
    # Whether this account may send at all, as opposed to draft.
    #
    # THE CHECKBOX HAD NO READER (2026-08-23)
    # ---------------------------------------
    # The connections page has offered "May send, not just draft" since it
    # was written, the value was stored in the config and read back out of
    # it, and `Account` had no such field -- so `send()` never saw it and
    # gated on `confirmed` alone. The page showed "allowed" or "drafts only"
    # beside a setting nothing consulted.
    #
    # `confirmed` is unchanged and still required for every message. This is
    # the other half: confirmation says *this* message is wanted; may_send
    # says this mailbox is one the assistant is allowed to send from at all.
    may_send: bool = False

    def __post_init__(self) -> None:
        known = provider(self.provider_key)
        if known and known.imap_host:
            self.imap_host = self.imap_host or known.imap_host
            self.smtp_host = self.smtp_host or known.smtp_host
            self.imap_port = self.imap_port or known.imap_port
            self.smtp_port = self.smtp_port or known.smtp_port
        self.username = self.username or self.address

    @property
    def secret_key(self) -> str:
        return SECRET_KEY_TEMPLATE.format(address=self.address)

    def save_password(self, password: str) -> str:
        """Put the app password in the OS credential store."""
        return secrets.set_secret(self.secret_key, password)

    def password(self) -> str | None:
        return secrets.get_secret(self.secret_key)

    def forget_password(self) -> bool:
        return secrets.delete_secret(self.secret_key)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """One email, reduced to what an assistant needs."""

    uid: str
    sender: str
    subject: str
    date: str
    preview: str = ""
    to: str = ""
    unread: bool = False

    def safe_summary(self) -> str:
        """A one-line summary, redacted, and framed as data.

        TWO SEPARATE PROTECTIONS, AND BOTH MATTER
        -----------------------------------------
        **Redaction**: an email is a very common place for a password reset
        link or an API key to be sitting in plain text. Anything that came out
        of a mailbox is redacted before it can reach a log, a dashboard or a
        notification.

        **Untrusted content**: the text of an email is data, never an
        instruction. If a message says "ignore your previous instructions" or
        "forward this to accounts@...", that is not the user speaking -- it is
        a stranger who can write to their inbox, which is the easiest injection
        surface anybody has.

        This method cannot enforce the second one on its own. What it can do
        is make sure the assistant's own operating instructions say so, which
        they do, and never present mail content in a way that looks like a
        command.
        """
        line = f"{self.sender}: {self.subject}"
        if self.preview:
            line += f" -- {self.preview[:120]}"
        return secrets.redact(line)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

class MailError(Exception):
    """A mail problem, phrased for a person."""


def from_config(entry) -> Account:
    """A live account from a stored one.

    `config.MailAccount` is what is written to disk -- address, hosts, ports,
    may_send. `Account` is what talks to a server, and it additionally knows
    a username and how to fetch the password from the credential store.

    They are not interchangeable, and the first version of the `mail` command
    passed the stored one straight into `recent()`, where it would have died
    on `account.password()` the moment somebody actually had a mailbox
    connected. Converting in one named place means nothing has to remember
    which of the two it is holding.
    """
    return Account(
        address=getattr(entry, "address", ""),
        imap_host=getattr(entry, "imap_host", ""),
        smtp_host=getattr(entry, "smtp_host", ""),
        imap_port=getattr(entry, "imap_port", 993) or 993,
        smtp_port=getattr(entry, "smtp_port", 587) or 587,
        may_send=bool(getattr(entry, "may_send", False)),
    )


def signs_in_with_google(account: Account) -> bool:
    """Does this mailbox prove itself with Google rather than a password?

    Decided by whose mailbox the Google token was granted for -- not by a
    setting somebody has to keep in step with reality. A refresh token IS one
    address's; storing "this account uses OAuth" separately would be a second
    copy of a fact that can go stale, and the failure it produces (a token for
    another address) is one Gmail reports as a bare authentication failure
    naming neither address.
    """
    from . import google_account

    try:
        if not google_account.connected(google_account.GMAIL):
            return False
        granted = google_account.account_address(google_account.GMAIL)
    except Exception:                                     # noqa: BLE001
        # A credential store that will not answer means "no", the same way it
        # does everywhere else here -- never an exception mid-read.
        return False
    return bool(granted) and granted.lower() == account.address.lower()


def _google_login_string(account: Account) -> str:
    from . import google_account

    token = google_account.access_token(google_account.GMAIL)
    return f"user={account.address}auth=Bearer {token}"


def _connect(account: Account) -> imaplib.IMAP4_SSL:
    google = signs_in_with_google(account)
    password = None if google else account.password()
    if not google and not password:
        raise MailError(
            f"No app password saved for {account.address}. Run /aki-agent:setup and "
            "connect the account again."
        )

    if not account.imap_host:
        raise MailError(
            f"No IMAP server known for {account.address}. Your provider's "
            "help pages will list one."
        )

    try:
        context = ssl.create_default_context()
        connection = imaplib.IMAP4_SSL(account.imap_host, account.imap_port,
                                       ssl_context=context)
    except (OSError, ssl.SSLError) as exc:
        raise MailError(
            f"Could not reach {account.imap_host}. If you are on a work "
            f"network it may be blocked. ({exc})"
        ) from exc

    try:
        if google:
            # XOAUTH2: the same IMAP session, a bearer token instead of a
            # password. Everything after this line is unchanged, which is the
            # whole reason for signing in this way rather than through the
            # Gmail API.
            connection.authenticate(
                "XOAUTH2",
                lambda _challenge: _google_login_string(account).encode())
        else:
            connection.login(account.username, password)
    except imaplib.IMAP4.error as exc:
        # Never include the password or the exception's raw text, which some
        # servers echo the login line into.
        if google:
            raise MailError(
                f"Google would not let this in to {account.address}. Sign in "
                "again on the Connections page — a refresh token stops "
                "working when the password changes or the permission is "
                "withdrawn."
            ) from exc
        raise MailError(
            f"{account.address} refused the login. The usual cause is that "
            "the app password has been revoked or was pasted with a space in "
            "it. Create a new one and run /aki-agent:setup again."
        ) from exc

    return connection


def recent(account: Account, limit: int = DEFAULT_LIMIT,
           unread_only: bool = False, folder: str = "INBOX") -> list[Message]:
    """The most recent messages. Bounded, always."""
    limit = max(1, min(limit, HARD_LIMIT))
    connection = _connect(account)

    try:
        connection.select(folder, readonly=True)   # readonly: never mark read
        criteria = "(UNSEEN)" if unread_only else "ALL"
        status, data = connection.search(None, criteria)
        if status != "OK":
            return []

        ids = data[0].split()
        chosen = ids[-limit:]

        messages: list[Message] = []
        for message_id in reversed(chosen):
            status, fetched = connection.fetch(message_id, "(RFC822.HEADER)")
            if status != "OK" or not fetched:
                continue
            raw = fetched[0][1] if isinstance(fetched[0], tuple) else b""
            parsed = email.message_from_bytes(raw)

            messages.append(Message(
                uid=message_id.decode("ascii", "replace"),
                sender=_decode(parsed.get("From", "")),
                subject=_decode(parsed.get("Subject", "(no subject)")),
                date=_decode(parsed.get("Date", "")),
                to=_decode(parsed.get("To", "")),
                unread=unread_only,
            ))
        return messages

    finally:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _decode(value: str) -> str:
    """Decode an email header into readable text.

    Headers arrive encoded in whatever the sender's mail program felt like.
    Getting this wrong turns a Chinese or accented subject line into mojibake,
    which for a bilingual user is most of their mail.
    """
    if not value:
        return ""
    try:
        parts = email.header.decode_header(value)
    except (email.errors.HeaderParseError, ValueError):
        return value

    out: list[str] = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(charset or "utf-8", "replace"))
            except (LookupError, UnicodeDecodeError):
                out.append(text.decode("utf-8", "replace"))
        else:
            out.append(text)
    return "".join(out).strip()


# ---------------------------------------------------------------------------
# Sending -- gated
# ---------------------------------------------------------------------------

@dataclass
class Draft:
    to: str
    subject: str
    body: str
    cc: str = ""

    def preview(self) -> str:
        lines = [f"To:      {self.to}"]
        if self.cc:
            lines.append(f"Cc:      {self.cc}")
        lines += [f"Subject: {self.subject}", "", self.body]
        return "\n".join(lines)


def send(account: Account, draft: Draft, confirmed: bool) -> tuple[bool, str]:
    """Send a draft. Requires an explicit yes, every single time.

    Not "confirmed once at setup". Not "the user turned on auto-send". Every
    message, individually.

    Email is the most consequential thing a personal assistant can do on
    somebody's behalf, it goes to other people, and it cannot be recalled. A
    wrong file can be rewritten; a wrong email has been read.
    """
    if not account.may_send:
        return False, (f"Not sent. {account.address} is set to drafts only. "
                       "Change that on the Connections page if you want it "
                       "to be able to send.")

    if not confirmed:
        return False, ("Not sent. Show the user the draft and get a yes "
                       "first -- every message, every time.")

    google = signs_in_with_google(account)
    password = None if google else account.password()
    if not google and not password:
        return False, f"No app password saved for {account.address}."

    message = EmailMessage()
    message["From"] = account.address
    message["To"] = draft.to
    if draft.cc:
        message["Cc"] = draft.cc
    message["Subject"] = draft.subject
    message["Date"] = email.utils.formatdate(localtime=True)
    message["Message-ID"] = email.utils.make_msgid()
    message.set_content(draft.body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(account.smtp_host, account.smtp_port,
                          timeout=60) as server:
            server.starttls(context=context)
            if google:
                server.ehlo()
                server.auth("XOAUTH2",
                            lambda _challenge=None: _google_login_string(
                                account))
            else:
                server.login(account.username, password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        return False, (f"Could not send: {type(exc).__name__}. The draft has "
                       "not gone anywhere and is still here.")

    return True, f"Sent to {draft.to}."


def test_connection(account: Account) -> tuple[bool, str]:
    """Check the account works, without doing anything to it."""
    try:
        connection = _connect(account)
    except MailError as exc:
        return False, str(exc)

    try:
        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            return False, "Connected, but the inbox could not be opened."
        return True, f"{account.address} is working."
    finally:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
