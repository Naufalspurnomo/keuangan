import time
import logging
from difflib import SequenceMatcher
from sheets_helper import get_sheet
from config.constants import COL_NAMA_PROJEK, KNOWN_COMPANY_NAMES, OPERATIONAL_KEYWORDS

_project_cache = {
    'names': set(),
    'last_updated': 0,
    'ttl': 300
}

from config.wallets import DOMPET_SHEETS
from config.constants import SPLIT_LAYOUT_DATA_START
import re


def _normalize_project_name(name: str) -> str:
    """Normalize project names for consistent cache matching."""
    if not name:
        return ""
    cleaned = str(name).strip()
    cleaned = re.sub(r'\s*\((Start|Finish)\)$', '', cleaned, flags=re.IGNORECASE)
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
            
            # Iterate all real sheets
            for sheet_name in DOMPET_SHEETS:
                sh = get_sheet(sheet_name)
                if not sh: continue
                
                # Get Column N (Project in Pengeluaran) - Index 14
                # And maybe Column E (Project in Pemasukan) - Index 5
                
                # Optimization: Read all values and filter in memory
                try:
                    # Get values starting from Row 9
                    # Assuming max 2000 rows to be safe/fast
                    # We grab Col E and Col N
                    # Col E = 5, Col N = 14
                    
                    # Reading Col N (Pengeluaran Project)
                    col_n = sh.col_values(14)[SPLIT_LAYOUT_DATA_START-1:]
                    for p in col_n:
                        if p.strip(): all_projects.add(p.strip())
                        
                    # Reading Col E (Pemasukan Project)
                    col_e = sh.col_values(5)[SPLIT_LAYOUT_DATA_START-1:]
                    for p in col_e:
                        if p.strip(): all_projects.add(p.strip())

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
            _project_cache['last_updated'] = now
            logging.info(f"[ProjectService] Loaded {len(clean_projects)} projects from Sheets")
            
        except Exception as e:
            logging.error(f"[ProjectService] Failed: {e}")
            
    return _project_cache['names']

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


def resolve_project_name(candidate):
    """
    Logika Matching Strict & Professional.
    
    NEW: First checks if candidate is an operational keyword.
    If so, returns status 'OPERATIONAL' for routing to Operasional Ktr.
    """
    if not candidate:
        return {'status': 'NEW', 'final_name': candidate}
    
    candidate_clean = candidate.strip()
    
    # =============== OPERATIONAL KEYWORD FILTER ===============
    # Check if this is an operational expense, not a project
    if is_operational_keyword(candidate_clean):
        return {
            'status': 'OPERATIONAL',
            'final_name': None,
            'original': candidate_clean,
            'detected_keyword': candidate_clean.lower()
        }
    
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
        # 1. EXACT MATCH (Case Insensitive)
        if existing.lower() == candidate_clean.lower():
            return {
                'status': 'EXACT',
                'final_name': existing, 
                'original': candidate_clean
            }
            
        # 2. SUBSTRING MATCH (Kasus "Vadim Purana" vs "Purana")
        # Jika salah satu nama ada di dalam nama yang lain
        if candidate_clean.lower() in existing.lower() or existing.lower() in candidate_clean.lower():
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
        len_diff = abs(len(candidate_clean) - len(existing))
        if len_diff <= 3: # Panjang cuma beda dikit (indikasi typo)
            score = calculate_similarity(candidate_clean, existing)
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
