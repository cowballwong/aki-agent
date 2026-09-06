"""The signature maths, checked against something that is not itself.

A crypto implementation that only ever verifies its own signatures will pass
its own tests while being systematically wrong -- sign and verify agree with
each other because they share the mistake. So the checks here are all against
an outside authority: the RFC's published vectors, and the `cryptography`
package where the developer machine happens to have it.
"""
from __future__ import annotations

import os

import pytest

from aki_agent import ed25519

# RFC 8032, section 7.1, TEST 1. The most-published Ed25519 vector there is.
#
# Yes, the first one is a private key, and it is printed in an IETF standard
# that has been read by everybody who has ever implemented this. It secures
# nothing. The marker is how the credential scanner is told so -- and the
# scanner flagging it first is the scanner working.
RFC_SECRET = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"  # not-a-secret: published value
RFC_PUBLIC = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"  # not-a-secret: published value


def test_the_rfc_vector_gives_the_rfc_public_key():
    got = ed25519.public_key(bytes.fromhex(RFC_SECRET))
    assert got.hex() == RFC_PUBLIC


def test_a_signature_verifies():
    secret = os.urandom(32)
    public = ed25519.public_key(secret)
    signature = ed25519.sign(b"a release", secret)
    assert ed25519.verify(signature, b"a release", public)


@pytest.mark.parametrize("what", [
    "a different message",
    "a flipped byte in R",
    "a flipped byte in S",
    "somebody else's key",
    "an empty signature",
    "a signature with a byte glued on",
    "a signature with S above the group order",
])
def test_forgeries_are_refused(what):
    """Each of these is a way a tampered release could try to get through."""
    secret = os.urandom(32)
    public = ed25519.public_key(secret)
    message = b"install this release"
    signature = ed25519.sign(message, secret)

    if what == "a different message":
        assert not ed25519.verify(signature, b"install something else", public)
    elif what == "a flipped byte in R":
        broken = bytes([signature[0] ^ 1]) + signature[1:]
        assert not ed25519.verify(broken, message, public)
    elif what == "a flipped byte in S":
        broken = signature[:-1] + bytes([signature[-1] ^ 1])
        assert not ed25519.verify(broken, message, public)
    elif what == "somebody else's key":
        theirs = ed25519.public_key(os.urandom(32))
        assert not ed25519.verify(signature, message, theirs)
    elif what == "an empty signature":
        assert not ed25519.verify(b"", message, public)
    elif what == "a signature with a byte glued on":
        assert not ed25519.verify(signature + b"x", message, public)
    elif what == "a signature with S above the group order":
        # Malleability: without the canonical-S check, a second byte string
        # verifies for the same message, and "the signature we checked" stops
        # being one identifiable thing.
        order = 2 ** 252 + 27742317777372353535851937790883648493  # not-a-secret: published value
        S = int.from_bytes(signature[32:], "little")
        slid = signature[:32] + (S + order).to_bytes(32, "little")
        assert not ed25519.verify(slid, message, public)


def test_it_agrees_with_a_real_implementation():
    """Byte-for-byte against `cryptography`, on the machine that has it.

    Skipped rather than vendored: this is a developer's cross-check, and
    making it a hard dependency would defeat the reason this module exists.
    """
    ref = pytest.importorskip(
        "cryptography.hazmat.primitives.asymmetric.ed25519")
    from cryptography.hazmat.primitives import serialization

    for length in (0, 1, 31, 32, 33, 200):
        secret = os.urandom(32)
        message = os.urandom(length)
        theirs = ref.Ed25519PrivateKey.from_private_bytes(secret)
        their_public = theirs.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)

        assert ed25519.public_key(secret) == their_public
        assert ed25519.sign(message, secret) == theirs.sign(message)
        assert ed25519.verify(theirs.sign(message), message, their_public)
