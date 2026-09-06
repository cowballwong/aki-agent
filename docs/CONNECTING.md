# Connecting to the user's accounts — one way in, not three

Written 2026-08-28, against version 0.37.0, in answer to a direct question:
could a user connect Google Drive, Gmail and Calendar over OAuth, instead of
every pre-loaded tool being wired up its own way?

The complaint is correct. Today there are **three different connection methods**
and no shared layer between them.

---

## 1. Where we actually are

| Connector | Method today | User has to |
|---|---|---|
| `connectors/mail.py` | **IMAP + SMTP with an app password** | Go to their provider, create an app password, paste it |
| `connectors/google_calendar.py` | **OAuth 2.0, hand-rolled over 4 REST calls** | Create their *own* Google Cloud project, paste client id + secret, click through consent |
| `connectors/calendars.py` | **ICS URL** | Find and paste a subscription link |
| `connectors/files.py` | **A folder that is already synced** | Nothing |

All four store their credentials the same way — `secrets.py`, the OS credential
store — which is good. But *obtaining* the credential is different every time,
and every connector owns its own flow.

So OAuth is not a new idea here: **it already exists, for Calendar.** The real
questions are whether to generalise it, and who owns the OAuth client.

---

## 2. The thing that decides everything: Google's scope tiers

Google sorts every scope into three tiers, and the tier — not the API — decides
what it costs to ship.

| Tier | Verification needed | Examples |
|---|---|---|
| **Non-sensitive** | **None at all** | `drive.file` — only the files the user picks or the app itself created |
| **Sensitive** | Google review, roughly 10 days, **free** | Calendar scopes · `gmail.send` |
| **Restricted** | Review **plus an annual third-party security assessment**, paid, repeated every year | `gmail.readonly`, `gmail.modify`, `https://mail.google.com/`, full `drive`, `drive.readonly` |

Two consequences fall straight out of this:

**Reading Gmail is the only expensive thing on the whole list.** Everything else
Aki wants — writing to a calendar, sending a mail, putting a file in Drive — sits
in the free tiers.

**Aki already reads mail over IMAP**, which needs no Google review at all. So the
one scope that would trigger the annual paid assessment is the one scope Aki does
not need to ask for.

> ⚠️ Scope tiers are labelled automatically in the Google Cloud Console when you
> add a scope to a project. **Check them there before committing** — that console
> is the authority, not this document.

---

## 3. Who owns the OAuth client — the real choice

### Option A — Aki ships one verified Google app
The maintainer registers one Google Cloud project, verifies it, and the client id travels
inside the package.

- 🟢 Student clicks "Connect Google", signs in, done. No console, no pasting.
- 🟢 No user cap, no weekly token expiry.
- 🔴 Verification review for the sensitive scopes.
- 🔴 The moment a restricted scope is added, an **annual paid security
  assessment** starts, forever.
- 🔴 the maintainer carries the app's compliance, for everyone's data.

### Option B — Aki ships one *unverified* app
- 🔴 **100 users for the lifetime of the project.** It cannot be reset.
- 🔴 In Testing status refresh tokens expire **weekly** — every student
  reconnects every week.
- 🔴 They see an "unverified app" warning screen.
- Not viable for a course. Listed only so it is ruled out on the record.

### Option C — each user creates their own client id
**This is what `google_calendar.py` already does.**

- 🟢 No cap, no review, no cost, no compliance carried by the maintainer.
- 🟢 The data never passes through anything the maintainer owns.
- 🟢 The "unverified app" warning is honest — it *is* their own app.
- 🔴 Ten minutes of Google Cloud Console per student, and the console is not kind.

### The recommendation

**Keep C as the default, add A for the two free tiers, once.**

Register one Aki app with **only** `drive.file` + calendar + `gmail.send`. That
combination needs a free review and never a paid assessment. Ship it as the
one-click path. Keep "use my own client id" as the escape hatch for anyone who
wants their data to touch nothing of the maintainer's — which, for a course teaching
people to run their own agent, is a lesson rather than an inconvenience.

Never request a restricted scope. If Gmail reading is wanted, it stays on IMAP.

---

## 4. What this means for the architecture

Right now each connector obtains its own credential. That is the duplication
The maintainer is objecting to, and the fix is a seam, in the shape `seams.py` already
supports.

### The `account` seam

```
seams.Registry("account")
```

One interface, three implementations to start:

| Provider | Handles |
|---|---|
| `oauth` | The full dance: consent URL, code exchange, refresh, storage under a per-service key |
| `app_password` | Prompt, validate, store — what `mail.py` does today |
| `url` / `folder` | ICS links and synced folders — a "credential" that is really a location |

Connectors stop asking *how* and start asking *who*:

```
account.for_service("google_calendar").token()
account.for_service("mail").password()
```

What this buys, concretely:

- The OAuth refresh dance is written **once**, not once per Google service. Today
  Drive and Gmail would each re-implement what `google_calendar.py` already has.
- `aki inspect` can show every connection and its state in one list, because they
  all report into one registry.
- Revoking is uniform. `test_connection_removal.py` already exists; it would test
  one path instead of four.
- A plugin can add a provider — Microsoft, Dropbox, Notion — **without editing
  this package**, which is what `plugins.py` is for.

### Where it slots in
This makes `account` the third seam, after `calendar` and `channel`. It is a
better third seam than `mail` or `files`, because those two would each need an
auth story anyway — so auth is the layer underneath them, and it should exist
first.

---

## 5. Other services, and whether OAuth actually helps

| Service | OAuth? | Verdict for Aki |
|---|---|---|
| **Microsoft 365** (Outlook mail, calendar, OneDrive) | Yes — Microsoft Graph, one app, one consent for all three | The best case for OAuth after Google. One client covers mail + calendar + files |
| **Dropbox** | Yes, simple, no review tier like Google's | Easy win if file storage is wanted beyond a synced folder |
| **Notion** | Yes, straightforward | Useful if notes ever become a first-class area |
| **Slack** | Yes | Only if a workplace channel is wanted |
| **GitHub** | Yes, or a fine-grained PAT | PAT is simpler and enough |
| **Apple / iCloud** | **No usable OAuth** for mail or calendar | Stays on app password + CalDAV/ICS. This is a permanent exception, not a gap to close |
| **Xero, QuickBooks** | Yes | Out of scope for now |

The pattern worth noticing: **one OAuth client per *provider*, not per service.**
One Google client covers Drive, Calendar and Gmail-send. One Microsoft client
covers Outlook, Calendar and OneDrive. That is two connections for most people —
which is a very different experience from four unrelated setup flows.

And the honest caveat: **OAuth will never cover everything.** iCloud has no
usable OAuth. Some calendars will only ever be an ICS link. The `account` seam is
worth building precisely because it lets those live beside OAuth instead of
being a special case bolted on.

---

## 6. Open, not decided

- Whether the maintainer wants to own a verified Google app at all — it is a real, ongoing
  responsibility, not just a registration.
- Whether Microsoft Graph comes in the same pass or later.
- Whether `drive.file` is enough for what Aki wants to do with Drive. It only
  reaches files the user explicitly picks or the app created. If Aki needs to
  browse an existing Drive, that is the restricted tier, and the answer should be
  the synced-folder route instead.
