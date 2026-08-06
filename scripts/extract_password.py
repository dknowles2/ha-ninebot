# /// script
# requires-python = ">=3.14.2"
# dependencies = []
# ///
"""Recover the Segway-Ninebot session password from a local iPhone backup.

The official app negotiates a 16-byte session password with the scooter and
stores it. Recovering it lets this integration authenticate as an already
paired client, instead of running SET_PWD and displacing the app's pairing.

This reads your own backup of your own phone, for your own vehicle. Nothing
leaves the machine.

Run from a terminal with Full Disk Access (System Settings -> Privacy &
Security -> Full Disk Access), otherwise the backup directory is unreadable:

    uv run scripts/extract_password.py
    uv run scripts/extract_password.py --serial N2ABA2415P0216

The backup must be UNENCRYPTED. In Finder, select the iPhone, choose "Back up
all of the data on your iPhone to this Mac", and leave "Encrypt local backup"
unchecked.
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path
import plistlib
import sqlite3
import subprocess
import sys

PASSWORD_LENGTH = 16

BACKUP_ROOT = Path.home() / "Library/Application Support/MobileSync/Backup"

# The app has shipped under more than one bundle identifier over the years.
DOMAIN_HINTS = ("ninebot", "segway")


class NeedsFullDiskAccessError(Exception):
    """Raised when macOS blocks reading the backup directory."""


def find_backups() -> list[Path]:
    """Return every backup directory containing a manifest, newest first.

    Raises:
        NeedsFullDiskAccess: the directory exists but macOS denied the read.
    """
    if not BACKUP_ROOT.is_dir():
        return []
    try:
        entries = list(BACKUP_ROOT.iterdir())
    except PermissionError as err:
        # The directory is visible but unreadable, which is TCC denying the
        # terminal rather than a missing backup.
        raise NeedsFullDiskAccessError(str(BACKUP_ROOT)) from err
    backups = [d for d in entries if (d / "Manifest.db").is_file()]
    return sorted(backups, key=lambda d: d.stat().st_mtime, reverse=True)


def is_encrypted(backup: Path) -> bool:
    """Return True if the backup is encrypted, which makes the manifest opaque."""
    manifest = backup / "Manifest.plist"
    if not manifest.is_file():
        return False
    try:
        with manifest.open("rb") as handle:
            return bool(plistlib.load(handle).get("IsEncrypted"))
    except OSError, plistlib.InvalidFileException:
        return False


def find_preference_files(backup: Path) -> list[tuple[str, str]]:
    """Return (fileID, relativePath) for candidate preference plists."""
    query = """
        SELECT fileID, domain, relativePath FROM Files
        WHERE relativePath LIKE '%.plist'
          AND (LOWER(domain) LIKE ? OR LOWER(domain) LIKE ?)
    """
    with sqlite3.connect(f"file:{backup / 'Manifest.db'}?mode=ro", uri=True) as db:
        rows = db.execute(query, [f"%{h}%" for h in DOMAIN_HINTS]).fetchall()
    return [(file_id, f"{domain}/{path}") for file_id, domain, path in rows]


def stored_path(backup: Path, file_id: str) -> Path:
    """Return where a backed-up file physically lives."""
    return backup / file_id[:2] / file_id


def read_plist(path: Path) -> dict[str, object]:
    """Load a plist, converting from binary form if needed."""
    try:
        with path.open("rb") as handle:
            loaded = plistlib.load(handle)
    except plistlib.InvalidFileException:
        converted = subprocess.run(
            ["/usr/bin/plutil", "-convert", "xml1", "-o", "-", str(path)],
            capture_output=True,
            check=False,
        )
        if converted.returncode != 0:
            return {}
        loaded = plistlib.loads(converted.stdout)
    return loaded if isinstance(loaded, dict) else {}


def find_passwords(data: dict[str, object]) -> list[tuple[str, bytes]]:
    """Return every (key, 16-byte password) pair the plist holds."""
    found = []
    for key, value in data.items():
        if not key.endswith("_decrypt"):
            continue
        raw: bytes | None = None
        if isinstance(value, bytes):
            raw = value
        elif isinstance(value, str):
            try:
                raw = base64.b64decode(value, validate=True)
            except ValueError, base64.binascii.Error:
                raw = None
        if raw and len(raw) == PASSWORD_LENGTH:
            found.append((key, raw))
    return found


def scan_backup(backup: Path, wanted_serial: str | None) -> int:
    """Report any stored passwords in one backup. Returns how many were found."""
    if is_encrypted(backup):
        print("    ENCRYPTED - its manifest cannot be read.")
        print("    Make an unencrypted backup, or decrypt this one first.")
        return 0

    try:
        candidates = find_preference_files(backup)
    except sqlite3.DatabaseError as err:
        print(f"    Could not read the manifest: {err}")
        return 0

    if not candidates:
        print("    No Ninebot or Segway app data in this backup.")
        return 0

    hits = 0
    for file_id, description in candidates:
        path = stored_path(backup, file_id)
        if not path.is_file():
            continue
        for key, password in find_passwords(read_plist(path)):
            serial = key.removesuffix("_decrypt")
            if wanted_serial and serial != wanted_serial:
                continue
            hits += 1
            print(f"    {description}")
            print(f"      serial:   {serial}")
            print(f"      password: {password.hex().upper()}")
    if not hits:
        print("    App data present, but no stored password for this vehicle.")
    return hits


def explain_full_disk_access(path: str) -> None:
    """Tell the user how to grant the permission macOS just denied."""
    print(f"Cannot read {path}\n")
    print("macOS is blocking it. Grant Full Disk Access to this terminal:")
    print("  System Settings -> Privacy & Security -> Full Disk Access")
    print("  add your terminal app, enable it, then QUIT AND REOPEN it.")
    print("\nThe permission only applies to terminals started afterwards.")


def main() -> int:
    """Search local backups for a stored session password."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="only report this scooter's password")
    parser.add_argument("--backup", type=Path, help="use a specific backup directory")
    args = parser.parse_args()

    try:
        backups = [args.backup] if args.backup else find_backups()
    except NeedsFullDiskAccessError as err:
        explain_full_disk_access(str(err))
        return 1

    if not backups:
        if not BACKUP_ROOT.is_dir():
            print(f"No backup directory at {BACKUP_ROOT}")
        else:
            print(f"No backups found under {BACKUP_ROOT}")
            print("Create one in Finder, with 'Encrypt local backup' unchecked.")
        return 1

    print(f"Found {len(backups)} backup(s).\n")
    hits = 0

    for backup in backups:
        print(f"=== {backup.name}")
        hits += scan_backup(backup, args.serial)
        print()

    if not hits:
        print("No stored password found.")
        print("The backup may predate pairing the scooter, or the app may not")
        print("have been included. Re-pair in the app, back up again, retry.")
        return 1

    print("Pass this to the probe with --password <hex>.")
    print("Treat it as a credential: it authenticates against your scooter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
