import time
import logging
from difflib import SequenceMatcher
from sheets_helper import get_sheet
from config.constants import KNOWN_COMPANY_NAMES, OPERATIONAL_KEYWORDS, PROJECT_STOPWORDS
from services.state_manager import resolve_project_knowledge

_project_cache = {
    'names': set(),
    'records': [],
    'last_updated': 0,
    'ttl': 300
}

from config.wallets import (
    DOMPET_SHEETS,
    extract_company_prefix,
    get_company_name_from_sheet,
    strip_company_prefix,
)
from config.constants import SPLIT_LAYOUT_DATA_START, SPLIT_PEMASUKAN, SPLIT_PENGELUARAN
import re


def _normalize_project_name(name: str) -> str:
    """Normalize project names for consistent cache matching."""
    if not name:
        return ""
    cleaned = str(name).strip()
    cleaned = re.sub(r'\s*\((Start|Finish|Selesai)\)$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def get_existing_projects(force_refresh=False):
    """
    Ambil list projek unik dari 3 Sheet Dompet (Split Layout).
    Source: Column Index 5 (E) inside Pemasukan/Pengeluaran blocks if needed?
    Actually SPLIT_PEMASUKAN['PROJECT'] = 5, SPLIT_PENGELUARAN['PROJECT'] = 14 (N).
    We should scan BOTH? Or just assume projects are mentioned in Pengeluaran mostly?
    Let's scan Pengeluaran (Col N / 14) as mostly costs are project related.
    """
    global _project_cache
    now = time.time()
    
    if force_refresh or (now - _project_cache['last_updated'] > _project_cache['ttl']):
        try:
            all_projects = set()
            project_records = []
            seen_records = set()

            # Once the import is verified, this avoids a full Sheets scan for
            # every project validation. Returning None deliberately preserves
            # the Sheets path until the database contains real ledger data.
            try:
                from services.ledger_store import read_project_records

                database_records = read_project_records()
            except Exception as exc:
                logging.error(f"[ProjectService] Ledger index unavailable: {type(exc).__name__}")
                database_records = None

            if database_records is not None:
                for record in database_records:
                    raw_project = str(record.get('name') or '').strip()
                    if not raw_project:
                        continue
                    all_projects.add(raw_project)
                    clean_project = _normalize_project_name(raw_project)
                    prefix = extract_company_prefix(clean_project)
                    company = prefix or record.get('company') or get_company_name_from_sheet(record.get('dompet') or '')
                    record_key = (clean_project.lower(), record.get('dompet') or '', str(company or '').upper())
                    if record_key not in seen_records:
                        seen_records.add(record_key)
                        project_records.append({
                            'name': clean_project,
                            'base_name': strip_company_prefix(clean_project),
                            'dompet': record.get('dompet') or '',
                            'company': company,
                        })

            # Iterate Sheets only before database cutover or during fallback.
            for sheet_name in ([] if database_records is not None else DOMPET_SHEETS):
                sh = get_sheet(sheet_name)
                if not sh: continue
                
                try:
                    rows = sh.get(f"A{SPLIT_LAYOUT_DATA_START}:R") or []
                    for row in rows:
                        for col_idx in (SPLIT_PEMASUKAN['PROJECT'], SPLIT_PENGELUARAN['PROJECT']):
                            raw_project = row[col_idx - 1] if len(row) >= col_idx else ""
                            raw_project = str(raw_project or "").strip()
                            if not raw_project:
                                continue

                            all_projects.add(raw_project)
                            clean_project = _normalize_project_name(raw_project)
                            if not clean_project:
                                continue

                            prefix = extract_company_prefix(clean_project)
                            company = prefix or get_company_name_from_sheet(sheet_name)
                            record_key = (clean_project.lower(), sheet_name, str(company or "").upper())
                            if record_key in seen_records:
                                continue
                            seen_records.add(record_key)
                            project_records.append({
                                'name': clean_project,
                                'base_name': strip_company_prefix(clean_project),
                                'dompet': sheet_name,
                                'company': company,
                            })

                except Exception as ex:
                    logging.warning(f"Error reading projects from {sheet_name}: {ex}")
                    continue

            # Clean and Filter
            clean_projects_by_key = {}
            for v in all_projects:
                v_clean = _normalize_project_name(v)
                if not v_clean:
                    continue

                v_key = v_clean.lower()
                if len(v_clean) > 2 and v_key not in KNOWN_COMPANY_NAMES:
                    # Keep first-seen casing but deduplicate case-insensitively.
                    clean_projects_by_key.setdefault(v_key, v_clean)

            clean_projects = set(clean_projects_by_key.values())
            
            _project_cache['names'] = clean_projects
            _project_cache['records'] = [
                r for r in project_records
                if len(r.get('base_name') or r.get('name') or '') > 2
                and (r.get('base_name') or r.get('name') or '').lower() not in KNOWN_COMPANY_NAMES
            ]
            _project_cache['last_updated'] = now
            logging.info(f"[ProjectService] Loaded {len(clean_projects)} projects from Sheets")
            
        except Exception as e:
            logging.error(f"[ProjectService] Failed: {e}")
            
    return _project_cache['names']


def get_existing_project_records(force_refresh=False, dompet_sheet=None, company=None):
    get_existing_projects(force_refresh=force_refresh)
    records = list(_project_cache.get('records') or [])
    if dompet_sheet:
        records = [r for r in records if r.get('dompet') == dompet_sheet]
    if company:
        company_key = str(company).strip().upper()
        records = [r for r in records if str(r.get('company') or '').strip().upper() == company_key]
    return records

def add_new_project_to_cache(new_project_name):
    normalized = _normalize_project_name(new_project_name)
    if not normalized:
        return

    norm_key = normalized.lower()
    if len(normalized) <= 2 or norm_key in KNOWN_COMPANY_NAMES:
        return

    for existing in _project_cache['names']:
        if existing.lower() == norm_key:
            return

    _project_cache['names'].add(normalized)
    _project_cache.setdefault('records', []).append({
        'name': normalized,
        'base_name': strip_company_prefix(normalized),
        'dompet': None,
        'company': extract_company_prefix(normalized),
    })

def calculate_similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def is_operational_keyword(text: str) -> bool:
    """
    Check if text matches any operational keyword.
    Uses word boundary matching for better accuracy.
    """
    import re
    
    if not text:
        return False
    text_lower = text.lower().strip()
    
    # Direct exact match
    if text_lower in OPERATIONAL_KEYWORDS:
        return True
    
    # Word boundary match (e.g., "bayar gaji" should match "gaji")
    for kw in OPERATIONAL_KEYWORDS:
        # Use word boundary for more reliable matching
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, text_lower):
            return True
    
    return False


def resolve_project_name(candidate, dompet_sheet=None, company=None):
    """
    Logika Matching Strict & Professional.
    
    NEW: First checks if candidate is an operational keyword.
    If so, returns status 'OPERATIONAL' for routing to Operasional Ktr.
    """
    if not candidate:
        return {'status': 'NEW', 'final_name': candidate}
    
    candidate_clean = normalize_project_input(candidate)
    candidate_lower = candidate_clean.lower()
    
    # =============== OPERATIONAL KEYWORD FILTER ===============
    # Check if this is an operational expense, not a project
    if is_operational_keyword(candidate_clean):
        return {
            'status': 'OPERATIONAL',
            'final_name': None,
            'original': candidate_clean,
            'detected_keyword': candidate_clean.lower()
        }

    if candidate_lower in PROJECT_STOPWORDS or candidate_lower in KNOWN_COMPANY_NAMES:
        return {
            'status': 'INVALID',
            'final_name': None,
            'original': candidate_clean,
            'reason': 'generic_project_keyword',
        }

    knowledge = resolve_project_knowledge(
        candidate_clean,
        dompet_sheet=dompet_sheet,
        company=company,
    )
    if knowledge:
        knowledge['final_name'] = normalize_project_input(knowledge.get('final_name') or '') or knowledge.get('final_name')
        knowledge['original'] = candidate_clean
        return knowledge
    
    scoped_records = get_existing_project_records(dompet_sheet=dompet_sheet, company=company)
    if dompet_sheet or company:
        existing_projects = [r.get('name') for r in scoped_records if r.get('name')]
    else:
        existing_projects = get_existing_projects()
    
    # Kalau nama kependekan (misal singkatan 2 huruf), anggap NEW saja biar aman
    if len(candidate_clean) < 3:
         return {'status': 'NEW', 'final_name': candidate_clean, 'original': candidate_clean}

    best_match = None
    highest_score = 0.0
    is_substring_match = False
    close_matches = set()

    # Threshold kita naikkan biar ga lebay
    AUTO_FIX_THRESHOLD = 0.92  # Typo sangat minim (Puraan -> Purana)
    AMBIGUOUS_THRESHOLD = 0.8  # Mirip banget atau Substring
    
    for existing in existing_projects:
        existing = normalize_project_input(existing)
        existing_base = strip_company_prefix(existing)
        existing_candidates = [existing]
        if existing_base and existing_base.lower() != existing.lower():
            existing_candidates.append(existing_base)

        # 1. EXACT MATCH (Case Insensitive)
        if any(e.lower() == candidate_clean.lower() for e in existing_candidates):
            return {
                'status': 'EXACT',
                'final_name': existing, 
                'original': candidate_clean
            }
            
        # 2. SUBSTRING MATCH (Kasus "Vadim Purana" vs "Purana")
        # Jika salah satu nama ada di dalam nama yang lain
        if any(
            candidate_clean.lower() in e.lower()
            or (
                e.lower() in candidate_clean.lower()
                and len(candidate_clean) < len(e) + 6
            )
            for e in existing_candidates
        ):
            # Tandai ini kandidat kuat untuk konfirmasi
            is_substring_match = True
            best_match = existing
            close_matches.add(existing)
            # Kita break loop? Belum tentu, cari yang paling mirip dulu.
            # Tapi biasanya substring match itu prioritas tinggi.
            highest_score = 0.85 # Set score manual biar masuk kategori AMBIGUOUS
            # Lanjut loop siapa tau ada exact match lain
            continue
        
        # 3. TYPO CHECK (Sequence Matcher)
        # Hanya hitung skor jika panjang string mirip (biar Prn ga match ke Purana)
        typo_target = existing_base or existing
        len_diff = abs(len(candidate_clean) - len(typo_target))
        if len_diff <= 3: # Panjang cuma beda dikit (indikasi typo)
            score = calculate_similarity(candidate_clean, typo_target)
            if score >= AMBIGUOUS_THRESHOLD:
                close_matches.add(existing)
            if score > highest_score:
                highest_score = score
                best_match = existing

    # --- DECISION LOGIC ---
    
    if highest_score >= AUTO_FIX_THRESHOLD:
        return {
            'status': 'AUTO_FIX',
            'final_name': best_match,
            'confidence': highest_score,
            'match_count': 1,
            'original': candidate_clean
        }
    elif is_substring_match and (dompet_sheet or company) and len(close_matches) == 1:
        return {
            'status': 'AUTO_FIX',
            'final_name': best_match,
            'confidence': highest_score,
            'match_count': 1,
            'original': candidate_clean
        }
    elif highest_score >= AMBIGUOUS_THRESHOLD or is_substring_match:
        # Case "Vadim Purana" vs "Purana" masuk sini
        if best_match:
            close_matches.add(best_match)
        return {
            'status': 'AMBIGUOUS',
            'final_name': best_match,
            'confidence': highest_score,
            'match_count': len(close_matches) if close_matches else 1,
            'original': candidate_clean
        }
    else:
        # Singkatan aneh-aneh (score rendah) akan masuk sini (NEW)
        return {
            'status': 'NEW',
            'final_name': candidate_clean,
            'match_count': 0,
            'original': candidate_clean
        }


def resolve_project_name_for_context(candidate, dompet_sheet=None, company=None, debt_source_dompet=None):
    """Resolve project with a guard for debt-source wallet mentions.

    Example: "pinjam dompet CV HB, projek Grand Cayman" mentions CV HB as the
    funding wallet, not necessarily the project owner. If the scoped lookup says
    NEW only because it searched inside the wrong wallet/company scope, retry
    unscoped before asking the user to create a new project.
    """
    result = resolve_project_name(candidate, dompet_sheet=dompet_sheet, company=company)
    if result.get('status') == 'NEW' and (dompet_sheet or company):
        fallback = resolve_project_name(candidate)
        if (
            fallback.get('status') in {'EXACT', 'AUTO_FIX'}
            and fallback.get('final_name')
            and int(fallback.get('match_count') or 1) == 1
        ):
            fallback['original'] = result.get('original') or candidate
            fallback['scope_fallback'] = True
            if (
                debt_source_dompet
                and dompet_sheet
                and str(dompet_sheet).strip() == str(debt_source_dompet).strip()
            ):
                fallback['debt_source_scope_fallback'] = True
            return fallback
    return result


def _normalize_text_for_project_scan(value: str) -> str:
    if not value:
        return ""
    cleaned = str(value).lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _project_scan_candidates(text_norm: str, phrase_norm: str) -> tuple:
    """Return (matched, score) for an exact/fuzzy phrase match in free text."""
    if not text_norm or not phrase_norm:
        return False, 0.0

    if re.search(rf"(?<!\w){re.escape(phrase_norm)}(?!\w)", text_norm):
        return True, 1.0

    phrase_tokens = phrase_norm.split()
    text_tokens = text_norm.split()
    if len(phrase_tokens) < 2 or len(text_tokens) < len(phrase_tokens):
        return False, 0.0

    window_size = len(phrase_tokens)
    best_score = 0.0
    for i in range(0, len(text_tokens) - window_size + 1):
        window = " ".join(text_tokens[i:i + window_size])
        score = SequenceMatcher(None, window, phrase_norm).ratio()
        if score > best_score:
            best_score = score

    return best_score >= 0.88, best_score


def infer_project_from_text_context(text, dompet_sheet=None, company=None, debt_source_dompet=None):
    """Infer an existing project by scanning the whole user text.

    This is used when model extraction produced a generic project name or no
    project at all. It intentionally only returns existing known projects.
    """
    text_norm = _normalize_text_for_project_scan(text)
    if not text_norm:
        return None

    def _match_records(records):
        matches = []
        for record in records:
            phrases = {
                _normalize_text_for_project_scan(record.get('name') or ""),
                _normalize_text_for_project_scan(record.get('base_name') or ""),
            }
            phrases = {
                p for p in phrases
                if p and len(p) >= 3 and p not in PROJECT_STOPWORDS and p not in KNOWN_COMPANY_NAMES
            }
            for phrase in phrases:
                matched, score = _project_scan_candidates(text_norm, phrase)
                if matched:
                    matches.append((score, len(phrase), record))
                    break
        return sorted(matches, key=lambda item: (item[0], item[1]), reverse=True)

    records = get_existing_project_records(dompet_sheet=dompet_sheet, company=company)
    matches = _match_records(records)

    if not matches and (dompet_sheet or company):
        matches = _match_records(get_existing_project_records())

    if not matches:
        return None

    top_score, _top_len, top_record = matches[0]
    tied = [
        record for score, length, record in matches
        if abs(score - top_score) <= 0.02 and length == _top_len
    ]
    if len({r.get('name') for r in tied}) > 1:
        return {
            'status': 'AMBIGUOUS',
            'final_name': top_record.get('name'),
            'matches': [r.get('name') for r in tied],
            'confidence': top_score,
            'match_count': len(tied),
            'source': 'text_project_scan',
        }

    return {
        'status': 'EXACT' if top_score >= 0.99 else 'AUTO_FIX',
        'final_name': top_record.get('name'),
        'dompet': top_record.get('dompet'),
        'company': top_record.get('company'),
        'confidence': top_score,
        'match_count': 1,
        'source': 'text_project_scan',
    }
def normalize_project_input(name: str) -> str:
    """Normalize a user-entered project label without changing its meaning."""
    candidate = _normalize_project_name(str(name or "").strip())
    if not candidate:
        return ""
    # Users commonly reply with "Project Hojja - X". Keep the real name and
    # let apply_company_prefix() canonicalize the company prefix later.
    return re.sub(
        r"^\s*(?:nama\s+)?(?:project|projek|proyek)\s*[:\-]?\s*",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip()
