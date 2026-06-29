"""
extract_divergences.py - Ubah log NARROW_SHADOW jadi draft fixtures.

ALUR KERJA (Fase 2a -> loop fixtures):
1. Jalankan bot dengan NARROW_RESOLVER_SHADOW=1, simpan lognya ke file.
2. Jalankan skrip ini terhadap file log itu.
3. Skrip menarik baris "NARROW_SHADOW divergence", mengubahnya jadi draft
   fixture JSON, lalu MANUSIA mengisi label `expect` yang benar (ground truth).
4. Tempel case yang sudah dilabeli ke tests/replay/fixtures.json.

PENTING: skrip ini TIDAK menebak jawaban benar. Ia hanya menyiapkan kerangka
case + apa yang dilihat resolver vs pipeline, supaya pelabelan manusia cepat.
Tidak menyentuh produksi; murni alat bantu offline.

Pakai:
    python -m tests.replay.extract_divergences path/ke/bot.log
    python -m tests.replay.extract_divergences path/ke/bot.log --out draft_fixtures.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional

# Baris log contoh yang diharapkan (dari _shadow_compare_narrow_resolver):
#   ... NARROW_SHADOW divergence | conf=0.7 needs_conf=True | main_wallet: resolver='TX SBY(216)' pipeline=None | debt_source: resolver=None pipeline='CV HB(101)'
DIVERGENCE_RE = re.compile(r"NARROW_SHADOW divergence\s*\|\s*(?P<body>.*)$")
CONF_RE = re.compile(r"conf=(?P<conf>[0-9.]+)\s+needs_conf=(?P<needs>\w+)")
FIELD_RE = re.compile(
    r"(?P<field>main_wallet|debt_source|project):\s*resolver=(?P<resolver>.+?)\s+pipeline=(?P<pipeline>.+?)(?=\s*\||$)"
)


def _parse_repr_value(token: str) -> Optional[str]:
    """Convert a logged repr-ish token into a plain value or None."""
    token = (token or "").strip()
    if token in ("None", "", "[]"):
        return None
    # Strip surrounding quotes if present.
    if len(token) >= 2 and token[0] in "'\"" and token[-1] == token[0]:
        return token[1:-1]
    # List form e.g. ['vadim'] -> take first element heuristically.
    m = re.match(r"\[\s*'([^']*)'", token)
    if m:
        return m.group(1)
    return token


def parse_divergence_line(line: str) -> Optional[Dict[str, Any]]:
    m = DIVERGENCE_RE.search(line)
    if not m:
        return None
    body = m.group("body")

    conf = None
    needs = None
    cm = CONF_RE.search(body)
    if cm:
        try:
            conf = float(cm.group("conf"))
        except ValueError:
            conf = None
        needs = cm.group("needs").strip().lower() == "true"

    fields: Dict[str, Dict[str, Optional[str]]] = {}
    for fm in FIELD_RE.finditer(body):
        fields[fm.group("field")] = {
            "resolver": _parse_repr_value(fm.group("resolver")),
            "pipeline": _parse_repr_value(fm.group("pipeline")),
        }

    if not fields:
        return None

    return {"confidence": conf, "needs_confirmation": needs, "fields": fields}


def divergence_to_draft_case(parsed: Dict[str, Any], idx: int) -> Dict[str, Any]:
    """Build a draft fixture case. `expect` is left for human labeling."""
    fields = parsed.get("fields", {})

    def _seen(field: str) -> Dict[str, Optional[str]]:
        return fields.get(field, {})

    # Draft expectations default to pipeline values as a STARTING POINT only.
    # A human MUST review: pipeline is not ground truth.
    return {
        "id": f"shadow-divergence-{idx}",
        "text": "<<ISI teks chat asli di sini>>",
        "note": "DRAFT dari shadow log. WAJIB dilabeli manusia. resolver vs pipeline: "
                + "; ".join(
                    f"{k}(resolver={v.get('resolver')!r}, pipeline={v.get('pipeline')!r})"
                    for k, v in fields.items()
                ),
        "needs_review": True,
        "_observed": {
            "confidence": parsed.get("confidence"),
            "resolver_needs_confirmation": parsed.get("needs_confirmation"),
            "fields": fields,
        },
        "expect": {
            "project": _seen("project").get("pipeline"),
            "main_wallet": _seen("main_wallet").get("pipeline"),
            "debt_source": _seen("debt_source").get("pipeline"),
            "company": None,
            "needs_confirmation": False,
        },
    }


def extract(log_path: str) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    idx = 1
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parsed = parse_divergence_line(line)
            if not parsed:
                continue
            cases.append(divergence_to_draft_case(parsed, idx))
            idx += 1
    return cases


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Extract NARROW_SHADOW divergences into draft fixtures.")
    parser.add_argument("log_path", help="Path to bot log file containing NARROW_SHADOW lines.")
    parser.add_argument("--out", default=None, help="Write draft fixtures JSON to this path (default: stdout).")
    args = parser.parse_args(argv)

    try:
        cases = extract(args.log_path)
    except FileNotFoundError:
        print(f"Log file not found: {args.log_path}", file=sys.stderr)
        return 2

    payload = {
        "_note": "DRAFT fixtures dari shadow log. Setiap case wajib direview manusia: "
                 "isi `text` asli, perbaiki `expect` (pipeline BUKAN ground truth), lalu hapus needs_review.",
        "cases": cases,
    }
    output = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output + "\n")
        print(f"Wrote {len(cases)} draft case(s) to {args.out}")
    else:
        print(output)

    if not cases:
        print("(no NARROW_SHADOW divergence lines found)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
