# /// script
# requires-python = ">=3.14.2"
# dependencies = ["bleak", "bleak-retry-connector", "miauth==0.9.7"]
# ///
"""Read a Ninebot scooter's registers without Home Assistant.

Drives the same pynebot client the integration uses, so a successful run here
means the integration's protocol layer works against real hardware. Read-only:
issues no writes, no lock/unlock, no firmware commands.

Run from the repository root:

    uv run scripts/probe.py             # scan, connect, dump every register
    uv run scripts/probe.py --scan      # scan only, dump advertisements
    uv run scripts/probe.py --group mcu # one register group (ble|bms|mcu)
    uv run scripts/probe.py --debug     # verbose protocol logging

On macOS this must run from a terminal granted Bluetooth permission (System
Settings -> Privacy & Security -> Bluetooth). Otherwise the process is killed
by TCC before it can scan.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys
import time

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

# Import pynebot directly rather than through the integration package, whose
# __init__ pulls in Home Assistant. This script deliberately needs neither.
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "custom_components" / "ninebot")
)

from pynebot import (
    HARDWARE_IDS,
    MANUFACTURER_ID,
    PASSWORD_LENGTH,
    REGISTERS,
    NinebotClient,
    NinebotError,
    parse_hardware_id,
)
from pynebot.protocol import DeviceId

WEAK_SIGNAL_DBM = -85

GROUPS = {
    "mcu": DeviceId.MCU,
    "bms": DeviceId.BMS,
    "ble": DeviceId.BLE,
}


async def scan(
    timeout: float, *, list_all: bool
) -> tuple[BLEDevice | None, AdvertisementData | None]:
    """Scan for a Ninebot scooter."""
    seen: dict[str, tuple[BLEDevice, AdvertisementData]] = {}

    def found(device: BLEDevice, advertisement: AdvertisementData) -> None:
        seen[str(device.address)] = (device, advertisement)

    print(f"Scanning {timeout:.0f}s for manufacturer ID {MANUFACTURER_ID} (0x424E)...")
    async with BleakScanner(found, scanning_mode="active"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not list_all:
                for device, advertisement in seen.values():
                    if MANUFACTURER_ID in (advertisement.manufacturer_data or {}):
                        return device, advertisement
            await asyncio.sleep(0.25)

    hits = [
        (device, advertisement)
        for device, advertisement in seen.values()
        if MANUFACTURER_ID in (advertisement.manufacturer_data or {})
    ]
    print(f"\nSaw {len(seen)} BLE devices, {len(hits)} Ninebot.")
    for device, advertisement in hits:
        describe(device, advertisement)
    return hits[0] if hits else (None, None)


def describe(device: BLEDevice, advertisement: AdvertisementData) -> None:
    """Print everything an advertisement carries."""
    print(f"\n  address:   {device.address}")
    print("             (macOS reports a CoreBluetooth UUID, not the MAC)")
    print(f"  name:      {str(advertisement.local_name or device.name)!r}")
    print(f"  rssi:      {advertisement.rssi} dBm")
    print(f"  services:  {list(advertisement.service_uuids or [])}")
    for identifier, payload in (advertisement.manufacturer_data or {}).items():
        raw = bytes(payload)
        print(f"  mfr[{identifier}]: {raw.hex()}  ({len(raw)} bytes)")
        if identifier == MANUFACTURER_ID:
            hardware_id = parse_hardware_id(raw)
            model = HARDWARE_IDS.get(hardware_id or -1, "unknown model")
            print(f"             hardware ID {hardware_id} -> {model}")


async def dump(device: BLEDevice, groups: list[str], timeout: float, name: str) -> int:
    """Connect and print every register in the requested groups."""
    client = NinebotClient(device, request_timeout=timeout, name=name)
    print(f"\nConnecting to {name!r} ...")
    print("If this stalls, press the scooter's power button to accept pairing.\n")

    try:
        await client.connect()
    except NinebotError as err:
        print(f"\nConnection failed: {type(err).__name__}: {err}")
        return 1

    if client.password is not None:
        print(f"Authenticated. Session password: {client.password.hex().upper()}")
        print("Save it: passing it back with --password avoids re-pairing.\n")
    try:
        state = await client.async_poll(include_static=True)
    except NinebotError as err:
        print(f"\nPoll failed: {type(err).__name__}: {err}")
        return 1
    finally:
        await client.disconnect()

    wanted = {GROUPS[group] for group in groups}
    for register in REGISTERS:
        if register.board not in wanted:
            continue
        raw = state.raw.get(register.key)
        if raw is None:
            reason = state.failures.get(register.key, "not read")
            print(f"  {register.key:<28} 0x{register.index:02X}  <{reason}>")
            continue
        value = state.values.get(register.key)
        scale = "" if register.scale == 1.0 else f"  (raw x {register.scale})"
        print(f"  {register.key:<28} 0x{register.index:02X}  {raw:<32} {value}{scale}")

    if state.failures:
        print(f"\n{len(state.failures)} register(s) did not answer.")
    return 0


async def main() -> int:
    """Run the probe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="scan only")
    parser.add_argument("--debug", action="store_true", help="protocol logging")
    parser.add_argument(
        "--group", action="append", choices=sorted(GROUPS), help="limit register group"
    )
    parser.add_argument("--timeout", type=float, default=4.0, help="per-register wait")
    parser.add_argument("--scan-time", type=float, default=20.0, help="scan duration")
    parser.add_argument(
        "--password",
        help="hex session password recovered from the official app "
        "(see scripts/extract_password.py). Without it, pairing runs and "
        "displaces whatever the app had stored.",
    )
    parser.add_argument(
        "--name",
        help="override the name used to derive the handshake key "
        "(defaults to the advertised local name)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.DEBUG if args.debug else logging.INFO,
    )

    device, advertisement = await scan(args.scan_time, list_all=args.scan)
    if device is None or advertisement is None:
        print("No Ninebot scooter found. Is it powered on and in range?")
        return 1
    if args.scan:
        return 0

    describe(device, advertisement)
    if advertisement.rssi < WEAK_SIGNAL_DBM:
        print(
            f"\nWARNING: {advertisement.rssi} dBm is very weak."
            " A sustained connection will likely be flaky."
        )

    name = args.name or str(advertisement.local_name or device.name or "Unnamed")
    print(f"\nBLEDevice.name={device.name!r}  local_name={advertisement.local_name!r}")
    print(f"Handshake key will be derived from: {name!r}")
    password = bytes.fromhex(args.password) if args.password else None
    if password is not None and len(password) != PASSWORD_LENGTH:
        print(f"Password must be {PASSWORD_LENGTH} bytes, got {len(password)}")
        return 1

    return await dump(device, args.group or list(GROUPS), args.timeout, name, password)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
