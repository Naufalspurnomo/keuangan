"""
Lifecycle helpers for project naming (Start/Finish markers).
"""
from services.project_service import get_existing_projects


def apply_lifecycle_markers(project_name: str, transaction: dict, is_new_project: bool = False) -> str:
    """
    Applies (Start) or (Finish) markers to project names.
    Only for 'Pemasukan' transactions.
    """
    if not project_name or transaction.get('tipe') != 'Pemasukan':
        return project_name

    desc = (transaction.get('keterangan', '') or '').lower()

    # Rule 1: Finish
    finish_keywords = ['pelunasan', 'lunas', 'final payment', 'penyelesaian', 'selesai', 'kelar', 'beres']
    if any(k in desc for k in finish_keywords):
        return f"{project_name} (Finish)"

    # Rule 2: Start (New Project Auto-Detect)
    if is_new_project:
        return f"{project_name} (Start)"

    existing = get_existing_projects()

    # Check if project exists (case insensitive)
    if not any(e.lower() == project_name.lower() for e in existing):
        return f"{project_name} (Start)"

    return project_name
