"""Business-logic services with side-effect-free package initialization."""

from __future__ import annotations


_STATE_MANAGER_EXPORTS = {
    "get_pending_transactions",
    "set_pending_transaction",
    "clear_pending_transaction",
    "is_message_duplicate",
    "store_bot_message_ref",
    "get_original_message_id",
    "find_pending_by_bot_msg",
    "find_pending_for_user",
    "pending_key",
}

__all__ = sorted(_STATE_MANAGER_EXPORTS)


def __getattr__(name: str):
    if name in _STATE_MANAGER_EXPORTS:
        from . import state_manager

        return getattr(state_manager, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
