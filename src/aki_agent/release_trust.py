"""Is this release one we built, or one somebody put on the disk?

THE HOLE THIS CLOSES
--------------------
`upgrade` finds a release by globbing `Aki-Agent-Beta-*` across Downloads,
Documents and Desktop and taking whichever was modified most recently. The
only check was structural -- "is there a `src/aki_agent` inside" -- which any
copy of this package passes, including one somebody edited.

So the attack needed no cleverness at all: get a file with that name onto a
student's machine, by any of the ordinary routes a file arrives -- a download
they were talked into, a USB stick, an email attachment, a second browser tab
-- and wait. The next time they upgrade, which is a thing they are *told* to
do, the contents are copied over their engine and run. No prompt they would
recognise as a decision, because from where they sit they pressed "upgrade"
and it upgraded.

TWO GATES, AND WHY BOTH
-----------------------
1. **Identity.** The file is named, with its fingerprint, and an upgrade the
   person did not point at a specific file will not proceed on its own. This
   gate needs no cryptography and so cannot be defeated by a mistake in any.
2. **Signature.** A release built by the maintainer carries a manifest of every file
   in it, signed with a key that exists on one machine. Verified here against
   the public half below.

Gate 2 is the real one. Gate 1 is there because gate 2 is code I wrote, and a
security check whose failure mode is "silently allow" should never be the
only thing standing up. Signed-and-verified is the *only* state that upgrades
without a person saying yes to a named file.

WHAT A SIGNATURE HERE DOES NOT MEAN
-----------------------------------
It means these bytes came from the maintainer's build. It says nothing about whether
what he built is safe, and it is not a substitute for reading a release. It
also cannot help a machine that is already compromised: an attacker who can
edit this file can edit the key in it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from . import ed25519

# The file listing every file in the release and its hash, and the signature
# over that listing. Both sit at the top of the package, beside `src/`.
MANIFEST_NAME = "RELEASE.manifest"
SIGNATURE_NAME = "RELEASE.sig"

# The public half of the release key. The private half is on one machine, at
# `~/.aki-release/signing-key.hex`, has never been on the Google Drive
# workspace, and is not in this repository.
#
# A list rather than a single value so a key can be replaced without the
# release that carries the new one being unverifiable by the version people
# are upgrading *from* -- retire a key by leaving it here for one release and
# removing it in the next.
TRUSTED_KEYS: dict[str, str] = {
    "anzon-2026-09": "c3c038c51cdc21c7585f5f4d8078989276a9e4eac1d63b64fdcc51c42455e1c6",  # not-a-secret: published value
}

# Never part of what is signed: the signature cannot cover itself, and
# `__pycache__` is built on the installing machine, not shipped.
NOT_SIGNED = {MANIFEST_NAME, SIGNATURE_NAME}
NOT_SIGNED_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache"}


@dataclass
class Verdict:
    """What is known about a release, in the words the user will be shown."""

    trusted: bool = False
    signer: str = ""
    problem: str = ""
    fingerprint: str = ""
    differences: list[str] = field(default_factory=list)

    def sentence(self) -> str:
        if self.trusted:
            return f"signed by {self.signer}, and every file matches"
        return self.problem or "not signed"


def fingerprint(path: Path) -> str:
    """SHA-256 of a file, as the user will be shown it.

    Shown in full rather than shortened. A truncated hash invites comparing
    the first six characters, and the whole point of showing it is that it is
    compared against something.
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


def _files_to_sign(root: Path) -> list[Path]:
    """Every file a manifest covers, in a stable order.

    Sorted by the POSIX-style relative path, so a manifest built on Windows
    and one built on macOS come out identical.
    """
    found = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in NOT_SIGNED_DIRS for part in relative.parts):
            continue
        if relative.as_posix() in NOT_SIGNED:
            continue
        if path.suffix in (".pyc", ".pyo"):
            continue
        found.append(path)
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def manifest_text(entries: list[tuple[str, Path]]) -> str:
    """The text that gets signed: one `sha256  path` line per file, sorted.

    Takes (relative name, file) pairs rather than walking a folder, because
    the release script signs a list of files it has already chosen and has
    never assembled on disk. Both callers must produce byte-identical text
    for the same release, so the sorting and the two-space separator live
    here and nowhere else.
    """
    lines = [f"{fingerprint(path)}  {relative}"
             for relative, path in sorted(entries)]
    return "\n".join(lines) + "\n"


def build_manifest(root: Path) -> str:
    """The manifest for a package that exists as a folder."""
    root = Path(root)
    return manifest_text([(p.relative_to(root).as_posix(), p)
                          for p in _files_to_sign(root)])


def sign_release(root: Path, secret_key_hex: str) -> None:
    """Write the manifest and its signature into a built package.

    Called by the release script, on the machine holding the key. Nothing in
    the installed package ever calls this.
    """
    root = Path(root)
    manifest = build_manifest(root)
    (root / MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    signature = ed25519.sign(manifest.encode("utf-8"),
                             bytes.fromhex(secret_key_hex.strip()))
    (root / SIGNATURE_NAME).write_text(signature.hex() + "\n", encoding="utf-8")


def verify_package(root: Path) -> Verdict:
    """Check a release folder against its own signed manifest.

    The order matters. The signature is checked *first*, against the manifest
    as it sits on the disk; only then are the files compared to it. Done the
    other way round, an attacker who rewrote both the files and the manifest
    would sail through the comparison and the signature check would be a
    formality on a document they wrote.
    """
    root = Path(root)
    manifest_file = root / MANIFEST_NAME
    signature_file = root / SIGNATURE_NAME

    if not manifest_file.exists() or not signature_file.exists():
        return Verdict(problem="this release is not signed")

    try:
        manifest = manifest_file.read_text(encoding="utf-8")
        signature = bytes.fromhex(signature_file.read_text().strip())
    except (OSError, ValueError):
        return Verdict(problem="the signature on this release is unreadable")

    body = manifest.encode("utf-8")
    signer = ""
    for name, key in TRUSTED_KEYS.items():
        if ed25519.verify(signature, body, bytes.fromhex(key)):
            signer = name
            break
    if not signer:
        return Verdict(problem="the signature on this release is not one I "
                               "recognise -- it was not built by the maintainer")

    # Now the manifest is known to be his. Does the folder match it?
    promised = {}
    for line in manifest.splitlines():
        if not line.strip():
            continue
        digest, _, relative = line.partition("  ")
        promised[relative] = digest

    actual = {p.relative_to(root).as_posix(): fingerprint(p)
              for p in _files_to_sign(root)}

    differences = []
    for relative, digest in sorted(promised.items()):
        if relative not in actual:
            differences.append(f"missing: {relative}")
        elif actual[relative] != digest:
            differences.append(f"changed: {relative}")
    # Extra files are a difference too, and the interesting one: adding a file
    # is how you get code into a package without touching anything listed.
    for relative in sorted(actual):
        if relative not in promised:
            differences.append(f"added:   {relative}")

    if differences:
        return Verdict(signer=signer,
                       problem=(f"signed by {signer}, but "
                                f"{len(differences)} file(s) do not match "
                                "the signature"),
                       differences=differences[:20])

    return Verdict(trusted=True, signer=signer)


def describe(source: Path, verdict: Verdict) -> list[str]:
    """The lines shown to somebody about to install this. Plain words."""
    lines = [f"  file        {source}"]
    if verdict.fingerprint:
        lines.append(f"  fingerprint {verdict.fingerprint}")
    if verdict.trusted:
        lines.append(f"  signature   OK -- signed by {verdict.signer}")
    else:
        lines.append(f"  signature   NOT VERIFIED -- {verdict.problem}")
        for difference in verdict.differences:
            lines.append(f"                {difference}")
    return lines
