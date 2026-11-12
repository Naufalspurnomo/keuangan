"""Build a deterministic finance migration manifest from an immutable snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.financial_migration import build_manifest  # noqa: E402


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run the canonical finance backfill from an immutable source snapshot."
    )
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--mappings", type=Path, required=True)
    parser.add_argument("--start-after")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="Required safety flag; this command never writes PostgreSQL or Sheets.",
    )
    args = parser.parse_args(argv)

    manifest = build_manifest(
        _load(args.snapshot),
        _load(args.mappings),
        start_after=args.start_after,
        limit=args.limit,
    )
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
