"""
parsers.py - Input Parsing Utilities

Contains:
- parse_selection: Parse 1-5 company selection
- parse_revision_amount: Parse amount for revision
- should_respond_in_group: Check if bot should respond in group
- pending_key: Generate unique pending transaction key
- pending_is_expired: Check if pending transaction expired
"""

import re
from datetime import datetime

from config.constants import Timeouts, GROUP_TRIGGERS

# Use centralized timeouts
PENDING_TTL_SECONDS = Timeouts.PENDING_TRANSACTION


def pending_key(sender_number: str, chat_jid: str) -> str:
    """Generate unique key for pending transactions per chat."""
    # For DM, chat_jid might be same as sender, that's fine
    return chat_jid or sender_number


def pending_is_expired(pending: dict) -> bool:
    """Check if pending transaction has expired (TTL exceeded)."""
    created = pending.get("created_at")
    if created is None:
        return False
    return (datetime.now() - created).total_seconds() > PENDING_TTL_SECONDS


def should_respond_in_group(message: str, is_group: bool) -> tuple:
    """
    Check if bot should respond to this message in group chat.
    
    In group chats, ONLY respond to:
    1. Messages starting with "/" (slash commands)
    2. Messages with GROUP_TRIGGERS prefix (+catat, +bot, etc.)
    
    Returns:
        (should_respond: bool, cleaned_message: str)
    """
    if not is_group:
        return True, message  # Private chat always responds
    
    message_lower = message.lower().strip()
    
    # Check for group triggers (+catat, +bot, +input, /catat)
    for trigger in GROUP_TRIGGERS:
        if message_lower.startswith(trigger.lower()):
            # Remove trigger and return cleaned message
            cleaned = message[len(trigger):].strip()
            return True, cleaned
    
    # ONLY respond to "/" commands in groups (avoid spam from casual chat)
    if message_lower.startswith('/'):
        return True, message
    
    return False, ""  # Group chat without trigger or slash - ignore


def is_command_match(text: str, command_list: list, is_group: bool = False) -> bool:
    """
    Check if text matches any command in the list, respecting group chat rules.
    
    Args:
        text: The message text (lowercase)
        command_list: List of command aliases (e.g., Commands.STATUS)
        is_group: If True, only match slash commands
        
    Returns:
        True if text matches a valid command for the context
    """
    text = text.lower().strip()
    
    if is_group:
        # In groups, only match commands starting with "/"
        for cmd in command_list:
            if cmd.startswith('/') and text == cmd:
                return True
        return False
    else:
        # In private chat, match any alias
        return text in command_list


def is_prefix_match(text: str, prefix_list: list, is_group: bool = False) -> bool:
    """
    Check if text starts with any prefix in the list, respecting group chat rules.
    
    Args:
        text: The message text (lowercase)
        prefix_list: List of prefixes (e.g., Commands.TANYA_PREFIXES)
        is_group: If True, only match slash prefixes
        
    Returns:
        True if text starts with a valid prefix for the context
    """
    text = text.lower().strip()
    
    if is_group:
        # In groups, only match prefixes starting with "/"
        for prefix in prefix_list:
            if prefix.startswith('/') and text.startswith(prefix):
                return True
        return False
    else:
        # In private chat, match any prefix
        for prefix in prefix_list:
            if text.startswith(prefix):
                return True
        return False



def parse_selection(text: str) -> tuple:
    """
    Parse user selection input (1-5).
    
    Returns:
        (is_valid: bool, selection: int, error_message: str)
    """
    text = text.strip()
    
    # Check for cancel
    if text.lower() in ['/cancel', 'batal', 'cancel']:
        return False, 0, "cancel"
    
    # Check for multi-selection (not allowed)
    if ',' in text or ' ' in text.strip():
        return False, 0, "Pilih satu saja. Ketik angka 1-5."
    
    # Try to parse as number
    try:
        num = int(text)
        if 1 <= num <= 5:
            return True, num, ""
        else:
            return False, 0, "Pilihan tidak tersedia. Ketik angka 1-5."
    except ValueError:
        return False, 0, "Balas dengan angka 1-5 untuk memilih."


def parse_revision_amount(text: str) -> int:
    """
    Parse amount from revision text.
    Supports: "/revisi 150rb", "150000", "150rb", "1.5jt", "2 juta", etc.
    
    Returns:
        Amount in Rupiah, or 0 if not parseable
    """
    # Clean the text
    text = text.lower().strip()
    
    # Remove /revisi or revisi prefix
    text = re.sub(r'^[/]?(revisi|ubah|ganti|koreksi|edit)\s*', '', text).strip()
    
    # Handle "2 juta", "500 rb", "1.5jt" - number followed by optional space and suffix
    match = re.match(r'^([\d]+(?:[.,]\d+)?)\s*(rb|ribu|k|jt|juta)?$', text)
    if match:
        num_str = match.group(1)
        suffix = match.group(2) or ''
        
        # Replace comma with dot for decimal (Indonesian uses comma as decimal)
        num_str = num_str.replace(',', '.')
        
        try:
            num = float(num_str)
        except ValueError:
            return 0
        
        if suffix in ['rb', 'ribu', 'k']:
            return int(num * 1000)
        elif suffix in ['jt', 'juta']:
            return int(num * 1000000)
        else:
            # No suffix - if it has decimal, it's probably already in full amount
            return int(num)
    
    # Try direct number (just digits after cleaning)
    cleaned = text.replace('.', '').replace(',', '').replace(' ', '')
    try:
        return int(cleaned)
    except ValueError:
        return 0


# For testing
if __name__ == '__main__':
    print("Parser Tests")
    print(f"parse_selection('3'): {parse_selection('3')}")
    print(f"parse_selection('cancel'): {parse_selection('cancel')}")
    print(f"parse_revision_amount('150rb'): {parse_revision_amount('150rb')}")
    print(f"parse_revision_amount('1.5jt'): {parse_revision_amount('1.5jt')}")
    print(f"should_respond_in_group('+catat beli', True): {should_respond_in_group('+catat beli', True)}")
