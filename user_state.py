"""
user_state.py - User State Management v2.1 (Simplified)

Simplified version - no longer tracks active project.
Kept for potential future use (user preferences, settings).

NOTE: The complex project tracking is removed.
      Now uses fixed categories auto-detected by AI.
"""

import os
import json
from datetime import datetime
from typing import Optional, Dict

STATE_FILE = os.path.join(os.path.dirname(__file__), 'user_state.json')


def _load_state() -> Dict:
    """Load state from JSON file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_state(state: Dict) -> None:
    """Save state to JSON file."""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_user_state(user_id: str) -> Optional[Dict]:
    """Get user state."""
    state = _load_state()
    return state.get(str(user_id))


def update_user_activity(user_id: str, user_name: str = None) -> None:
    """Update user's last activity timestamp."""
    state = _load_state()
    user_id = str(user_id)
    
    if user_id not in state:
        state[user_id] = {}
    
    state[user_id]['last_active'] = datetime.now().isoformat()
    
    if user_name:
        state[user_id]['name'] = user_name
    
    _save_state(state)


def get_all_users() -> Dict:
    """Get all user states."""
    return _load_state()


if __name__ == '__main__':
    print("User state module v2.1 (simplified)")
    print(f"State file: {STATE_FILE}")
