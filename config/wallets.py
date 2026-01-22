"""
wallets.py - Wallet/Dompet Configuration

Contains:
- DOMPET_SHEETS: List of physical wallet sheet names  
- DOMPET_COMPANIES: Mapping of dompet to companies
- SELECTION_OPTIONS: Flat 1-5 selection options for chat interface
- Helper functions for wallet/company lookups
"""

from typing import Dict, List, Optional

# Sheet configuration - Dompet sheets (3 main dompet sheets)
DOMPET_SHEETS = [
    "Dompet Holja",
    "Dompet Texturin Sby",
    "Dompet Evan"
]

# Dompet -> Companies mapping
DOMPET_COMPANIES = {
    "Dompet Holja": ["HOLLA", "HOJJA", "Dompet Holja"],
    "Dompet Texturin Sby": ["TEXTURIN-Surabaya", "Dompet Texturin Sby"],
    "Dompet Evan": ["TEXTURIN-Bali", "KANTOR", "Dompet Evan"]
}

# Flat selection options for 1-5 display
SELECTION_OPTIONS = [
    {"idx": 1, "dompet": "Dompet Holja", "company": "HOLLA"},
    {"idx": 2, "dompet": "Dompet Holja", "company": "HOJJA"},
    {"idx": 3, "dompet": "Dompet Texturin Sby", "company": "TEXTURIN-Surabaya"},
    {"idx": 4, "dompet": "Dompet Evan", "company": "TEXTURIN-Bali"},
    {"idx": 5, "dompet": "Dompet Evan", "company": "KANTOR"},
]

# Legacy aliases for backward compatibility
COMPANY_SHEETS = DOMPET_SHEETS
FUND_SOURCES = DOMPET_COMPANIES


def get_dompet_for_company(company_name: str) -> str:
    """Get the dompet (wallet) for a given company."""
    for dompet, companies in DOMPET_COMPANIES.items():
        if company_name in companies:
            return dompet
    return "Dompet Holja"  # Fallback


def get_selection_by_idx(idx: int) -> Optional[Dict]:
    """Get selection option by 1-based index."""
    for opt in SELECTION_OPTIONS:
        if opt["idx"] == idx:
            return opt
    return None


def get_available_dompets() -> List[str]:
    """Get list of available dompet sheets."""
    return DOMPET_SHEETS.copy()


# For testing
if __name__ == '__main__':
    print("Wallet Configuration Test")
    print(f"Dompets: {DOMPET_SHEETS}")
    print(f"Companies for Dompet Holja: {DOMPET_COMPANIES['Dompet Holja']}")
    print(f"Selection 3: {get_selection_by_idx(3)}")
    print(f"Dompet for HOJJA: {get_dompet_for_company('HOJJA')}")
