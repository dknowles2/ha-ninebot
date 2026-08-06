# Ninebot Scooter for Home Assistant

Monitor a Segway-Ninebot kick scooter over Bluetooth LE.

Built for the **Ninebot eKickScooter E2 Pro** (hardware ID 141 / `0x8D`). Other
vehicles using Encryption2 with the same `5A A5` framing should connect, but
their register maps differ and most values will be wrong or missing.

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

### Pairing, and why you probably want to recover a password first

The scooter authenticates a client with a 16-byte session password, and it
stores **one**. Whoever pairs last owns it.

That matters if you also use the Segway-Ninebot app. If Home Assistant sets its
own password, the app's stops working; the app then re-pairs and breaks Home
Assistant's, and you get a button press every time you switch between them.

Recovering the password the app already negotiated avoids this entirely — both
authenticate as the same client and neither displaces the other:

```bash
uv run scripts/extract_password.py --serial YOUR_SERIAL
```

It reads an unencrypted local iPhone backup; see the script's own help for the
requirements. Pass the result when adding the integration.

Without a recovered password, pairing runs on the first connection and needs a
press of the scooter's power button. The password is then stored in the config
entry and reused, so restarts do not ask again — until the app re-pairs.

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
│   ├── protocol.py   # frame encoding (5A A5)
│   ├── crypto.py     # Encryption2: AES-128 CTR with CBC-MAC
│   ├── registers.py  # E2 Pro register map and decoders
│   ├── client.py     # connect, 3-phase handshake, poll
│   └── models.py
├── coordinator.py    # polls on advertisement, persists the pairing key
├── sensor.py
├── binary_sensor.py
└── diagnostics.py
```

`pynebot` is vendored here rather than published, because pinning down the
register scalings will churn its API. Once that settles it moves to its own
package and the integration depends on it normally.

### Encryption

This vehicle speaks **Encryption2**: AES-128 in a custom CTR-like mode with
CBC-MAC authentication, keyed by `SHA-1(key1 ‖ key2)` where the key pair changes
at each handshake phase, and with a monotonic counter for replay protection.

It is *not* the legacy NinebotCrypto that `miauth` implements. The two are easy
to confuse: the device tables describe this model's command framing as Proto2,
and Encryption2 Gen2 uses that same `5A A5` framing. They also share the initial
key derivation, so the first handshake frame succeeds either way — and then
everything afterwards fails silently, because the legacy implementation never
enters counter mode.

[`crypto.py`](custom_components/ninebot/pynebot/crypto.py) implements it from
the published specification, using `cryptography`, which Home Assistant already
ships. There are no third-party protocol dependencies.

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

Protocol and encryption documentation by [NootNooot][docs], without which the
Encryption2 handshake would not have been implementable. Prior art in
[ownbee/ninebot-ble][ownbee] and [dnandha/miauth][miauth].

[docs]: https://nootnooot.codeberg.page/segway-ninebot-ble/
[ownbee]: https://github.com/ownbee/ninebot-ble
[miauth]: https://github.com/dnandha/miauth

## License

Apache 2.0, with no third-party protocol dependencies.
