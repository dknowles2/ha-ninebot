"""Encryption2, the cipher Segway-Ninebot vehicles use on the BLE link.

AES-128 in a custom CTR-like mode with CBC-MAC authentication. It resembles
CCM but is not interchangeable with it: the nonce layout, the associated-data
handling and the truncated tag are all specific to this protocol.

Implemented from the protocol documentation at
https://nootnooot.codeberg.page/segway-ninebot-ble/encryption/
and verified against frames captured from a real scooter (see the tests).

Two modes exist:

Non-SN (counter 0)
    Used before authentication. Every block is XORed with the *same* AES-ECB
    output, so identical plaintext blocks produce identical ciphertext. Fine
    for a handshake that carries no secrets, useless for anything else.

SN (counter > 0)
    Used once authentication starts. Proper CTR keystream plus a CBC-MAC tag,
    with a monotonically increasing counter for replay protection.
"""

from __future__ import annotations

import hashlib
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .exceptions import NinebotProtocolError

BLOCK_SIZE = 16
KEY_SIZE = 16
TAG_SIZE = 4
NONCE_SIZE = 13
HEADER_SIZE = 3
"""Preamble and length byte, sent in the clear."""

TAIL_SIZE = 6
"""Tag or checksum plus counter, appended to every frame."""

FW_DATA = bytes.fromhex("97CFB802844143DE56002B3B34780A5D")
"""Fixed protocol constant from the vendor's crypto library.

Not a secret: it is identical across every device and app version, and is not
derived from anything per-device. Gen2 vehicles use it both as the second half
of the PRE_COMM key material and as the ECB input that generates the non-SN
keystream. Gen3 vehicles use zeros in both places.
"""

GEN2 = 2
"""Vehicle generation that keys PRE_COMM with fw_data rather than zeros."""

CTR_BLOCK_PREFIX = 0x01
MAC_BLOCK_PREFIX = 0x59


class DecryptionError(NinebotProtocolError):
    """Raised when a frame fails authentication or replay checks."""


def derive_key(key1: bytes, key2: bytes | None) -> bytes:
    """Derive the AES-128 key from a key pair.

    Each half is zero-padded or truncated to 16 bytes, concatenated, and
    hashed; the first 16 bytes of the digest are the key.
    """
    first = (key1 + bytes(BLOCK_SIZE))[:BLOCK_SIZE]
    second = (key2 + bytes(BLOCK_SIZE))[:BLOCK_SIZE] if key2 else bytes(BLOCK_SIZE)
    return hashlib.sha1(first + second).digest()[:KEY_SIZE]


def build_nonce(counter: int, auth: bytes) -> bytes:
    """Build the 13-byte nonce from a counter and the auth parameter."""
    return struct.pack(">I", counter) + (auth + bytes(8))[:8] + b"\x00"


def _xor(left: bytes, right: bytes) -> bytes:
    """XOR two byte strings, truncating to the shorter one."""
    return bytes(a ^ b for a, b in zip(left, right, strict=False))


class Encryption2:
    """Cipher state for one BLE session.

    The key and auth parameter change as the handshake advances, so this holds
    mutable state and is not safe to share between connections.
    """

    def __init__(self, *, generation: int = GEN2) -> None:
        """Initialize for a Gen2 (default) or Gen3 vehicle."""
        self._ecb_input = FW_DATA if generation == GEN2 else bytes(BLOCK_SIZE)
        self._key = derive_key(b"", None)
        self._auth = bytes(BLOCK_SIZE)
        self._counter = 0
        self._peer_counter = 0

    @property
    def counter(self) -> int:
        """Return the counter that will be used by the next frame we send."""
        return self._counter

    @property
    def sn_mode(self) -> bool:
        """Return True once the authenticated counter mode is active."""
        return self._counter > 0

    def set_key(self, key1: bytes, key2: bytes | None = None) -> None:
        """Set the key pair for the current handshake phase."""
        self._key = derive_key(key1, key2)

    def set_auth(self, auth: bytes) -> None:
        """Store the auth parameter the vehicle issued during PRE_COMM."""
        self._auth = auth

    def start_sn(self) -> None:
        """Enter counter mode.

        The counter becomes 1, so the first frame sent afterwards carries 2 —
        which is what the vehicle expects, whether or not SET_PWD was skipped.
        """
        self._counter = 1
        self._peer_counter = 0

    def reset_sn(self) -> None:
        """Return to non-counter mode, as used before PRE_COMM."""
        self._counter = 0
        self._peer_counter = 0

    def _ecb(self, block: bytes) -> bytes:
        """Encrypt a single block with AES-128-ECB."""
        encryptor = Cipher(algorithms.AES(self._key), modes.ECB()).encryptor()
        return encryptor.update(block) + encryptor.finalize()

    def _ctr_block(self, nonce: bytes, index: int) -> bytes:
        """Build counter block A_i, whose encryption is the keystream."""
        return bytes([CTR_BLOCK_PREFIX]) + nonce + bytes([0x00, index])

    def _keystream_xor(self, payload: bytes, nonce: bytes) -> bytes:
        """Apply the CTR keystream to a payload. Symmetric, so also decrypts."""
        out = bytearray()
        for index, offset in enumerate(range(0, len(payload), BLOCK_SIZE), start=1):
            chunk = payload[offset : offset + BLOCK_SIZE]
            out += _xor(chunk, self._ecb(self._ctr_block(nonce, index)))
        return bytes(out)

    def _cbc_mac(self, plaintext: bytes, nonce: bytes) -> bytes:
        """Compute the 4-byte CBC-MAC tag over a whole plaintext frame."""
        payload = plaintext[HEADER_SIZE:]
        state = self._ecb(
            bytes([MAC_BLOCK_PREFIX]) + nonce + bytes([0x00, len(payload)])
        )
        # The 3-byte header is authenticated as associated data.
        state = self._ecb(
            _xor(state, plaintext[:HEADER_SIZE] + bytes(BLOCK_SIZE - HEADER_SIZE))
        )
        for offset in range(0, len(payload), BLOCK_SIZE):
            chunk = payload[offset : offset + BLOCK_SIZE]
            padded = chunk + bytes(BLOCK_SIZE - len(chunk))
            state = self._ecb(_xor(state, padded))
        return state[:TAG_SIZE]

    def _static_keystream_xor(self, payload: bytes) -> bytes:
        """Apply the non-SN keystream, which repeats for every block."""
        keystream = self._ecb(self._ecb_input)
        out = bytearray()
        for offset in range(0, len(payload), BLOCK_SIZE):
            out += _xor(payload[offset : offset + BLOCK_SIZE], keystream)
        return bytes(out)

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt a framed packet. Returns six bytes more than it received."""
        if len(plaintext) < HEADER_SIZE:
            raise DecryptionError(f"Frame too short to encrypt: {len(plaintext)}")

        header, payload = plaintext[:HEADER_SIZE], plaintext[HEADER_SIZE:]

        if not self.sn_mode:
            checksum = (~sum(payload)) & 0xFFFF
            return (
                header
                + self._static_keystream_xor(payload)
                + bytes([0x00, 0x00, checksum & 0xFF, checksum >> 8, 0x00, 0x00])
            )

        self._counter = (self._counter + 1) & 0xFFFF
        nonce = build_nonce(self._counter, self._auth)
        tag = self._cbc_mac(plaintext, nonce)
        encrypted_tag = _xor(tag, self._ecb(self._ctr_block(nonce, 0))[:TAG_SIZE])
        return (
            header
            + self._keystream_xor(payload, nonce)
            + encrypted_tag
            + struct.pack(">H", self._counter)
        )

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt and authenticate a framed packet.

        Raises:
            DecryptionError: the frame is truncated, replays an old counter, or
                fails its authentication tag.
        """
        if len(ciphertext) < HEADER_SIZE + TAIL_SIZE:
            raise DecryptionError(f"Frame too short to decrypt: {len(ciphertext)}")

        header = ciphertext[:HEADER_SIZE]
        body = ciphertext[HEADER_SIZE:-TAIL_SIZE]
        tail = ciphertext[-TAIL_SIZE:]
        counter = struct.unpack(">H", tail[4:6])[0]

        if counter == 0:
            payload = self._static_keystream_xor(body)
            expected = (~sum(payload)) & 0xFFFF
            received = tail[2] | (tail[3] << 8)
            if expected != received:
                raise DecryptionError(
                    f"Checksum mismatch: computed {expected:04X}, got {received:04X}"
                )
            return header + payload

        if counter <= self._peer_counter:
            raise DecryptionError(
                f"Replayed counter {counter}, already saw {self._peer_counter}"
            )

        nonce = build_nonce(counter, self._auth)
        payload = self._keystream_xor(body, nonce)
        plaintext = header + payload

        received_tag = _xor(
            tail[:TAG_SIZE], self._ecb(self._ctr_block(nonce, 0))[:TAG_SIZE]
        )
        if received_tag != self._cbc_mac(plaintext, nonce):
            raise DecryptionError("Authentication tag mismatch")

        self._peer_counter = counter
        return plaintext
