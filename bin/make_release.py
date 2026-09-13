"""Build a distributable zip of this package into _release/.

Why this exists
---------------
Until the package has a git repository and a marketplace to be served from,
the way a student gets it is: receive a zip, unzip it, then point
`claude plugin marketplace add` at the unzipped folder. That is a real plugin
install -- skills and agents land where Claude Code reads them -- it simply
has no automatic updates.

So each build is a dated snapshot: Aki-Agent-Beta-YYYY-MM-DD.zip

What it deliberately leaves out
-------------------------------
- `_release/` itself. A zip that contains every previous zip doubles in size
  each build. This is the one exclusion that is not merely tidiness.
- `desktop.ini` -- Google Drive writes these all over a synced folder. They
  are invisible on Windows and confusing rubbish on a Mac.
- `__pycache__`, `.pytest_cache`, `*.pyc` -- another machine's compiled
  bytecode is at best useless and at worst stale.
- `config.yaml`, `secrets.json` -- a user's own configuration lives in their
  home folder and must never travel inside a package. These should not be
  here at all; the rule is stated so a stray copy cannot escape.

What it deliberately keeps
--------------------------
`tests/`. After a student's assistant integrates any of this, INTEGRATE.md
tells it to run `tests/test_two_configs.py` to prove nothing was hardcoded.
Strip the tests and that verification step becomes impossible.

Usage
-----
    python bin/make_release.py            # dated build
    python bin/make_release.py --date 2026-08-16
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from aki_agent import release_trust  # noqa: E402

# The private half of the release key. One machine, never in this repository,
# and never on the Google Drive workspace -- that folder was found shared
# "anyone with the link can edit" on 2026-08-07, and a signing key there would
# let anybody sign a release every installed copy would then trust silently.
SIGNING_KEY_FILE = Path.home() / ".aki-release" / "signing-key.hex"


def signing_key() -> str:
    """The key, or "" on a machine that does not hold it."""
    try:
        return SIGNING_KEY_FILE.read_text(encoding="utf-8").split()[0].strip()
    except (OSError, IndexError):
        return ""


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
RELEASE_DIR = PACKAGE_ROOT / "_release"

# Directory names dropped wherever they appear.
#
# This list is a denylist, so anything new in the tree ships by default and
# the mistake is silent. `_audit/` was added to `.gitignore` on 2026-09-05 and
# shipped anyway on the next release, because this script reads the disk and
# has never read `.gitignore`. `.ruff_cache` had been shipping since whenever
# ruff was first run here. Two rules below catch the shape rather than the
# name: a dot-directory is a tool's, and a leading underscore is ours and
# private. Keep adding names here too -- the rules are a net, not a policy.
# Shared with the signer rather than copied. These two lists were allowed to
# disagree once and a single `desktop.ini` then made a signed release
# impossible (2026-09-12) — the manifest describes a release, so what a
# release leaves out and what a signature leaves out have to be one set.
# The secret-bearing names below stay here: those are release safety, and the
# signer WANTS to see a stray `.env` so it can refuse to sign it.
EXCLUDED_DIRS = set(release_trust.NOT_SIGNED_DIRS)

# Kept out by shape, so a folder nobody remembered to name is still kept out.
# `.claude-plugin` is the one dot-directory that MUST ship -- it is how Claude
# Code finds the plugin at all -- so it is named rather than inferred.
DOT_DIRS_THAT_SHIP = {".claude-plugin", ".claude"}


def _is_private_dir(name: str) -> bool:
    """A tool's folder, or one of ours that was never meant to leave."""
    if name in DOT_DIRS_THAT_SHIP:
        return False
    return name.startswith(".") or name.startswith("_")

# Exact file names dropped wherever they appear.
# Entries are written WITHOUT the MS-DOS ReadOnly bit.
#
# WHY, AND WHAT WAS ACTUALLY MEASURED (2026-08-20)
# ------------------------------------------------
# An upgrade on a user's machine failed repeatedly because 45 directories in
# their installed engine carried Windows' ReadOnly attribute, and `rmtree`
# ends each directory with `os.rmdir`, which returns WinError 5 on one. Their
# evidence is unambiguous: `(Get-Item ...).Attributes -> ReadOnly, Directory`,
# and `Remove-Item -Force` (which clears the bit first) succeeded where Python
# had failed.
#
# The obvious conclusion -- "the zip ships the attribute" -- was checked and is
# NOT true, so it is written down here rather than left as folklore:
#
#   * the zip stores **zero directory entries**; extractors create the
#     directories themselves, with attributes this build does not control
#   * zero entries in the previous release carried the ReadOnly bit either
#   * extracting that zip, and copying the source tree with `copytree`,
#     both produce zero ReadOnly directories on the build machine
#
# So the attribute arises on the user's machine -- their extraction tool, sync
# client or folder policy -- and this change cannot be the fix. It is kept
# because it costs nothing and closes one route in; the fix that actually
# works is at the install end, where `engine.force_rmtree` clears the bit on
# the way past and `engine.clear_readonly` stops the new install inheriting
# it. Do not delete those on the strength of this line.

# MS-DOS attribute bit 0, in the low half of a zip entry's external_attr.
READ_ONLY_BIT = 0x01

# `NOT_SIGNED` too (2026-09-13). Since the repo carries its own RELEASE.manifest
# and RELEASE.sig, the build copied them in AND listed them in the zip's own
# manifest, then wrote a second pair on top. The verifier rightly ignores those
# two names, so every zip reported them "missing" and `upgrade --from` refused
# a release this script had just signed. Found by extracting 0.49.1 and running
# the real check rather than trusting "Signed 514 files".
EXCLUDED_FILES = set(release_trust.NOT_SIGNED_NAMES) | set(release_trust.NOT_SIGNED) | {
    "config.yaml",
    "secrets.json",
    # 2026-08-23. `.gitignore` claimed ".env" was "stated here as well as in
    # make_release.py so a stray copy cannot escape either route". It was
    # not. One .env dropped into the build folder and the next release would
    # have zipped it to a whole class.
    ".env",
    ".env.local",
    "secrets.yaml",
    "credentials.json",
    "client_secret.json",
    "token.json",
}

EXCLUDED_SUFFIXES = set(release_trust.NOT_SIGNED_SUFFIXES) | {
    # Not signing exclusions: these carry data or keys, and only a release
    # needs them gone.
    ".jsonl", ".pem", ".key"}

# Files that must arrive executable on macOS and Linux.
#
# This is not cosmetic. A zip built on Windows records the permissions Windows
# has, and Windows has no executable bit -- every file lands as 0o666. Unzip
# that on a Mac and double-clicking `check.command` fails with "you aren't
# allowed to execute", which is the first thing a new user ever does. The
# script is fine; it simply cannot be run. So the mode is set here explicitly
# rather than inherited from the building machine.
EXECUTABLE_SUFFIXES = {".sh", ".command"}
EXECUTABLE_MODE = 0o755


def _is_excluded(path: Path) -> bool:
    """True if this file should not travel to a student's machine."""
    relative = path.relative_to(PACKAGE_ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return True
    # The shape rule, applied to DIRECTORIES only -- `relative.parts[:-1]`
    # leaves the file's own name out, so `.gitignore` and `_bootstrap.py`
    # still ship. Added 2026-09-05, after `_audit/` shipped despite being in
    # `.gitignore`: this script has never read that file and a denylist of
    # names cannot exclude a folder nobody has created yet.
    if any(_is_private_dir(part) for part in relative.parts[:-1]):
        return True
    if path.name in EXCLUDED_FILES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    # `*.egg-info` is a directory, so the check has to look at every part of
    # the path rather than at the file's own name -- checking the name alone
    # let a whole stale egg-info folder into the first build.
    if any(part.endswith(".egg-info") for part in relative.parts):
        return True
    return False


# Names that must never travel, whatever the extension says. Checked AFTER
# collection rather than during it, because the point is to stop the build
# rather than to quietly drop the file -- a denylist that silently skips
# something is indistinguishable from one that never saw it.
SUSPICIOUS = (".env", "secret", "credential", "password", "token",
              "_rsa", "id_ed25519", ".pfx", ".p12", "cookies")
SUSPICIOUS_ALLOWED = {"tests/fake_credentials.py", "src/aki_agent/secrets.py",
                      "docs/STATUS.md",
                      # Tests OF the credential store, so their names contain
                      # the words the scan looks for. Added 2026-09-06, when
                      # the first of them stopped a release -- which is the
                      # scan behaving correctly: it matches on the path, it
                      # cannot tell a test about passwords from a file of
                      # them, and stopping is the right answer to that
                      # ambiguity. Each entry read before it was added.
                      "tests/test_secrets_file_is_locked_down.py",
                      "tests/test_pin_reset_is_limited.py",
                      "tests/test_forgot_pin_route.py"}


def refuse_anything_secret(files: list[Path]) -> None:
    """Stop the build rather than ship a secret.

    A denylist over a whole build folder cannot enumerate what it has not
    thought of, which is the failure mode that matters: the release builder
    was written before Telegram sessions, before `.claude/settings.local.json`
    and before half of what now lands beside the package. So instead of
    trusting the list to be complete, anything that looks like a credential
    stops the build and says so.
    """
    caught = []
    for path in files:
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        if relative in SUSPICIOUS_ALLOWED:
            continue
        low = relative.lower()
        if any(mark in low for mark in SUSPICIOUS):
            caught.append(relative)
    if caught:
        listed = "\n  ".join(caught)
        raise SystemExit(
            "Refusing to build. These look like credentials and would have "
            f"shipped to every student:\n  {listed}\n\n"
            "Move them out of the package folder, or add the path to "
            "SUSPICIOUS_ALLOWED if it is genuinely safe.")


def collect_files() -> list[Path]:
    files = sorted(
        p for p in PACKAGE_ROOT.rglob("*") if p.is_file() and not _is_excluded(p)
    )
    refuse_anything_secret(files)
    return files


def package_version() -> str:
    """The one place a version is declared, read rather than repeated.

    Three files used to carry it -- the package, the project metadata and the
    plugin manifest -- and nothing checked that they agreed. A test now does;
    this reads the package, which is the copy that actually ships.
    """
    text = (PACKAGE_ROOT / "src" / "aki_agent" / "__init__.py").read_text(
        encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("No __version__ in the package -- refusing to guess one.")


def _unused_name(version: str, date_stamp: str) -> Path:
    """Aki-Agent-Beta-YYYYMMDD-NNN.zip -- date, then that day's build number.

    A DATE ALONE IS NOT AN IDENTITY. The first version of this script named
    builds by date only, and on the day the package changed most, five
    different zips were written to the same filename -- so "the 17 August
    build" named five different pieces of software and nobody could tell which
    one they were holding.

    The counter fixes that without pretending each rebuild is a new release:
    the day says when, `001` says which one that day, and an existing file is
    never overwritten. Whatever someone downloaded keeps meaning what it meant.

    The semantic version still exists and still matters -- it names the folder
    the plugin installs into -- but it belongs in the manifest, not in a file
    name a person has to read out over the phone.
    """
    compact = date_stamp.replace("-", "")
    base = f"Aki-Agent-Beta-{compact}"
    build_number = 1
    candidate = RELEASE_DIR / f"{base}-{build_number:03d}.zip"
    while candidate.exists():
        build_number += 1
        candidate = RELEASE_DIR / f"{base}-{build_number:03d}.zip"
    return candidate


def _warn_if_version_reused(version: str, target: Path) -> None:
    """Warn when an earlier zip already went out under this same version.

    Not a refusal: rebuilding the same version during a day's work is normal
    and useful. But shipping *changes* under a version a user already has is
    the one case where an upgrade silently does nothing, so it has to be said
    at the moment the zip is written rather than discovered by a person whose
    dashboard did not change.
    """
    others = sorted(p for p in RELEASE_DIR.glob("Aki-Agent-Beta-*.zip")
                    if p != target)
    if not others:
        return

    seen: list[str] = []
    for archive in others:
        try:
            with zipfile.ZipFile(archive) as opened:
                for name in opened.namelist():
                    if name.endswith(".claude-plugin/plugin.json"):
                        if f'"version": "{version}"' in opened.read(
                                name).decode("utf-8", "replace"):
                            seen.append(archive.name)
                        break
        except (OSError, zipfile.BadZipFile):        # pragma: no cover
            continue

    if seen:
        print()
        print(f"  NOTE: version {version} has already shipped, in "
              f"{', '.join(seen[-3:])}.")
        print("  Claude Code compares the plugin version, so `claude plugin "
              "update` will")
        print("  see nothing new. Bump __version__, pyproject.toml and "
              "plugin.json together")
        print("  if anybody is expected to upgrade into this build.")


def build(date_stamp: str) -> Path:
    """Write the zip and return its path. Never replaces an existing build."""
    RELEASE_DIR.mkdir(exist_ok=True)
    version = package_version()
    target = _unused_name(version, date_stamp)

    files = collect_files()
    if not files:
        raise SystemExit("Nothing to package -- refusing to write an empty zip.")

    _warn_if_version_reused(version, target)

    # Everything sits under one top-level folder so that unzipping into a
    # Downloads directory does not spray a hundred files across it.
    top = target.stem.lower()

    # Build beside the target and swap, so an interrupted run never leaves a
    # half-written zip wearing the real name.
    staging = target.with_suffix(".zip.partial")
    made_executable = 0
    with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            arcname = f"{top}/{path.relative_to(PACKAGE_ROOT).as_posix()}"
            info = zipfile.ZipInfo.from_file(path, arcname)
            info.compress_type = zipfile.ZIP_DEFLATED

            # The low 16 bits of external_attr are the MS-DOS attributes, and
            # bit 0 is ReadOnly. `from_file` copies it off the source, and the
            # source lives on a synced drive that sets it. Extract that and
            # Windows marks the file read-only; `copytree` then puts the same
            # attribute on the directories of the installed copy; and the next
            # upgrade's `rmtree` dies on `os.rmdir` with WinError 5.
            #
            # That chain destroyed a user's install twice on 2026-08-20. It is
            # broken in three places now -- here, in `engine.clear_readonly`,
            # and by `engine.force_rmtree` -- because a delete that cannot
            # delete is not a failure anybody can be expected to diagnose.
            info.external_attr &= ~READ_ONLY_BIT

            if path.suffix in EXECUTABLE_SUFFIXES:
                info.external_attr = (EXECUTABLE_MODE << 16) | (
                    info.external_attr & 0xFFFF
                )
                made_executable += 1
            archive.writestr(info, path.read_bytes())

        # The signature, written last, over everything above.
        #
        # WHY A RELEASE IS SIGNED (2026-09-06)
        # ------------------------------------
        # `upgrade` picks up whatever `Aki-Agent-Beta-*` zip is newest in a
        # student's Downloads folder and installs it. Before this, the only
        # check was that the shape looked right -- so getting a file with
        # that name onto their machine was the whole attack. The manifest and
        # this signature are what `release_trust.verify_package` checks
        # against the public key inside the package.
        #
        # An unsigned build is still a build. It goes out saying so, and
        # refuses to install without `--allow-unsigned`, rather than the
        # release script failing at the end of a long run.
        # Paths WITHOUT the `{top}/` prefix. The zip carries one top-level
        # folder, and `unpack` hands back that folder as the package root --
        # so what `verify_package` sees is `src/aki_agent/...`, not
        # `aki-agent-beta-.../src/aki_agent/...`. Signing the prefixed names
        # would have made every file in every release look like it did not
        # match its own signature.
        manifest = release_trust.manifest_text(
            [(path.relative_to(PACKAGE_ROOT).as_posix(), path)
             for path in files])
        signature = signing_key()
        if signature:
            from aki_agent import ed25519
            archive.writestr(f"{top}/{release_trust.MANIFEST_NAME}", manifest)
            archive.writestr(
                f"{top}/{release_trust.SIGNATURE_NAME}",
                ed25519.sign(manifest.encode("utf-8"),
                             bytes.fromhex(signature)).hex() + chr(10))
    staging.replace(target)

    # Fifteen builds in one
    # day left fifteen zips here and fifteen more in the Downloads folder of
    # the machine they were installed on. None of them is worth keeping: the
    # source is in git and rollback is `cli rollback`, which uses the
    # engine.old folder on the machine, not a zip.
    #
    # Named out loud rather than done quietly -- a build step that deletes
    # files and says nothing is one somebody finds out about at the worst
    # possible moment.
    swept = sorted(one for one in RELEASE_DIR.glob("*.zip") if one != target)
    for one in swept:
        one.unlink()

    size_kb = target.stat().st_size / 1024
    print(f"Wrote {target.name}")
    if swept:
        print(f"  cleared {len(swept)} older zip(s): "
              f"{swept[0].name} … {swept[-1].name}" if len(swept) > 1
              else f"  cleared 1 older zip: {swept[0].name}")
    print(f"  {len(files)} files, {size_kb:,.0f} KB")
    print(f"  {made_executable} marked executable for macOS / Linux")
    if signing_key():
        print("  signed -- installs without --allow-unsigned")
    else:
        print(f"  NOT SIGNED: no key at {SIGNING_KEY_FILE}.")
        print("    This zip refuses to install without --allow-unsigned.")
    print(f"  in {RELEASE_DIR}")

    # State the install route in the build output itself, so whoever runs this
    # does not have to remember it or go looking for the document that has it.
    print()
    print("To install from this zip on another machine:")
    print("  1. Unzip it.")
    print(f"  2. claude plugin marketplace add <path to {top}>")
    print("  3. claude plugin install aki-agent@aki-agent")

    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=_dt.date.today().isoformat(),
        help="Date stamp for the file name (default: today, YYYY-MM-DD).",
    )
    args = parser.parse_args()
    build(args.date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
