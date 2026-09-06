"""When there is no password manager, the file that replaces it must be shut.

The fallback exists so that a student with no working keyring is not simply
stuck. It holds their email password in plain text, and it was protected by
`os.chmod(0o600)` -- which on Windows, where every student is, does not
change who can read a file. It sets the read-only attribute and stops.

So the protection was, on the platform it mattered on, nothing at all. And
the second writer -- the one that runs when a credential is deleted, and
which rewrites the file holding all the others -- did not even call that.
"""
from __future__ import annotations

import json

import pytest

from aki_agent import paths, secrets


@pytest.fixture
def no_keyring(tmp_path, monkeypatch):
    """A machine with no credential store, which is the whole scenario."""
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setattr(secrets, "_keyring_or_none", lambda: None)
    paths.ensure_app_dirs()
    return tmp_path


def _rights_on(path):
    """The access-control entries Windows reports for this file.

    WHAT TO ASSERT ON, AND THE FALSE GREEN THAT CAME FIRST (2026-09-06)
    ------------------------------------------------------------------
    The first version of these tests asserted that "Everyone", "BUILTIN\\Users"
    and "Authenticated Users" do not appear. Both tests passed -- and went on
    passing with `lock_down` gutted to `return ""`, because a file in a
    pytest temporary folder never had those groups on it in the first place.
    The assertion was true before the fix, after the fix, and would be true
    of a file with no protection whatsoever.

    What actually changes is inheritance. Untouched, a file here carries
    entries marked `(I)` -- SYSTEM, Administrators, OWNER RIGHTS -- inherited
    from the folder above. After `lock_down` there is exactly one entry, this
    account, and no `(I)` anywhere. That is a fact about the fix rather than
    about the folder it ran in.
    """
    import subprocess
    done = subprocess.run(["icacls", str(path)], capture_output=True,
                          text=True, timeout=20)
    lines = [line.strip() for line in done.stdout.splitlines()
             if ":(" in line]
    # The first line carries the path before the first entry; drop it.
    if lines:
        lines[0] = lines[0].split(str(path))[-1].strip()
    return lines


def _only_this_account(path):
    """Nobody inherits rights on this file, and one account has them.

    Said plainly about what it does not cover: an administrator can still
    take ownership and read it. This shuts out other accounts on the machine
    and anything running as them, which is who the fallback file was open to.
    """
    import os

    entries = _rights_on(path)
    assert entries, f"icacls reported nothing for {path}"
    assert not any("(I)" in entry for entry in entries), (
        f"{path} still carries inherited permissions: {entries}")
    assert len(entries) == 1, f"{path} grants more than one account: {entries}"
    assert os.environ.get("USERNAME", "") in entries[0], entries


def test_the_fallback_file_is_written_at_all(no_keyring):
    secrets.set_secret("mail_password", "hunter2")
    assert secrets.get_secret("mail_password") == "hunter2"


def test_writing_a_secret_locks_the_file(no_keyring):
    secrets.set_secret("mail_password", "hunter2")
    path = secrets._fallback_path()
    assert path.exists()

    if not paths.is_windows():
        pytest.skip("the ACL half of this is Windows")
    _only_this_account(path)


def test_deleting_a_secret_also_locks_the_file(no_keyring):
    """The path that had no permission handling at all.

    It rewrites the file holding every OTHER credential, so getting this one
    wrong undoes the other one on the next delete.
    """
    secrets.set_secret("mail_password", "hunter2")
    secrets.set_secret("telegram_token", "12345:abcdef")
    secrets.delete_secret("mail_password")

    path = secrets._fallback_path()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "telegram_token": "12345:abcdef"}

    if not paths.is_windows():
        pytest.skip("the ACL half of this is Windows")
    _only_this_account(path)


def test_lock_down_reports_rather_than_pretends(tmp_path):
    """It returns why it failed, so a caller can say so.

    A hardening step that swallows its own failure is how a file ends up
    believed to be protected and not protected.
    """
    missing = tmp_path / "not-there.json"
    assert secrets.lock_down(missing) != ""


def test_the_warning_still_names_the_file(no_keyring):
    """Locked down is not the same as safe, and the text must keep saying so:
    anybody running as this user still reads it."""
    warning = secrets.fallback_warning()
    assert warning and "plain file" in warning
