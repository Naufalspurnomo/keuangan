"""
Transaction context routing helpers.

This module decides whether extracted transactions should follow the project
flow or operational flow. It keeps main.py focused on orchestration.
"""

import re

from config.constants import OPERATIONAL_KEYWORDS, PROJECT_STOPWORDS
from services.project_service import get_existing_projects


def map_operational_category(keyword: str) -> str:
    """
    Maps keywords to standard Operational Categories.
    Expanded keyword matching.
    """
    k = keyword.lower()

    # Payroll
    if k in ['gaji', 'salary', 'upah', 'honor', 'thr', 'bonus', 'upah karyawan']:
        return 'Gaji'

    # Utilities
    if k in ['listrik', 'pln', 'air', 'pdam', 'wifi', 'internet', 'listrikair', 'speedy', 'indihome']:
        return 'ListrikAir'

    # Consumables
    if k in ['konsumsi', 'makan', 'snack', 'minum', 'jamu', 'kopi']:
        return 'Konsumsi'

    # Equipment
    if k in ['peralatan', 'atk', 'alat', 'perlengkapan', 'alat tulis', 'perlengkapan kantor']:
        return 'Peralatan'

    return 'Lain Lain'


def detect_transaction_context(text: str, transactions: list, category_scope: str = 'UNKNOWN') -> dict:
    """
    Detects context: PROJECT vs OPERATIONAL.

    Rules:
    1. If AI says OPERATIONAL -> OPERATIONAL unless explicit project override.
    2. Has valid project name -> PROJECT.
    3. Has operational keywords + no valid project -> OPERATIONAL.
    4. Else -> PROJECT.
    """
    text_lower = (text or '').lower()
    has_project_word = bool(re.search(r"\b(projek|project|proyek|prj)\b", text_lower))
    has_kantor_word = bool(re.search(r"\b(kantor|office|operasional|operational|ops)\b", text_lower))

    # Trust AI's category_scope if available, while allowing explicit scope words.
    if category_scope == 'OPERATIONAL' and has_project_word:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}
    if category_scope == 'OPERATIONAL':
        detected_keywords = [kw for kw in OPERATIONAL_KEYWORDS if kw in text_lower]
        category = map_operational_category(detected_keywords[0]) if detected_keywords else 'Lain Lain'
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}

    if category_scope == 'PROJECT':
        if has_kantor_word and not has_project_word:
            detected_keywords = [kw for kw in OPERATIONAL_KEYWORDS if kw in text_lower]
            category = map_operational_category(detected_keywords[0]) if detected_keywords else 'Lain Lain'
            return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}

    if category_scope == 'TRANSFER':
        # Wallet balance updates are recorded to dompet with "Saldo Umum".
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}

    if category_scope == 'AMBIGUOUS':
        if has_project_word and not has_kantor_word:
            return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}
        if has_kantor_word and not has_project_word:
            detected_keywords = [kw for kw in OPERATIONAL_KEYWORDS if kw in text_lower]
            category = map_operational_category(detected_keywords[0]) if detected_keywords else 'Lain Lain'
            return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}
        return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}

    detected_keywords = []
    for kw in OPERATIONAL_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
            detected_keywords.append(kw)

    if has_project_word and has_kantor_word:
        return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}
    if has_project_word:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}
    if has_kantor_word:
        category = map_operational_category(detected_keywords[0]) if detected_keywords else 'Lain Lain'
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}

    try:
        from utils.transaction_scope_detector import AMBIGUOUS_KEYWORDS as _AMBIGUOUS
        ambiguous_keywords = set(_AMBIGUOUS.keys())
    except Exception:
        ambiguous_keywords = set()
    matched_ambiguous = [
        k for k in ambiguous_keywords
        if re.search(r'\b' + re.escape(k) + r'\b', text_lower)
    ]
    has_ambiguous_keyword = bool(matched_ambiguous)
    generic_ambiguous = {'bayar'}
    has_generic_ambiguous_only = bool(matched_ambiguous) and all(
        k in generic_ambiguous for k in matched_ambiguous
    )

    office_roles = set()
    field_roles = set()
    try:
        from utils.transaction_scope_detector import OFFICE_ROLES as _OFFICE, FIELD_ROLES as _FIELD
        office_roles = set(_OFFICE)
        field_roles = set(_FIELD)
    except Exception:
        office_roles = set()
        field_roles = set()

    has_office_role = any(re.search(r'\b' + re.escape(r) + r'\b', text_lower) for r in office_roles)
    has_field_role = any(re.search(r'\b' + re.escape(r) + r'\b', text_lower) for r in field_roles)

    existing_projects_cache = {p.lower() for p in get_existing_projects()}
    has_valid_project = False
    valid_project_name = None

    for tx in transactions:
        nama_projek = tx.get('nama_projek', '')
        if nama_projek and len(nama_projek) > 2:
            clean_name = nama_projek.lower().strip()

            if clean_name in existing_projects_cache:
                return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False, 'project_name': nama_projek}

            generic_names = {'umum', 'kantor', 'ops', 'operasional', 'admin', 'gaji', 'finance'}
            generic_names.update(OPERATIONAL_KEYWORDS)
            generic_names.update(PROJECT_STOPWORDS)

            if clean_name not in generic_names:
                is_just_keyword = (clean_name in PROJECT_STOPWORDS or clean_name in OPERATIONAL_KEYWORDS)
                if not is_just_keyword:
                    has_valid_project = True
                    valid_project_name = nama_projek
                    break

    detected_ambiguous = [kw for kw in detected_keywords if kw in ambiguous_keywords]
    all_ambiguous = bool(detected_keywords) and len(detected_ambiguous) == len(detected_keywords)

    if has_project_word and not has_kantor_word:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}
    if has_office_role and not has_project_word:
        category = map_operational_category(detected_keywords[0]) if detected_keywords else 'Lain Lain'
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}
    if has_field_role and not has_kantor_word:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}

    if detected_keywords and not has_valid_project:
        if all_ambiguous or (has_ambiguous_keyword and not has_generic_ambiguous_only):
            return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}
        category = map_operational_category(detected_keywords[0])
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}

    if has_valid_project:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False, 'project_name': valid_project_name}

    if detected_keywords:
        if all_ambiguous or (has_ambiguous_keyword and not has_generic_ambiguous_only):
            return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}
        category = map_operational_category(detected_keywords[0])
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}

    if has_ambiguous_keyword and not has_valid_project:
        return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}

    return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}
