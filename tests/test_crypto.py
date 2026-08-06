"""Tests for the Encryption2 implementation.

The captured vectors come from a real eKickScooter E2 Pro (hardware ID 141),
recorded during a PRE_COMM exchange. They are the only ground truth available,
so they are asserted byte for byte.
"""

from __future__ import annotations

import pytest

from custom_components.ninebot.pynebot.crypto import (
    FW_DATA,
    DecryptionError,
    Encryption2,
    build_nonce,
    derive_key,
)

DEVICE_NAME = b"E2 Pro 0216"

# Captured PRE_COMM request, non-SN mode: 5A A5 | LEN | src dst cmd idx
CAPTURED_PRE_COMM_PLAINTEXT = bytes.fromhex("5AA5003D215B00")
CAPTURED_PRE_COMM_CIPHERTEXT = bytes.fromhex("5AA5006C62AFC9000046FF0000")

# Captured PRE_COMM response, carrying a zero auth parameter and the serial.
CAPTURED_SERIAL = b"N2ABA2415P0216"


def _pre_comm() -> Encryption2:
    """Return a cipher keyed for the PRE_COMM phase of a Gen2 vehicle."""
    crypto = Encryption2(generation=2)
    crypto.set_key(DEVICE_NAME, FW_DATA)
    return crypto


def test_key_derivation_pads_and_hashes() -> None:
    key = derive_key(DEVICE_NAME, FW_DATA)

    assert len(key) == 16
    # A short key1 is zero-padded, so passing the padding explicitly matches.
    assert key == derive_key(DEVICE_NAME + bytes(5), FW_DATA)


def test_missing_key2_is_treated_as_zeros() -> None:
    assert derive_key(DEVICE_NAME, None) == derive_key(DEVICE_NAME, bytes(16))


def test_nonce_layout() -> None:
    nonce = build_nonce(2, bytes(range(16)))

    assert len(nonce) == 13
    assert nonce == b"\x00\x00\x00\x02" + bytes(range(8)) + b"\x00"


def test_encrypts_the_captured_pre_comm_frame() -> None:
    """The whole non-SN path, checked against bytes a real scooter accepted."""
    assert _pre_comm().encrypt(CAPTURED_PRE_COMM_PLAINTEXT) == (
        CAPTURED_PRE_COMM_CIPHERTEXT
    )


def test_decrypts_what_it_encrypts_in_non_sn_mode() -> None:
    crypto = _pre_comm()

    assert crypto.decrypt(CAPTURED_PRE_COMM_CIPHERTEXT) == (CAPTURED_PRE_COMM_PLAINTEXT)


def test_gen3_uses_zeros_where_gen2_uses_fw_data() -> None:
    gen2 = Encryption2(generation=2)
    gen2.set_key(DEVICE_NAME, FW_DATA)
    gen3 = Encryption2(generation=3)
    gen3.set_key(DEVICE_NAME, FW_DATA)

    assert gen2.encrypt(CAPTURED_PRE_COMM_PLAINTEXT) != gen3.encrypt(
        CAPTURED_PRE_COMM_PLAINTEXT
    )


def test_start_sn_makes_the_first_frame_use_counter_two() -> None:
    """The vehicle expects 2 first, whether or not SET_PWD was performed."""
    crypto = _pre_comm()
    crypto.start_sn()

    frame = crypto.encrypt(CAPTURED_PRE_COMM_PLAINTEXT)

    assert frame[-2:] == b"\x00\x02"
    assert crypto.counter == 2


def test_sn_mode_round_trip() -> None:
    plaintext = bytes.fromhex("5AA50E3D205B00") + bytes(range(14))

    sender = _pre_comm()
    sender.set_auth(bytes(range(16)))
    sender.start_sn()
    receiver = _pre_comm()
    receiver.set_auth(bytes(range(16)))
    receiver.start_sn()

    assert receiver.decrypt(sender.encrypt(plaintext)) == plaintext


def test_sn_frames_are_six_bytes_longer_than_their_plaintext() -> None:
    plaintext = bytes.fromhex("5AA5103D205B00") + bytes(16)
    crypto = _pre_comm()
    crypto.start_sn()

    assert len(crypto.encrypt(plaintext)) == len(plaintext) + 6


def test_counter_increments_per_frame() -> None:
    crypto = _pre_comm()
    crypto.start_sn()

    counters = [crypto.encrypt(CAPTURED_PRE_COMM_PLAINTEXT)[-2:] for _ in range(3)]

    assert counters == [b"\x00\x02", b"\x00\x03", b"\x00\x04"]


def test_replayed_counter_is_rejected() -> None:
    sender = _pre_comm()
    sender.set_auth(bytes(range(16)))
    sender.start_sn()
    receiver = _pre_comm()
    receiver.set_auth(bytes(range(16)))
    receiver.start_sn()

    frame = sender.encrypt(CAPTURED_PRE_COMM_PLAINTEXT)
    receiver.decrypt(frame)

    with pytest.raises(DecryptionError, match="Replayed counter"):
        receiver.decrypt(frame)


def test_tampered_payload_fails_authentication() -> None:
    sender = _pre_comm()
    sender.set_auth(bytes(range(16)))
    sender.start_sn()
    receiver = _pre_comm()
    receiver.set_auth(bytes(range(16)))
    receiver.start_sn()

    frame = bytearray(
        sender.encrypt(bytes.fromhex("5AA5043D205B00") + b"\x01\x02\x03\x04")
    )
    frame[4] ^= 0xFF

    with pytest.raises(DecryptionError, match="Authentication tag"):
        receiver.decrypt(bytes(frame))


def test_wrong_key_fails_authentication() -> None:
    sender = _pre_comm()
    sender.set_auth(bytes(range(16)))
    sender.start_sn()

    receiver = Encryption2(generation=2)
    receiver.set_key(b"Some Other Scooter", FW_DATA)
    receiver.set_auth(bytes(range(16)))
    receiver.start_sn()

    with pytest.raises(DecryptionError):
        receiver.decrypt(sender.encrypt(CAPTURED_PRE_COMM_PLAINTEXT))


def test_corrupt_checksum_is_rejected_in_non_sn_mode() -> None:
    frame = bytearray(CAPTURED_PRE_COMM_CIPHERTEXT)
    frame[-4] ^= 0xFF

    with pytest.raises(DecryptionError, match="Checksum mismatch"):
        _pre_comm().decrypt(bytes(frame))


@pytest.mark.parametrize("raw", [b"", b"\x5a", b"\x5a\xa5\x00\x00\x00"])
def test_truncated_frames_are_rejected(raw: bytes) -> None:
    with pytest.raises(DecryptionError, match="too short"):
        _pre_comm().decrypt(raw)


def test_auth_phase_keys_on_the_session_password() -> None:
    """AUTH re-keys to SHA-1(password, auth), not the device name."""
    password = bytes(range(16, 32))
    auth = bytes(range(16))

    crypto = _pre_comm()
    before = crypto.encrypt(CAPTURED_PRE_COMM_PLAINTEXT)
    crypto.set_key(password, auth)
    after = crypto.encrypt(CAPTURED_PRE_COMM_PLAINTEXT)

    assert before != after


def test_serial_from_the_captured_response_is_ascii() -> None:
    assert CAPTURED_SERIAL.decode("ascii").startswith("N2A")
