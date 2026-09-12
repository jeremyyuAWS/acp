"""Validate cached source bytes against recognized recorded provider checksums.

QuickXorHash follows Microsoft's official sample:
https://learn.microsoft.com/en-us/onedrive/developer/code-snippets/quickxorhash
It is a provider integrity checksum, not cryptographic proof; callers must retain
owner, source-version and cryptographic corrected-artifact guards separately.
"""
import base64
import binascii
import hashlib
import hmac
import re
from functools import reduce
from operator import xor


def quickxor_digest(data: bytes) -> bytes:
    """20-byte QuickXor, circular shifts of 11 bits, then little-endian length XOR."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError('source must be binary bytes')
    data = bytes(data)
    if len(data) >= 1 << 63:
        raise ValueError('source exceeds signed 64-bit length')
    state = 0
    mask = (1 << 160) - 1
    # Every 160 input bytes returns to the same rotation. Fold those positions
    # before rotating, reducing Python-level work without changing the algorithm.
    for index in range(min(len(data), 160)):
        byte = reduce(xor, data[index::160], 0)
        shift = index * 11 % 160
        rotated = byte << shift
        state ^= (rotated & mask) | (rotated >> 160)
    result = bytearray(state.to_bytes(20, 'little'))
    for index, byte in enumerate(len(data).to_bytes(8, 'little')):
        result[12 + index] ^= byte
    return bytes(result)


def checksum_algorithm(checksum):
    """Recognize strict hex MD5/SHA1/SHA256 or canonical 20-byte Base64 QuickXor."""
    if not isinstance(checksum, str):
        return None
    algorithm = {32: 'md5', 40: 'sha1', 64: 'sha256'}.get(len(checksum))
    if algorithm and re.fullmatch(r'[0-9a-fA-F]+', checksum):
        return algorithm
    if not re.fullmatch(r'[A-Za-z0-9+/]{27}=', checksum):
        return None
    try:
        digest = base64.b64decode(checksum, validate=True)
    except (ValueError, binascii.Error):
        return None
    if len(digest) == 20 and base64.b64encode(digest).decode('ascii') == checksum:
        return 'quickxor'
    return None


def matches_source_checksum(data, checksum):
    """Fail closed for opaque/missing/malformed hashes; never infer from new bytes."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        return False
    data = bytes(data)
    algorithm = checksum_algorithm(checksum)
    if algorithm is None:
        return False
    if algorithm == 'quickxor':
        expected = base64.b64decode(checksum, validate=True)
        actual = quickxor_digest(data)
    else:
        expected = bytes.fromhex(checksum)
        actual = hashlib.new(algorithm, data).digest()
    return hmac.compare_digest(actual, expected)
