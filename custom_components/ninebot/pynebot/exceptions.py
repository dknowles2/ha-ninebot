"""Exceptions raised by pynebot."""

from __future__ import annotations


class NinebotError(Exception):
    """Base class for all pynebot errors."""


class NinebotConnectionError(NinebotError):
    """Raised when the BLE connection could not be established or was lost."""


class NinebotTimeoutError(NinebotError):
    """Raised when the scooter did not answer a request in time."""


class NinebotAuthError(NinebotError):
    """Raised when the encrypted handshake failed."""


class NinebotPairingRequiredError(NinebotAuthError):
    """Raised when the scooter needs the user to confirm pairing.

    The user must press the scooter's power button while the client is
    attempting to pair. Retrying the connection after that succeeds.
    """


class NinebotProtocolError(NinebotError):
    """Raised when a malformed frame was received."""
