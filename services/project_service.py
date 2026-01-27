import time
import logging
from difflib import SequenceMatcher
from sheets_helper import get_sheet
from config.constants import COL_NAMA_PROJEK, KNOWN_COMPANY_NAMES

_project_cache = {
    'names': set(),
    'last_updated': 0,
    'ttl': 300
}

def get_existing_projects(force_refresh=False):
    """Ambil list projek unik dari Sheet."""
    global _project_cache
    now = time.time()
    
    if force_refresh or (now - _project_cache['last_updated'] > _project_cache['ttl']):
        try:
            sh = get_sheet("Data_Agregat") 
            if sh:
                # Ambil kolom nama projek
                raw_values = sh.col_values(COL_NAMA_PROJEK)[1:] 
                
                clean_projects = set()
                for val in raw_values:
                    v = val.strip()
                    # Filter nama yang terlalu pendek (misal "-" atau "A")
                    if v and len(v) > 2 and v.lower() not in KNOWN_COMPANY_NAMES:
                        clean_projects.add(v)
                
                _project_cache['names'] = clean_projects
                _project_cache['last_updated'] = now
        except Exception as e:
            logging.error(f"[ProjectService] Failed: {e}")
            
    return _project_cache['names']

def add_new_project_to_cache(new_project_name):
    if new_project_name:
        _project_cache['names'].add(new_project_name)

def calculate_similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def resolve_project_name(candidate):
    """
    Logika Matching Strict & Professional.
    Hanya menangani Exact Match, Typo Ringan, dan Substring (Vadim Purana vs Purana).
    """
    if not candidate:
        return {'status': 'NEW', 'final_name': candidate}
        
    candidate_clean = candidate.strip()
    existing_projects = get_existing_projects()
    
    # Kalau nama kependekan (misal singkatan 2 huruf), anggap NEW saja biar aman
    # Kecuali klien emang punya projek nama "XY"
    if len(candidate_clean) < 3:
         return {'status': 'NEW', 'final_name': candidate_clean, 'original': candidate_clean}

    best_match = None
    highest_score = 0.0
    is_substring_match = False
    
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
            if score > highest_score:
                highest_score = score
                best_match = existing

    # --- DECISION LOGIC ---

    # Threshold kita naikkan biar ga lebay
    AUTO_FIX_THRESHOLD = 0.92  # Typo sangat minim (Puraan -> Purana)
    AMBIGUOUS_THRESHOLD = 0.8  # Mirip banget atau Substring
    
    if highest_score >= AUTO_FIX_THRESHOLD:
        return {
            'status': 'AUTO_FIX',
            'final_name': best_match,
            'confidence': highest_score,
            'original': candidate_clean
        }
    elif highest_score >= AMBIGUOUS_THRESHOLD or is_substring_match:
        # Case "Vadim Purana" vs "Purana" masuk sini
        return {
            'status': 'AMBIGUOUS',
            'final_name': best_match,
            'confidence': highest_score,
            'original': candidate_clean
        }
    else:
        # Singkatan aneh-aneh (score rendah) akan masuk sini (NEW)
        return {
            'status': 'NEW',
            'final_name': candidate_clean,
            'original': candidate_clean
        }