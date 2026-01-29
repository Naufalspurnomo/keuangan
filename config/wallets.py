"""
wallets.py - Wallet/Dompet Configuration (Cost Accounting v2)

Contains:
- DOMPET_SHEETS: List of Split Layout dompet sheet names  
- DOMPET_ALIASES: User input aliases for dompet names
- SELECTION_OPTIONS: Selection options for chat interface
- Helper functions for wallet/dompet lookups
"""

from typing import Dict, List, Optional

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
    # CV HB (101)
    "cv hb": "CV HB (101)",
    "cvhb": "CV HB (101)",
    "101": "CV HB (101)",
    "holja": "CV HB (101)",
    "holla": "CV HB (101)",
    "dompet holja": "CV HB (101)",
    "dompet holla": "CV HB (101)",
    
    # TX SBY (216)
    "tx sby": "TX SBY(216)",
    "txsby": "TX SBY(216)",
    "216": "TX SBY(216)",
    "texturin sby": "TX SBY(216)",
    "texturin surabaya": "TX SBY(216)",
    "dompet texturin sby": "TX SBY(216)",
    "surabaya": "TX SBY(216)",
    "sby": "TX SBY(216)",
    
    # TX BALI (087)
    "tx bali": "TX BALI(087)",
    "txbali": "TX BALI(087)", 
    "087": "TX BALI(087)",
    "texturin bali": "TX BALI(087)",
    "dompet bali": "TX BALI(087)",
    "dompet evan": "TX BALI(087)",
    "evan": "TX BALI(087)",
    "bali": "TX BALI(087)",
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

# Project company selection (4 options - for project transactions)
# KANTOR expenses go to Operasional sheet, not here
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


def get_dompet_for_company(company_name: str) -> str:
    """Get the dompet (wallet) sheet name for a given company."""
    for dompet, companies in DOMPET_COMPANIES.items():
        if company_name in companies:
            return dompet
    return "CV HB (101)"  # Fallback


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
    lines.append("↩️ Balas angka 1-3")
    return "\n".join(lines)


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
