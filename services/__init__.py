"""
services/ - Business Logic Services

Contains:
- state_manager.py: Pending transactions and message deduplication
- transaction_service.py: Transaction processing and saving
"""

from .state_manager import (
    get_pending_transactions,
    set_pending_transaction,
    clear_pending_transaction,
    is_message_duplicate,
    store_bot_message_ref,
    get_original_message_id,
    find_pending_by_bot_msg,
    find_pending_for_user,
    pending_key,
)
