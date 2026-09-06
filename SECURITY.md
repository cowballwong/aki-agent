# Reporting a security problem

**Use GitHub's private vulnerability reporting**: the *Security* tab of this
repository, then *Report a vulnerability*. It opens a private thread with the
maintainer that nobody else can read, and it needs no email address from
either of us.

Please do not open a public issue for anything that would let somebody reach
another person's assistant, files, mail or credentials. Report it privately
first, and give the maintainer a chance to fix it before it is described in
public.

If that button is not there, open a normal issue saying only *"I have a
security report and private reporting is switched off"* — no details — and it
will be turned on.

> No published email address, deliberately. The obvious alternative is the
> maintainer's own inbox, which then sits in a public file being scraped for
> the life of the repository. A GitHub `users.noreply` address is not an
> alternative: it does not receive mail, so a report sent to one is a report
> nobody gets — which is worse than no address at all, because the reporter
> believes they have told somebody.

There is no bounty. There is one maintainer, working on this in evenings, who
will thank you properly and credit you in the fix unless you would rather not
be named.

## What is worth reporting

Roughly: anything that lets code, a web page, or a person who is not sitting
at the machine do something the person who installed this did not choose.

Concretely, the things this project has deliberately built defences for, so a
hole in one of them matters:

- reaching the dashboard from anywhere other than the machine it runs on,
  without the PIN
- getting the dashboard to read or write a file outside the folders it is
  meant to touch
- getting past the six-digit PIN faster than the throttle should allow
- getting the safety gate to allow one of the commands it lists as refused
- causing a released package or repository to contain somebody's secrets

Reports about the *design* rather than a specific hole are welcome too. The
composition of several individually-reasonable choices is where this project
is most likely to be wrong.

## How a release is verified

Every release zip carries `RELEASE.manifest` — a SHA-256 of every file in it —
and `RELEASE.sig`, an Ed25519 signature over that manifest. `aki upgrade`
checks the signature against the public key in `src/aki_agent/release_trust.py`
**before** it believes the manifest, then re-hashes every file against it. A
zip that is unsigned, signed by another key, or altered since it was built is
refused, and the refusal names the file and the fingerprint so it can be
compared against wherever it came from.

`--allow-unsigned` exists for somebody installing a build they made
themselves. It is never a default and nothing passes it automatically.

Why it is there: `upgrade` finds a release by looking for `Aki-Agent-Beta-*`
in Downloads, Documents and Desktop and taking the newest. Before 2026-09-06
the only check was structural, so getting a file with that name onto somebody's
machine was the whole attack — and it landed the next time they did the thing
they are told to do.

The private key is on one machine and is in no repository. The verification is
`src/aki_agent/ed25519.py`, the RFC 8032 reference implementation on the
standard library alone, so that a failed `pip install` can never leave the
check quietly absent. It is checked against the RFC's own vectors and, where
the `cryptography` package is present, byte-for-byte against it.

Installing from the GitHub repository does not use any of this: there, the
integrity guarantee is git's and GitHub's.

## What is already known and stated

These are documented trade-offs, not undiscovered holes. Telling us they exist
is not a finding; telling us one is worse than we think would be.

- **The safety gate is a short denylist and it fails open.** A gate that
  blocks ordinary work is a gate that gets switched off, and a gate that
  blocks everything when it breaks is worse than none. It covers commands
  whose worst case is unrecoverable, and it records every time it could not
  run. See `src/aki_agent/safety_gate.py`.
- **The assistant can be run without permission prompts.** That is the
  product. The refusals above are the floor underneath it, and the launcher
  prints that list at the moment the mode is chosen.
- **Anything you connect, it can use.** Granting it your mail means it can
  read your mail. The gates are on sending, publishing and deleting.
- **The dashboard trusts whoever is at the keyboard, after the PIN.** It is a
  personal tool on a personal machine, not a multi-user system.

## What this project cannot promise

One maintainer, no security team, no service to take offline. There is no
committed response time. Expect an answer within a week or so, and a fix in a
release rather than a hotfix — the honest version, rather than a number
nobody is on call to keep.

macOS is written and reviewed but has never been executed by the maintainer.
A macOS-specific report is especially useful and will be taken on trust to a
degree a Windows one would not need to be.
