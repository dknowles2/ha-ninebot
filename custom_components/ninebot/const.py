"""Constants for the Ninebot integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ninebot"

CONF_PASSWORD: Final = "password"
"""Config entry key holding the hex-encoded BLE session password.

This is the credential the vehicle authenticates against. Recovering the one
the official app negotiated lets both clients coexist; setting our own
displaces the app's.
"""

CONF_POLL_INTERVAL: Final = "poll_interval"

DEFAULT_POLL_INTERVAL: Final = timedelta(minutes=2)
MIN_POLL_INTERVAL: Final = 30
MAX_POLL_INTERVAL: Final = 3600

MANUFACTURER: Final = "Segway-Ninebot"
