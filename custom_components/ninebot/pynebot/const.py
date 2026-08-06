"""Constants for the Ninebot BLE protocol."""

from __future__ import annotations

from typing import Final

# Nordic UART Service. Every Ninebot vehicle speaking Proto2 exposes this.
NUS_SERVICE_UUID: Final = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_CHAR_UUID: Final = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX_CHAR_UUID: Final = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# Company identifier used by Segway-Ninebot in BLE advertisements.
MANUFACTURER_ID: Final = 16974  # 0x424E, "BN"

# Preamble for every Proto2 frame. Newer Encryption2 vehicles use 5A B5 and are
# NOT supported by this client.
PROTO2_MAGIC: Final = b"\x5a\xa5"

# The scooter's hardware ID is broadcast as the first byte of the manufacturer
# specific advertisement data. Only models verified to speak Proto2 are listed.
HARDWARE_IDS: Final[dict[int, str]] = {
    125: "KickScooter E2/E2 Plus",
    141: "eKickScooter E2 Pro",
}

DEFAULT_HARDWARE_ID: Final = 141

# Length of the session password exchanged during pairing.
PASSWORD_LENGTH: Final = 16

# Length of the vehicle serial number returned by PRE_COMM.
SERIAL_LENGTH: Final = 14

# Conservative default timeouts, in seconds.
CONNECT_TIMEOUT: Final = 20.0
REQUEST_TIMEOUT: Final = 5.0
PAIRING_TIMEOUT: Final = 30.0
