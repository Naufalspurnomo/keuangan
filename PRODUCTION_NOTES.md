# Production Update Notes - Bot Keuangan

## Summary of Changes (2026-01-20)

### 1. Critical Fixes
- **Resolve `NameError` Crash**: Fixed the `NameError: name 'build_selection_prompt' is not defined` crash in WuzAPI handler by replacing deprecated function calls with `fmt.prompt_company` from `messages.py`.
- **Unified Transaction Storage**: Standardized `append_transactions` calls across all handlers to ensure `dompet` and `company` are always correctly passed.

### 2. Architecture Cleanup
- **Removed Fonnte Support**: Completely removed all code related to the legacy Fonnte integration (`/webhook`, `send_whatsapp_reply`). The bot now exclusively supports WuzAPI and Telegram.
- **Centralized Messaging**: Completed the migration to `messages.py` as the Single Source of Truth for all bot responses. Obsolete constants (`START_MESSAGE`, etc.) and wrapper functions in `main.py` have been removed.

### 3. Security & Safety
- **Telegram Plain Text**: Updated Telegram handlers to send messages as plain text (with Markdown stripping) by default. This prevents crashes caused by unescaped user input (e.g., project names with special characters) violating Telegram's Markdown parsing rules.
- **Pending Cleanup**: Implemented automatic cleanup of "pending" transactions (`PENDING_TTL_SECONDS = 3600`) to prevent memory leaks from abandoned sessions.

### 4. Improvements
- **Robust Parsing**: Enhanced `process_selection` to handle non-digit characters (e.g., "1.") and `parse_revision_amount` to handle currency prefixes ("Rp", "IDR").
- **Group UX**: Improved group chat handling by properly passing `mention` references in success and prompt messages.

## Next Steps for User
1. **Restart the Bot**: A full restart is required for these changes to take effect and to clear any old in-memory states.
2. **Verify Telegram**: Check if Telegram bot responds correctly to commands like `/start` and processes transactions without Markdown errors.
3. **Verify WuzAPI**: Test the "Selection Flow" (sending a transaction without a clear company) to ensure the prompt now appears correctly without error.
