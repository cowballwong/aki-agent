"""A published repository is an install route, so it has to be a real release.

Until 0.48.2 the only way anybody got this package was a zip, and
`make_release.py` signed the zip. Then `claude plugin marketplace add` started
cloning the repository and `upgrade` started reading that clone out of Claude
Code's plugin cache -- at which point `release_trust.verify_package()` looked
for a manifest and a signature, found neither, and said "this release is not
signed". The one-command upgrade ended at a refusal whose only way past was
`--allow-unsigned`.

The repository now carries `RELEASE.manifest` and `RELEASE.sig`, written by
`bin/sign_repo.py`. These tests exist because a manifest is a list of file
hashes: the moment somebody edits a file and forgets to re-sign, every clone
reports the release as TAMPERED WITH rather than merely unsigned -- a worse
failure, and a far more alarming one to read.

They are skipped in a working copy that carries no manifest, which is the
normal state of a development checkout.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aki_agent import release_trust

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / release_trust.MANIFEST_NAME


def _skip_if_unsigned() -> None:
    if not MANIFEST.exists():
        pytest.skip("this checkout carries no manifest, which is normal for "
                    "a development copy")


def test_the_signature_still_matches_the_files():
    """The one that catches a forgotten re-sign."""
    _skip_if_unsigned()

    verdict = release_trust.verify_package(REPO)

    assert verdict.trusted, verdict.problem


def test_the_manifest_describes_exactly_what_a_clone_gets():
    """Built by walking the working tree, checked against git.

    A file in the manifest that git does not carry makes every clone fail:
    the manifest names something that is not there. A tracked file missing
    from the manifest is a file nothing would notice being changed.
    """
    _skip_if_unsigned()

    listed = {line.split("  ", 1)[1]
              for line in MANIFEST.read_text(encoding="utf-8").splitlines()
              if line.strip()}
    done = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                          capture_output=True, check=True)
    # Minus the manifest and the signature. They are tracked, and they are
    # the two files a manifest can never list -- it would have to contain its
    # own hash. Both this test and `bin/sign_repo.py` got that wrong first
    # time and said so out loud, which is the argument for the check.
    tracked = {name for name in done.stdout.decode("utf-8").split("\0")
               if name} - release_trust.NOT_SIGNED

    assert listed - tracked == set(), "signed, but not in a clone"
    assert tracked - listed == set(), "in a clone, but not signed"


def test_the_signature_files_are_not_signing_themselves():
    """They cannot be: the manifest would have to contain its own hash."""
    _skip_if_unsigned()

    listed = MANIFEST.read_text(encoding="utf-8")

    assert release_trust.MANIFEST_NAME not in listed
    assert release_trust.SIGNATURE_NAME not in listed
