"""
Lifecycle helpers for project naming (Start/Finish markers).
"""
import re
from services.project_service import get_existing_projects
from config.wallets import strip_company_prefix


MARKER_RE = re.compile(r"\s*\((start|finish)\)\s*$", re.IGNORECASE)


def _strip_marker(project_name: str) -> str:
    """Remove trailing lifecycle marker to prevent duplicate markers."""
    return MARKER_RE.sub("", project_name or "").strip()


def apply_lifecycle_markers(project_name: str, transaction: dict, is_new_project: bool = False, allow_finish: bool = True) -> str:
    """
    Applies (Start) or (Finish) markers to project names.
    Rules:
    - New projects always get (Start), even if first TX is Pengeluaran.
    - Finish marker is applied on pelunasan-like pemasukan.
    - Marker is normalized so we do not end up with duplicate suffixes.
    """
    if not project_name:
        return project_name

    tipe = str(transaction.get('tipe') or '')
    desc = (transaction.get('keterangan', '') or '').lower()
    base_name = _strip_marker(project_name)

    # Rule 1: Finish
    finish_keywords = ['pelunasan', 'lunas', 'final payment', 'penyelesaian', 'selesai', 'kelar', 'beres']
    if allow_finish and tipe == 'Pemasukan' and any(k in desc for k in finish_keywords):
        return f"{base_name} (Finish)"

    # Rule 2: Start for explicitly new project (works for Pengeluaran too)
    if is_new_project:
        return f"{base_name} (Start)"

    # Existing auto-detect keeps old behavior: only mark Start on Pemasukan
    if tipe != 'Pemasukan':
        return project_name

    existing = get_existing_projects()
    lookup_name = strip_company_prefix(base_name) or base_name

    # Check if project exists (case insensitive)
    if not any(e.lower() in {base_name.lower(), lookup_name.lower()} for e in existing):
        return f"{base_name} (Start)"

    return project_name
