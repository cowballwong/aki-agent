"""Ed25519 signatures, in the standard library and nothing else.

WHY A SIGNATURE CHECK LIVES HERE AND NOT IN A DEPENDENCY
--------------------------------------------------------
This exists for one job: proving that a release zip about to be installed is
one the maintainer built. That check is worth having only if it is *always there*. A
student whose `pip install cryptography` fails -- no wheel for their Python,
a locked-down machine, an offline install from a USB stick -- would otherwise
end up with the check quietly absent, which is the worst of both worlds: the
software says it verifies releases and does not.

So this is the RFC 8032 reference implementation, on `hashlib` alone. It is
slow -- roughly a tenth of a second per verification -- and that is fine,
because it runs once, during an upgrade, next to a zip extraction.

WHAT IT IS NOT FOR
------------------
Nothing else. It is not constant-time, it has no protection against timing or
side-channel attacks, and it must never be used for anything an attacker can
ask to sign repeatedly. Verification of a file already on the disk, once, is
the whole remit. Signing is here only so the release script can use it on
The maintainer's own machine.

The implementation is deliberately the published reference rather than a
clever one: it is the version most eyes have read, and there is no
performance here worth trading legibility for. `tests/test_ed25519.py` checks
it against the RFC's own vectors and, where the `cryptography` package
happens to be installed, against that too.
"""
from __future__ import annotations

import hashlib

_BITS = 256
_Q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493  # not-a-secret: published value (RFC 8032)

SIGNATURE_BYTES = 64
KEY_BYTES = 32


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _inverse(x: int) -> int:
    return pow(x, _Q - 2, _Q)


_D = -121665 * _inverse(121666) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)


def _recover_x(y: int) -> int:
    square = (y * y - 1) * _inverse(_D * y * y + 1)
    x = pow(square, (_Q + 3) // 8, _Q)
    if (x * x - square) % _Q != 0:
        x = (x * _I) % _Q
    if x % 2 != 0:
        x = _Q - x
    return x


_BASE_Y = 4 * _inverse(5)
_BASE = (_recover_x(_BASE_Y) % _Q, _BASE_Y % _Q)


def _add(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p
    x2, y2 = q
    common = _D * x1 * x2 * y1 * y2
    x3 = (x1 * y2 + x2 * y1) * _inverse(1 + common)
    y3 = (y1 * y2 + x1 * x2) * _inverse(1 - common)
    return (x3 % _Q, y3 % _Q)


def _multiply(point: tuple[int, int], times: int) -> tuple[int, int]:
    """Double-and-add, written as a loop.

    The reference publishes this as recursion, which on a 256-bit scalar goes
    256 frames deep. That is under CPython's default limit, but only just, and
    it would be a silly place to meet a RecursionError -- in the middle of an
    upgrade, on somebody else's machine, with a stack limit somebody else set.
    """
    result = (0, 1)                       # the identity, and _add knows it
    while times > 0:
        if times & 1:
            result = _add(result, point)
        point = _add(point, point)
        times >>= 1
    return result


def _bit(data: bytes, index: int) -> int:
    return (data[index // 8] >> (index % 8)) & 1


def _secret_scalar(digest: bytes) -> int:
    """The clamped scalar an Ed25519 secret key expands into."""
    return 2 ** (_BITS - 2) + sum(
        2 ** i * _bit(digest, i) for i in range(3, _BITS - 2))


def _encode_point(point: tuple[int, int]) -> bytes:
    x, y = point
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _on_curve(point: tuple[int, int]) -> bool:
    x, y = point
    return (-x * x + y * y - 1 - _D * x * x * y * y) % _Q == 0


def _decode_point(data: bytes) -> tuple[int, int]:
    y = int.from_bytes(data, "little") & ((1 << 255) - 1)
    x = _recover_x(y)
    if (x & 1) != ((data[31] >> 7) & 1):
        x = _Q - x
    point = (x, y)
    if not _on_curve(point):
        raise ValueError("not a point on the curve")
    return point


def _hash_to_int(data: bytes) -> int:
    return int.from_bytes(_sha512(data), "little")


def public_key(secret: bytes) -> bytes:
    """The 32-byte public key for a 32-byte secret key."""
    if len(secret) != KEY_BYTES:
        raise ValueError(f"a secret key is {KEY_BYTES} bytes")
    scalar = _secret_scalar(_sha512(secret))
    return _encode_point(_multiply(_BASE, scalar))


def sign(message: bytes, secret: bytes) -> bytes:
    """Sign. Only ever called on the machine that holds the release key."""
    if len(secret) != KEY_BYTES:
        raise ValueError(f"a secret key is {KEY_BYTES} bytes")
    digest = _sha512(secret)
    scalar = _secret_scalar(digest)
    nonce = _hash_to_int(digest[32:64] + message) % _L
    R = _multiply(_BASE, nonce)
    encoded_R = _encode_point(R)
    challenge = _hash_to_int(encoded_R + public_key(secret) + message)
    S = (nonce + challenge * scalar) % _L
    return encoded_R + S.to_bytes(32, "little")


def verify(signature: bytes, message: bytes, key: bytes) -> bool:
    """Is this signature over this message, by the holder of this key?

    Returns False rather than raising for every kind of malformed input: a
    caller asking "is this release genuine" wants one answer, and a signature
    that is the wrong length is not a different answer from a signature that
    is wrong.
    """
    if len(signature) != SIGNATURE_BYTES or len(key) != KEY_BYTES:
        return False
    try:
        R = _decode_point(signature[:32])
        A = _decode_point(key)
    except (ValueError, IndexError):
        return False
    S = int.from_bytes(signature[32:], "little")
    if S >= _L:
        # Rejecting a non-canonical S is not pedantry: without it a valid
        # signature can be rewritten into a different byte string that also
        # verifies, and "the signature that was checked" stops being a single
        # identifiable thing.
        return False
    challenge = _hash_to_int(signature[:32] + key + message)
    return _multiply(_BASE, S) == _add(R, _multiply(A, challenge))
