#!/usr/bin/env python3
"""Validate or explicitly seed one project-document issuer profile from JSON."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

with contextlib.redirect_stdout(io.StringIO()):
    from services.project_document_repository import ProjectDocumentRepository

_CONFIRMATION = "APPLY_ISSUER_PROFILE"
_REQUIRED = (
    "issuer_key",
    "legal_name",
    "display_name",
    "number_code",
    "address",
    "expected_version",
)
_ALLOWED = frozenset(
    {
        *_REQUIRED,
        "phone",
        "email",
        "tax_identity",
        "bank_details",
        "logo_path",
    }
)


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(dict(payload), sort_keys=True, separators=(",", ":")))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or seed an issuer profile")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser


def _load(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("issuer file must be a regular file")
        if path.stat().st_size > 64 * 1024:
            raise ValueError("issuer file is too large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid issuer file") from exc
    if not isinstance(value, dict) or set(value) - _ALLOWED:
        raise ValueError("invalid issuer file")
    return value


def _validate(value: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in _REQUIRED:
        item = value.get(field)
        if field == "expected_version":
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                missing.append(field)
        elif not isinstance(item, str) or not item.strip():
            missing.append(field)
    if not missing:
        code = str(value["number_code"]).strip().upper()
        if len(code) > 16 or not code.replace("-", "").isalnum():
            missing.append("number_code")
        bank = value.get("bank_details", {})
        if not isinstance(bank, dict):
            missing.append("bank_details")
    return missing


def _dsn() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def main() -> None:
    args = _parser().parse_args()
    action = "apply" if args.apply else "validate"
    try:
        value = _load(args.file)
    except ValueError:
        _emit({"action": action, "error": "invalid_issuer_file", "missing": list(_REQUIRED)})
        raise SystemExit(2) from None
    missing = _validate(value)
    if missing:
        _emit({"action": action, "error": "invalid_issuer_file", "missing": missing})
        raise SystemExit(2)

    issuer_key = str(value["issuer_key"]).strip()
    number_code = str(value["number_code"]).strip().upper()
    if not args.apply:
        _emit(
            {
                "action": action,
                "issuer_key": issuer_key,
                "number_code": number_code,
                "valid": True,
            }
        )
        return
    if args.confirm != _CONFIRMATION:
        _emit({"action": action, "error": "confirmation_required", "issuer_key": issuer_key})
        raise SystemExit(2)
    selected = _dsn()
    if not selected:
        _emit({"action": action, "error": "database_not_configured", "issuer_key": issuer_key})
        raise SystemExit(2)

    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    key = "issuer-bootstrap-" + hashlib.sha256(canonical).hexdigest()
    repository = ProjectDocumentRepository(selected)
    result = repository.upsert_issuer_profile(
        issuer_key=issuer_key,
        legal_name=str(value["legal_name"]).strip(),
        display_name=str(value["display_name"]).strip(),
        number_code=number_code,
        address=str(value["address"]).strip(),
        phone=value.get("phone"),
        email=value.get("email"),
        tax_identity=value.get("tax_identity"),
        bank_details=value.get("bank_details") or {},
        logo_path=value.get("logo_path"),
        expected_version=int(value["expected_version"]),
        idempotency_key=key,
        actor={"role": "deployment", "source": "issuer-bootstrap-cli"},
    )
    _emit(
        {
            "action": action,
            "issuer_key": result["issuer_key"],
            "number_code": result["number_code"],
            "profile_version": result["profile_version"],
        }
    )


if __name__ == "__main__":
    main()
