"""
wallets.py - Wallet/Dompet Configuration (Cost Accounting v2)

Contains:
- DOMPET_SHEETS: List of Split Layout dompet sheet names  
- DOMPET_ALIASES: User input aliases for dompet names
- SELECTION_OPTIONS: Selection options for chat interface
- Helper functions for wallet/dompet lookups
"""

from typing import Dict, List, Optional
import re

# ===================== DOMPET SHEETS (Split Layout) =====================
# These are the actual sheet names in Google Sheets
DOMPET_SHEETS = [
    "CV HB (101)",
    "TX SBY(216)",
    "TX BALI(087)"
]

# Short names for display and reference
DOMPET_SHORT_NAMES = {
    "CV HB (101)": "CV HB",
    "TX SBY(216)": "TX SBY",
    "TX BALI(087)": "TX BALI"
}

# Aliases: user input -> canonical sheet name
# Lowercase for matching
DOMPET_ALIASES = {
    # ==========================================
    # CV HB (101) - Holja/Holla Variants
    # ==========================================
    # Standard names
    "cv hb": "CV HB (101)",
    "cvhb": "CV HB (101)",
    "cv-hb": "CV HB (101)",
    "cv.hb": "CV HB (101)",
    "cv hb 101": "CV HB (101)",
    
    # Rekening number
    "101": "CV HB (101)",
    "rek 101": "CV HB (101)",
    "rekening 101": "CV HB (101)",
    "no 101": "CV HB (101)",
    
    # Holja variants (original spelling)
    "holja": "CV HB (101)",
    "hollja": "CV HB (101)",
    "hojja": "CV HB (101)",  # Common typo
    "holjawall": "CV HB (101)",
    "dompet holja": "CV HB (101)",
    "dompet holjawall": "CV HB (101)",
    
    # Holla variants (alternative spelling)
    "holla": "CV HB (101)",
    "hollawall": "CV HB (101)",
    "dompet holla": "CV HB (101)",
    "dompet hollawall": "CV HB (101)",
    
    # Casual mentions
    "hb": "CV HB (101)",
    "cv": "CV HB (101)",
    "dompet cv": "CV HB (101)",
    "dompet hb": "CV HB (101)",
    
    # With spaces/typos
    "hol ja": "CV HB (101)",
    "hol la": "CV HB (101)",
    "ho lja": "CV HB (101)",
    
    # ==========================================
    # TX SBY (216) - Surabaya Variants
    # ==========================================
    # Standard names
    "tx sby": "TX SBY(216)",
    "txsby": "TX SBY(216)",
    "tx-sby": "TX SBY(216)",
    "tx.sby": "TX SBY(216)",
    "tx sby 216": "TX SBY(216)",
    
    # Rekening number
    "216": "TX SBY(216)",
    "rek 216": "TX SBY(216)",
    "rekening 216": "TX SBY(216)",
    "no 216": "TX SBY(216)",
    
    # Texturin variants
    "texturin": "TX SBY(216)",  # Default to SBY when ambiguous
    "texturin sby": "TX SBY(216)",
    "texturin surabaya": "TX SBY(216)",
    "dompet texturin": "TX SBY(216)",
    "dompet texturin sby": "TX SBY(216)",
    "dompet texturin surabaya": "TX SBY(216)",
    
    # Location variants
    "surabaya": "TX SBY(216)",
    "sby": "TX SBY(216)",
    "suraba": "TX SBY(216)",  # Typo
    "surbaya": "TX SBY(216)",  # Typo
    "dompet surabaya": "TX SBY(216)",
    "dompet sby": "TX SBY(216)",
    
    # Casual mentions
    "tx": "TX SBY(216)",  # When only "tx" mentioned, default to SBY (more common)
    "dompet tx": "TX SBY(216)",
    
    # With spaces/typos
    "tx s by": "TX SBY(216)",
    "tx sb y": "TX SBY(216)",
    
    # ==========================================
    # TX BALI (087) - Bali Variants
    # ==========================================
    # Standard names
    "tx bali": "TX BALI(087)",
    "txbali": "TX BALI(087)",
    "tx-bali": "TX BALI(087)",
    "tx.bali": "TX BALI(087)",
    "tx bali 087": "TX BALI(087)",
    
    # Rekening number
    "087": "TX BALI(087)",
    "rek 087": "TX BALI(087)",
    "rekening 087": "TX BALI(087)",
    "no 087": "TX BALI(087)",
    "87": "TX BALI(087)",  # Without leading zero
    
    # Texturin Bali variants
    "texturin bali": "TX BALI(087)",
    "dompet texturin bali": "TX BALI(087)",
    
    # Location variants
    "bali": "TX BALI(087)",
    "denpasar": "TX BALI(087)",
    "dompet bali": "TX BALI(087)",
    
    # Person-based (Evan handles Bali)
    "evan": "TX BALI(087)",
    "dompet evan": "TX BALI(087)",
    "evan punya": "TX BALI(087)",
    "punya evan": "TX BALI(087)",
    
    # Casual mentions
    "bali aja": "TX BALI(087)",
    "ke bali": "TX BALI(087)",
    
    # ==========================================
    # Common Typos & Abbreviations
    # ==========================================
    # Number typos
    "1o1": "CV HB (101)",  # o instead of 0
    "1O1": "CV HB (101)",
    "21e": "TX SBY(216)",  # e instead of 6
    "o87": "TX BALI(087)",  # o instead of 0
    "O87": "TX BALI(087)",
    
    # Indonesian spelling variants
    "hojah": "CV HB (101)",
    "hollah": "CV HB (101)",
    "texturein": "TX SBY(216)",  # Common typo
    "textureen": "TX SBY(216)",
    
    # Shortened versions
    "sb": "TX SBY(216)",  # Very casual
    "bl": "TX BALI(087)",  # Very casual
    
    # ==========================================
    # SPECIAL: Company Selection (1-4)
    # ==========================================
    # When user says company numbers instead of dompet
    # (These map to company selection, not direct dompet)
    "company 1": "CV HB (101)",  # HOLLA
    "company 2": "CV HB (101)",  # HOJJA (same dompet)
    "company 3": "TX SBY(216)",  # TEXTURIN-Surabaya
    "company 4": "TX BALI(087)",  # TEXTURIN-Bali
    
    # ==========================================
    # CONTEXT-AWARE: Project/Company Names
    # ==========================================
    # These should be checked if mentioned WITH transaction
    "holla project": "CV HB (101)",
    "hojja project": "CV HB (101)",
    "projek holla": "CV HB (101)",
    "projek hojja": "CV HB (101)",
    
    "texturin sby project": "TX SBY(216)",
    "projek texturin": "TX SBY(216)",
    
    "texturin bali project": "TX BALI(087)",
    "projek bali": "TX BALI(087)",
}

# Company -> Dompet mapping (for backward compatibility)
# NOTE: KANTOR is NOT a company - it's operational expense category
DOMPET_COMPANIES = {
    "CV HB (101)": ["HOLLA", "HOJJA", "CV HB"],
    "TX SBY(216)": ["TEXTURIN-Surabaya", "TX SBY"],
    "TX BALI(087)": ["TEXTURIN-Bali", "TX BALI"]
}

# Flat selection options for 1-3 display in operational mode
WALLET_SELECTION_OPTIONS = [
    {"idx": 1, "dompet": "CV HB (101)", "short": "CV HB", "display": "1. CV HB (101)"},
    {"idx": 2, "dompet": "TX SBY(216)", "short": "TX SBY", "display": "2. TX SBY (216)"},
    {"idx": 3, "dompet": "TX BALI(087)", "short": "TX BALI", "display": "3. TX BALI (087)"},
]

# Project company/wallet selection (4 options - matching prompt)
SELECTION_OPTIONS = [
    {"idx": 1, "dompet": "CV HB (101)", "company": "HOLLA"},
    {"idx": 2, "dompet": "CV HB (101)", "company": "HOJJA"},
    {"idx": 3, "dompet": "TX SBY(216)", "company": "TEXTURIN-Surabaya"},
    {"idx": 4, "dompet": "TX BALI(087)", "company": "TEXTURIN-Bali"},
]

# Legacy aliases for backward compatibility
COMPANY_SHEETS = DOMPET_SHEETS
FUND_SOURCES = DOMPET_COMPANIES


# ===================== HELPER FUNCTIONS =====================

def resolve_dompet_name(user_input: str) -> Optional[str]:
    """
    Resolve user input to canonical dompet sheet name.
    Returns None if not found.
    """
    if not user_input:
        return None
    clean = user_input.lower().strip()
    return DOMPET_ALIASES.get(clean)


def resolve_dompet_from_text(text: str) -> Optional[str]:
    """
    Resolve dompet name from a longer text (substring match).
    Prioritizes more specific aliases to avoid partial collisions
    like "dompet tx" vs "tx bali".
    """
    if not text:
        return None
    clean = text.lower()

    # Detect dompet by account prefix (e.g., "216-073-7991")
    prefix_map = {
        "101": "CV HB (101)",
        "216": "TX SBY(216)",
        "087": "TX BALI(087)",
    }
    m = re.search(r"\b(101|216|087)\s*[-–]\s*\d{3,}\b", clean)
    if not m:
        m = re.search(
            r"\b(?:rekening|rek|virtual|va|account|rekening tujuan|no\.?\s*rekening)\b[^0-9]{0,10}(101|216|087)\b",
            clean
        )
    if m:
        return prefix_map.get(m.group(1))

    candidates = []
    for alias, dompet in DOMPET_ALIASES.items():
        if alias in clean:
            candidates.append((alias, dompet))

    if not candidates:
        return None

    generic_tokens = {"dompet", "wallet", "dompetnya", "dompetku"}
    location_tokens = {"bali", "sby", "surabaya", "denpasar"}

    def _alias_score(alias: str) -> tuple:
        # Remove generic tokens to measure specificity
        norm = alias
        for token in generic_tokens:
            norm = re.sub(rf"\b{token}\b", "", norm)
        norm = " ".join(norm.split())

        score = len(norm)
        if any(loc in norm for loc in location_tokens):
            score += 5
        return (score, len(alias))

    best_alias, best_dompet = max(candidates, key=lambda item: _alias_score(item[0]))
    return best_dompet


def get_dompet_for_company(company_name: str) -> str:
    """Get the dompet (wallet) sheet name for a given company."""
    for dompet, companies in DOMPET_COMPANIES.items():
        if company_name in companies:
            return dompet
    return "CV HB (101)"  # Fallback


def get_company_name_from_sheet(dompet_sheet: str) -> str:
    """Get default company name for a dompet sheet."""
    companies = DOMPET_COMPANIES.get(dompet_sheet)
    if companies:
        return companies[0]
    return "UMUM"


def get_selection_by_idx(idx: int) -> Optional[Dict]:
    """Get selection option by 1-based index (from SELECTION_OPTIONS)."""
    for opt in SELECTION_OPTIONS:
        if opt["idx"] == idx:
            return opt
    return None


def get_wallet_selection_by_idx(idx: int) -> Optional[Dict]:
    """Get wallet selection by 1-based index (from WALLET_SELECTION_OPTIONS)."""
    for opt in WALLET_SELECTION_OPTIONS:
        if opt["idx"] == idx:
            return opt
    return None


def get_available_dompets() -> List[str]:
    """Get list of available dompet sheets."""
    return DOMPET_SHEETS.copy()


def get_dompet_short_name(full_name: str) -> str:
    """Get short display name for dompet."""
    return DOMPET_SHORT_NAMES.get(full_name, full_name)


def format_wallet_selection_prompt() -> str:
    """Format wallet selection prompt for operational transactions."""
    lines = ["💼 Uang ini diambil dari dompet mana?", ""]
    for opt in WALLET_SELECTION_OPTIONS:
        lines.append(opt["display"])
    lines.append("")
    lines.append("4. Ini ternyata Project")
    lines.append("")
    lines.append("↩️ Balas angka 1-4")
    return "\n".join(lines)


PROJECT_PREFIX_DOMPETS = {"CV HB (101)"}
PROJECT_PREFIX_COMPANIES = {"HOLLA", "HOJJA"}
PROJECT_PREFIX_EXCLUDE = {"operasional kantor", "saldo umum", "umum", "unknown"}


def extract_company_prefix(project_name: str) -> Optional[str]:
    """Return HOLLA/HOJJA if project name starts with a company prefix."""
    if not project_name:
        return None
    match = re.match(r"^\s*(HOLLA|HOJJA)\s*[-:]\s*", project_name, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def strip_company_prefix(project_name: str) -> str:
    """Remove HOLLA/HOJJA prefix from project name if present."""
    if not project_name:
        return project_name
    return re.sub(r"^\s*(HOLLA|HOJJA)\s*[-:]\s*", "", project_name, flags=re.IGNORECASE).strip()


def apply_company_prefix(project_name: str, dompet_sheet: str, company: str) -> str:
    """
    Add HOLLA/HOJJA prefix for CV HB projects, if not already prefixed.
    Keeps the original name if prefix is already present.
    """
    if not project_name:
        return project_name
    if dompet_sheet not in PROJECT_PREFIX_DOMPETS:
        return project_name
    if not company:
        return project_name
    company_clean = str(company).strip().upper()
    if company_clean not in PROJECT_PREFIX_COMPANIES:
        return project_name
    if project_name.strip().lower() in PROJECT_PREFIX_EXCLUDE:
        return project_name
    if extract_company_prefix(project_name):
        return project_name
    return f"{company_clean} - {project_name.strip()}"


# For testing
if __name__ == '__main__':
    print("Wallet Configuration Test (v2 - Cost Accounting)")
    print(f"Dompets: {DOMPET_SHEETS}")
    print(f"Resolve 'holja': {resolve_dompet_name('holja')}")
    print(f"Resolve 'tx sby': {resolve_dompet_name('tx sby')}")
    print(f"Resolve 'bali': {resolve_dompet_name('bali')}")
    print(f"Selection 3: {get_selection_by_idx(3)}")
    print(f"Wallet Selection 2: {get_wallet_selection_by_idx(2)}")
    print(f"\nWallet Selection Prompt:\n{format_wallet_selection_prompt()}")
