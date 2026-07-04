from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Tuple


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _amount(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def find_likely_duplicates(
    new_tx: Dict[str, Any],
    recent_rows: Iterable[Dict[str, Any]],
    threshold: float = 0.75,
) -> List[Tuple[float, Dict[str, Any]]]:
    """Find same-amount, similar-description recent rows."""
    new_amount = _amount(new_tx.get("jumlah"))
    new_desc = _norm(new_tx.get("keterangan"))
    new_project = _norm(new_tx.get("nama_projek"))
    new_company = _norm(new_tx.get("company_sheet") or new_tx.get("company"))
    new_tipe = _norm(new_tx.get("tipe"))

    if new_amount <= 0 or not new_desc:
        return []

    hits = []
    for row in recent_rows or []:
        if not isinstance(row, dict):
            continue
        if _amount(row.get("jumlah")) != new_amount:
            continue

        row_tipe = _norm(row.get("tipe"))
        if new_tipe and row_tipe and new_tipe != row_tipe:
            continue

        row_company = _norm(row.get("company_sheet") or row.get("company"))
        if new_company and row_company and new_company != row_company:
            continue

        row_project = _norm(row.get("nama_projek"))
        if new_project and row_project and new_project != row_project:
            project_score = SequenceMatcher(None, new_project, row_project).ratio()
            if project_score < 0.65:
                continue

        row_desc = _norm(row.get("keterangan"))
        score = SequenceMatcher(None, new_desc, row_desc).ratio()
        if score >= threshold:
            hits.append((score, row))

    hits.sort(key=lambda item: item[0], reverse=True)
    return hits

