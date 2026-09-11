"""Sign the checked-out repository, so a marketplace install is a real release.

WHY THIS EXISTS (2026-09-12)
----------------------------
`make_release.py` signs a zip. Until 0.48.2 that was the only way anybody got
this package, so a zip was the only thing that needed a signature.

Then the repository became an install route: `claude plugin marketplace add`
clones it, and `upgrade` reads the clone out of Claude Code's plugin cache.
`release_trust.verify_package()` looked for `RELEASE.manifest` and
`RELEASE.sig`, found neither, and said "this release is not signed" -- so the
one-command upgrade this package advertises ended at a refusal, and the only
way past it was `--allow-unsigned`, which is exactly the habit the signing
was introduced to prevent.

So the repository carries its own manifest and signature, and this writes
them.

WHEN TO RUN IT
--------------
Last. After the version bump, after the changelog, after the tests, and
immediately before the commit. The manifest is a list of file hashes: any
edit after signing makes the release look TAMPERED WITH rather than unsigned,
which is a worse failure and a more confusing one.

`tests/test_the_repo_is_signed.py` fails when the two disagree, so a forgotten
re-sign is caught by the suite rather than by somebody's upgrade.

    python bin/sign_repo.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from aki_agent import release_trust  # noqa: E402

KEY_FILE = Path.home() / ".aki-release" / "signing-key.hex"


def tracked_files() -> set[str]:
    """What a fresh clone would contain, straight from git.

    Compared against the manifest rather than trusted: the manifest is built
    by walking the working tree, and a working tree can hold files git does
    not. One of those in the manifest means every clone fails verification,
    because the file it names is not there.
    """
    done = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                          capture_output=True, check=True)
    names = {name for name in done.stdout.decode("utf-8").split("\0") if name}
    # The manifest and its signature are tracked, and are the two files a
    # manifest can never list: it would have to contain its own hash. Caught
    # by this very check on its first run, which is the argument for having
    # written the check.
    return names - release_trust.NOT_SIGNED


def main() -> int:
    if not KEY_FILE.exists():
        print(f"No signing key at {KEY_FILE}. Nothing was written.")
        return 1

    release_trust.sign_release(REPO, KEY_FILE.read_text().strip())

    manifest = REPO / release_trust.MANIFEST_NAME
    listed = {line.split("  ", 1)[1]
              for line in manifest.read_text(encoding="utf-8").splitlines()
              if line.strip()}
    tracked = tracked_files()

    stray = sorted(listed - tracked)
    missing = sorted(tracked - listed)
    if stray or missing:
        print("The manifest does not describe a clean checkout.")
        for name in stray[:10]:
            print(f"  signed but not in git: {name}")
        for name in missing[:10]:
            print(f"  in git but not signed: {name}")
        print("\nCommit or remove those first, then sign again.")
        return 1

    verdict = release_trust.verify_package(REPO)
    if not verdict.trusted:
        print(f"Signed, but it does not verify: {verdict.problem}")
        return 1

    print(f"Signed {len(listed)} files as {verdict.signer}.")
    print("Commit RELEASE.manifest and RELEASE.sig now, and change nothing "
          "else first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
