#!/usr/bin/env python3
"""Check or explicitly apply the additive project-document PostgreSQL schema.

Default mode is read-only. The command never prints the database URL.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Importing the application service graph emits startup diagnostics. Keep this
# one-off CLI stdout as a strict JSON channel for automation and evidence.
with contextlib.redirect_stdout(io.StringIO()):
    from services.project_document_repository import (
        ProjectDocumentUnavailable,
        ensure_project_document_schema,
        project_document_schema_health,
    )

_CONFIRMATION = "APPLY_PROJECT_DOCUMENT_SCHEMA"
_REQUIRED_READBACK = ("ready", "tables", "constraints", "indexes", "triggers")


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(dict(payload), sort_keys=True, separators=(",", ":")))


def _dsn() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def _complete(health: Mapping[str, Any]) -> bool:
    return all(bool(health.get(field)) for field in _REQUIRED_READBACK)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check or apply the Hollawall project-document schema",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Read schema health only (default)")
    mode.add_argument("--apply", action="store_true", help="Apply the additive schema once")
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Required with --apply: {_CONFIRMATION}",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    action = "apply" if args.apply else "check"
    selected = _dsn()
    if not selected:
        _emit(
            {
                "action": action,
                "configured": False,
                "error": "database_not_configured",
                "ready": False,
            }
        )
        raise SystemExit(2)
    if args.apply and args.confirm != _CONFIRMATION:
        _emit(
            {
                "action": action,
                "configured": True,
                "error": "confirmation_required",
                "ready": False,
            }
        )
        raise SystemExit(2)

    try:
        health = (
            ensure_project_document_schema(selected)
            if args.apply
            else project_document_schema_health(selected)
        )
    except ProjectDocumentUnavailable as exc:
        _emit(
            {
                "action": action,
                "configured": True,
                "error": type(exc).__name__,
                "ready": False,
            }
        )
        raise SystemExit(1) from None
    except Exception as exc:
        _emit(
            {
                "action": action,
                "configured": True,
                "error": type(exc).__name__,
                "ready": False,
            }
        )
        raise SystemExit(1) from None

    payload = {"action": action, "configured": True, **dict(health)}
    _emit(payload)
    if not _complete(health):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
