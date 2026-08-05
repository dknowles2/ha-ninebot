# Ninebot Scooter for Home Assistant

Monitor a Segway-Ninebot kick scooter over Bluetooth LE.

Built for the **Ninebot eKickScooter E2 Pro** (hardware ID 141 / `0x8D`). Other
scooters speaking the same Proto2 protocol will connect, but their register maps
differ and most values will be wrong or missing.

> **Status: unverified against hardware.** The register indices come from
> community protocol documentation, but the *units* those registers report in do
> not. Every scaling factor is currently a best guess marked `ASSUMED` in
> [`registers.py`](custom_components/ninebot/pynebot/registers.py). Expect some
> sensors to be off by a factor of ten until they are checked against the
> scooter's own display. See [Verifying the scalings](#verifying-the-scalings).

## What it reports

**Ride** — speed, total distance, trip distance, remaining range, body
temperature, gear mode, error and warning codes.

**Battery** — charge level (from the BMS and from the controller), voltage,
current, two temperature probes, per-cell voltages with min/max/delta, remaining
and design capacity, charge cycles, deep-discharge count.

**State** — lock status, problem indicator, traction control, light mode.

Values that never change (serial numbers, firmware versions, CPU ID) become
device attributes rather than entities.

## Requirements

- Home Assistant 2026.8 or later
- A Bluetooth adapter or [ESPHome Bluetooth proxy][proxy] within range of the
  scooter. The proxy must support **active connections** — passive-only proxies
  cannot poll, since none of this data is broadcast in advertisements.
- The scooter powered on. It stops advertising when asleep.

[proxy]: https://esphome.io/components/bluetooth_proxy.html

## Installation

### HACS

Add `https://github.com/dknowles2/ha-ninebot` as a custom repository of type
*Integration*, install, and restart Home Assistant.

### Manual

Copy `custom_components/ninebot` into your `<config>/custom_components/`
directory and restart Home Assistant.

## Setup

The scooter is discovered automatically once it advertises. Otherwise add it from
**Settings → Devices & services → Add integration → Ninebot Scooter**.

**The first connection needs a button press.** When Home Assistant first pairs,
press the scooter's power button to accept. The pairing key is then stored in the
config entry and reused, so restarts and reconnects do not ask again.

If pairing keeps failing, the scooter has probably forgotten the key (a factory
reset, or pairing cleared in the Segway-Ninebot app). The integration detects
this and re-pairs from scratch, which needs one more button press.

## Options

**Poll interval** — how often to connect and read, default 2 minutes. Each poll
wakes the scooter's Bluetooth module, so longer is gentler. Changes apply on the
next advertisement without reloading.

## Verifying the scalings

This is the part that needs real hardware, and where help is most useful.

1. Download diagnostics: **Settings → Devices & services → Ninebot Scooter →
   ⋮ → Download diagnostics**.
2. Each register appears with its `raw` payload, the `scale` applied, and the
   resulting `value`.
3. Compare against the scooter's display or the official app.
4. When a value is wrong, the raw bytes tell you the right factor. Open an issue
   with the raw payload and the true reading, or send a PR changing that
   register's `scale` and moving its comment from `ASSUMED` to `VERIFIED`.

There is also a standalone probe script for reading registers without Home
Assistant, useful for a quick check from a laptop in range of the scooter:

```bash
uv run scripts/probe.py
```

It prints every register's raw bytes next to the decoded value, and needs no
Home Assistant install. On macOS it must be run from a terminal that has been
granted Bluetooth permission.

## Architecture

```
custom_components/ninebot/
├── pynebot/          # protocol client, no Home Assistant imports
│   ├── protocol.py   # Proto2 framing (5A A5)
│   ├── registers.py  # E2 Pro register map and decoders
│   ├── client.py     # connect, handshake, poll
│   └── models.py
├── coordinator.py    # polls on advertisement, persists the pairing key
├── sensor.py
├── binary_sensor.py
└── diagnostics.py
```

`pynebot` is vendored here rather than published, because pinning down the
register scalings will churn its API. Once that settles it moves to its own
package and the integration depends on it normally.

Encryption is handled by [`miauth`][miauth], a Python port of
[NinebotCrypto][crypto]. That is the one piece deliberately not reimplemented:
it is the reference implementation the whole ecosystem uses, and rewriting it
would only introduce bugs.

[miauth]: https://github.com/dnandha/miauth
[crypto]: https://github.com/scooterhacking/NinebotCrypto

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run mypy custom_components/ninebot
```

Tests run against an in-memory scooter (`tests/fake_scooter.py`) that speaks the
real framing, so protocol changes are covered without hardware.

## Credits

Protocol documentation by [NootNooot][docs], crypto by
[scooterhacking][crypto] and [Daljeet Nandha][miauth], and prior art in
[ownbee/ninebot-ble][ownbee].

[docs]: https://nootnooot.codeberg.page/segway-ninebot-ble/
[ownbee]: https://github.com/ownbee/ninebot-ble

## License

Apache 2.0. Note that `miauth`, a runtime dependency, is AGPL-3.0.
