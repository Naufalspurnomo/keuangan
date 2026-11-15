#!/usr/bin/env python3
"""Transactionally remove exact verified Presensi acceptance events over FTPS."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import ssl
from ftplib import FTP_TLS, error_perm  # nosec B402 -- TLS-only owner-scoped maintenance
from pathlib import PurePosixPath
from typing import Any, cast


def connect(host: str, user: str, password: str, port: int) -> FTP_TLS:
    ftp = FTP_TLS(context=ssl.create_default_context(), timeout=60)
    ftp.connect(host, port)
    ftp.login(user, password)
    ftp.prot_p()
    ftp.set_pasv(True)
    return ftp

EVENT_PATTERN = re.compile(r"evt-[0-9a-f]{24}\Z")


def safe_event_ids(raw: str) -> set[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values or len(values) > 20 or len(set(values)) != len(values):
        raise ValueError("event IDs must be 1-20 unique comma-separated values")
    if any(EVENT_PATTERN.fullmatch(item) is None for item in values):
        raise ValueError("invalid event ID")
    return set(values)


def safe_remote(path: str) -> str:
    parsed = PurePosixPath(path)
    if not path or parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError("unsafe remote path")
    return parsed.as_posix()


def read_bytes(ftp: FTP_TLS, path: str) -> bytes:
    buffer = io.BytesIO()
    ftp.retrbinary(f"RETR {path}", buffer.write)
    return buffer.getvalue()


def file_exists(ftp: FTP_TLS, path: str) -> bool:
    try:
        ftp.size(path)
        return True
    except error_perm:
        return False


def chmod_private(ftp: FTP_TLS, path: str) -> None:
    ftp.sendcmd(f"SITE CHMOD 600 {path}")


def cleanup_events(
    ftp: FTP_TLS,
    event_ids: set[str],
    *,
    events_path: str = ".hollawall-presensi/events.json",
    photos_dir: str = ".hollawall-presensi/photos",
) -> dict[str, Any]:
    events_path = safe_remote(events_path)
    photos_dir = safe_remote(photos_dir)
    original = read_bytes(ftp, events_path)
    try:
        events = json.loads(original)
    except Exception as exc:
        raise RuntimeError("events store is not valid JSON") from exc
    if not isinstance(events, list):
        raise RuntimeError("events store must be an array")

    matched = [row for row in events if isinstance(row, dict) and row.get("id") in event_ids]
    if {str(row.get("id")) for row in matched} != event_ids or len(matched) != len(event_ids):
        raise RuntimeError("exact cleanup targets do not match the private store")
    if any((row.get("whatsapp_delivery") or {}).get("status") != "sent" for row in matched):
        raise RuntimeError("all cleanup targets must have WhatsApp status sent")

    photo_names = [str(row.get("photo_name") or "") for row in matched]
    if len(set(photo_names)) != len(photo_names):
        raise RuntimeError("cleanup photo names are not unique")
    photo_bytes: dict[str, bytes] = {}
    for event_id, name in zip((str(row["id"]) for row in matched), photo_names, strict=True):
        if not re.fullmatch(re.escape(event_id) + r"\.(?:jpg|jpeg|png|webp)", name, re.IGNORECASE):
            raise RuntimeError("cleanup photo name does not match its event ID")
        photo_path = f"{photos_dir}/{name}"
        if not file_exists(ftp, photo_path):
            raise RuntimeError("exact cleanup photo is missing")
        photo_bytes[photo_path] = read_bytes(ftp, photo_path)

    remaining = [row for row in events if not (isinstance(row, dict) and row.get("id") in event_ids)]
    updated = (json.dumps(remaining, ensure_ascii=False, indent=2) + "\n").encode()
    nonce = secrets.token_hex(8)
    staging = f"{events_path}.cleanup-next-{nonce}"
    backup = f"{events_path}.cleanup-prev-{nonce}"
    quarantined = {
        f"{photos_dir}/{name}": f"{photos_dir}/.{name}.cleanup-{nonce}"
        for name in photo_names
    }
    activated = False
    moved_photos: list[tuple[str, str]] = []
    try:
        ftp.storbinary(f"STOR {staging}", io.BytesIO(updated))
        chmod_private(ftp, staging)
        if read_bytes(ftp, staging) != updated:
            raise RuntimeError("staged cleanup readback mismatch")
        for source, target in quarantined.items():
            ftp.rename(source, target)
            moved_photos.append((source, target))
        ftp.rename(events_path, backup)
        ftp.rename(staging, events_path)
        activated = True
        chmod_private(ftp, events_path)
        if read_bytes(ftp, events_path) != updated:
            raise RuntimeError("final cleanup readback mismatch")
        decoded = json.loads(read_bytes(ftp, events_path))
        if any(isinstance(row, dict) and row.get("id") in event_ids for row in decoded):
            raise RuntimeError("event cleanup verification failed")
        for _source, target in moved_photos:
            ftp.delete(target)
        ftp.delete(backup)
    except Exception:
        if activated:
            try:
                if file_exists(ftp, events_path):
                    ftp.delete(events_path)
                ftp.rename(backup, events_path)
                chmod_private(ftp, events_path)
            except Exception:
                pass
        elif file_exists(ftp, backup) and not file_exists(ftp, events_path):
            try:
                ftp.rename(backup, events_path)
                chmod_private(ftp, events_path)
            except Exception:
                pass
        if file_exists(ftp, staging):
            try:
                ftp.delete(staging)
            except Exception:
                pass
        for source, target in reversed(moved_photos):
            try:
                if file_exists(ftp, target) and not file_exists(ftp, source):
                    ftp.rename(target, source)
                elif not file_exists(ftp, source):
                    ftp.storbinary(f"STOR {source}", io.BytesIO(photo_bytes[source]))
                    chmod_private(ftp, source)
            except Exception:
                pass
        raise

    if any(file_exists(ftp, f"{photos_dir}/{name}") for name in photo_names):
        raise RuntimeError("photo cleanup verification failed")
    return {
        "success": True,
        "removed_event_ids": sorted(event_ids),
        "removed_events": len(matched),
        "removed_photos": len(photo_names),
        "remaining_events": len(remaining),
        "events_sha256": hashlib.sha256(updated).hexdigest(),
        "readback_clean": True,
        "credentials_exposed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-ids", required=True)
    parser.add_argument("--events-path", default=".hollawall-presensi/events.json")
    parser.add_argument("--photos-dir", default=".hollawall-presensi/photos")
    parser.add_argument("--evidence")
    parser.add_argument("--port", type=int, default=int(os.getenv("RW_FTP_PORT", "21")))
    args = parser.parse_args()
    host = os.getenv("RW_FTP_HOST")
    user = os.getenv("RW_FTP_USER")
    password = os.getenv("RW_FTP_PASSWORD")
    if not all((host, user, password)):
        raise RuntimeError("RW_FTP_HOST, RW_FTP_USER, and RW_FTP_PASSWORD are required")
    ftp = connect(cast(str, host), cast(str, user), cast(str, password), args.port)
    try:
        result = cleanup_events(
            ftp,
            safe_event_ids(args.event_ids),
            events_path=args.events_path,
            photos_dir=args.photos_dir,
        )
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
        for key in ("RW_FTP_HOST", "RW_FTP_USER", "RW_FTP_PASSWORD"):
            os.environ.pop(key, None)
    if args.evidence:
        with open(args.evidence, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
