"""
config/ - Configuration Module

Contains centralized configuration for:
- Wallet/Dompet configuration
- Sheet constants and column indices
- Budget settings
- Commands and Timeouts
- Error messages
"""

from .wallets import (
    DOMPET_SHEETS,
    DOMPET_COMPANIES,
    SELECTION_OPTIONS,
    get_dompet_for_company,
    get_selection_by_idx,
    # Legacy aliases
    COMPANY_SHEETS,
    FUND_SOURCES,
)

from .constants import (
    SHEET_HEADERS,
    COL_NO, COL_TANGGAL, COL_COMPANY, COL_KETERANGAN, COL_JUMLAH,
    COL_TIPE, COL_OLEH, COL_SOURCE, COL_KATEGORI, COL_NAMA_PROJEK, COL_MESSAGE_ID,
    DASHBOARD_SHEET_NAME, META_SHEET_NAME, SYSTEM_SHEETS,
    DEFAULT_BUDGET, BUDGET_WARNING_PERCENT,
    # New exports
    Timeouts,
    Commands,
    GROUP_TRIGGERS,
)

from .errors import (
    UserErrors,
    InternalErrors,
)

