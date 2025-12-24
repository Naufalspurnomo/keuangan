"""
reminder.py - Smart Reminder Module

Features:
- Track user last activity
- Send reminder if no transaction for X days
- Budget warning notifications
- Scheduled checks (run periodically)

SECURITY: No sensitive data in notifications
"""

import os
import json
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import requests
from dotenv import load_dotenv

load_dotenv()

# Import modules
from sheets_helper import get_all_data, check_budget_alert, get_summary
from security import secure_log, sanitize_input

# Configuration
FONNTE_TOKEN = os.getenv('FONNTE_TOKEN')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Reminder settings
REMINDER_INACTIVE_DAYS = 3  # Remind if no transaction for 3 days
REMINDER_CHECK_INTERVAL = 3600 * 6  # Check every 6 hours
USER_DATA_FILE = os.path.join(os.path.dirname(__file__), 'user_activity.json')

# Store scheduler thread
_scheduler_thread = None
_scheduler_running = False


# ===================== USER ACTIVITY TRACKING =====================

def _load_user_activity() -> Dict:
    """Load user activity data."""
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_user_activity(data: Dict) -> None:
    """Save user activity data."""
    try:
        with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        secure_log("ERROR", f"Failed to save user activity: {type(e).__name__}")


def update_user_activity(user_id: str, platform: str, user_name: str = None) -> None:
    """
    Update user's last activity timestamp.
    Call this when user sends a transaction.
    """
    data = _load_user_activity()
    user_id = str(user_id)
    
    now = datetime.now().isoformat()
    
    if user_id not in data:
        data[user_id] = {
            'platform': platform,
            'name': user_name or 'User',
            'first_seen': now,
            'last_transaction': now,
            'last_reminder': None,
            'reminder_enabled': True
        }
    else:
        data[user_id]['last_transaction'] = now
        if user_name:
            data[user_id]['name'] = user_name
    
    _save_user_activity(data)
    secure_log("INFO", f"User activity updated: {platform}")


def get_inactive_users(days: int = REMINDER_INACTIVE_DAYS) -> List[Dict]:
    """Get users who haven't made transactions for X days."""
    data = _load_user_activity()
    inactive = []
    
    cutoff = datetime.now() - timedelta(days=days)
    
    for user_id, info in data.items():
        if not info.get('reminder_enabled', True):
            continue
        
        last_tx = info.get('last_transaction')
        if not last_tx:
            continue
        
        try:
            last_tx_date = datetime.fromisoformat(last_tx)
        except ValueError:
            continue
        
        # Check if inactive
        if last_tx_date < cutoff:
            # Check if we already sent reminder recently (within 24 hours)
            last_reminder = info.get('last_reminder')
            if last_reminder:
                try:
                    last_reminder_date = datetime.fromisoformat(last_reminder)
                    if datetime.now() - last_reminder_date < timedelta(hours=24):
                        continue  # Skip, already reminded today
                except ValueError:
                    pass
            
            inactive.append({
                'user_id': user_id,
                'platform': info.get('platform', 'telegram'),
                'name': info.get('name', 'User'),
                'days_inactive': (datetime.now() - last_tx_date).days
            })
    
    return inactive


def mark_reminder_sent(user_id: str) -> None:
    """Mark that we sent a reminder to this user."""
    data = _load_user_activity()
    user_id = str(user_id)
    
    if user_id in data:
        data[user_id]['last_reminder'] = datetime.now().isoformat()
        _save_user_activity(data)


def toggle_reminder(user_id: str, enabled: bool) -> None:
    """Enable/disable reminders for a user."""
    data = _load_user_activity()
    user_id = str(user_id)
    
    if user_id in data:
        data[user_id]['reminder_enabled'] = enabled
        _save_user_activity(data)


# ===================== NOTIFICATION SENDING =====================

def send_telegram_notification(chat_id: str, message: str) -> bool:
    """Send notification via Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            },
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        secure_log("ERROR", f"Telegram notification failed: {type(e).__name__}")
        return False


def send_whatsapp_notification(phone: str, message: str) -> bool:
    """Send notification via Fonnte WhatsApp."""
    if not FONNTE_TOKEN:
        return False
    
    try:
        response = requests.post(
            'https://api.fonnte.com/send',
            headers={'Authorization': FONNTE_TOKEN},
            data={'target': phone, 'message': message},
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        secure_log("ERROR", f"WhatsApp notification failed: {type(e).__name__}")
        return False


def send_notification(user_id: str, platform: str, message: str) -> bool:
    """Send notification via appropriate platform."""
    if platform == 'telegram':
        return send_telegram_notification(user_id, message)
    elif platform == 'whatsapp':
        return send_whatsapp_notification(user_id, message.replace('*', ''))
    return False


# ===================== REMINDER MESSAGES =====================

def get_inactivity_reminder(name: str, days: int) -> str:
    """Generate inactivity reminder message."""
    return f"""👋 *Hai {name}!*

Sudah *{days} hari* tidak ada transaksi yang dicatat.

Apakah ada pengeluaran yang belum diinput? Jangan sampai lupa ya! 📝

💡 *Tips:* Langsung kirim transaksi kapan saja:
• `Beli makan 50rb`
• `Bensin 100rb`
• Atau kirim foto struk

Balas pesan ini untuk mulai mencatat! 🚀"""


def get_budget_warning(percent: float, spent: int, budget: int) -> str:
    """Generate budget warning message."""
    remaining = budget - spent
    
    if percent >= 100:
        return f"""🚨 *BUDGET ALERT!*

Pengeluaran sudah *melebihi budget!*

💸 Terpakai: Rp {spent:,}
💼 Budget: Rp {budget:,}
📊 Lebih: Rp {abs(remaining):,}

Harap review pengeluaran Anda.
Ketik `/status` untuk detail.""".replace(',', '.')
    else:
        return f"""⚠️ *Budget Warning!*

Pengeluaran sudah *{percent:.0f}%* dari budget.

💸 Terpakai: Rp {spent:,}
💼 Budget: Rp {budget:,}
📊 Sisa: Rp {remaining:,}

Ketik `/status` untuk detail.""".replace(',', '.')


def get_weekly_summary() -> str:
    """Generate weekly summary message."""
    summary = get_summary(7)
    
    return f"""📊 *Ringkasan Mingguan*

💸 Pengeluaran: Rp {summary['total_pengeluaran']:,}
💰 Pemasukan: Rp {summary['total_pemasukan']:,}
📊 Saldo: Rp {summary['saldo']:,}
📝 Transaksi: {summary['transaction_count']}

Ketik `/laporan` untuk detail lengkap.""".replace(',', '.')


# ===================== SCHEDULER =====================

def check_and_send_reminders() -> int:
    """
    Check for inactive users and send reminders.
    Returns number of reminders sent.
    """
    sent_count = 0
    
    # 1. Check inactive users
    inactive_users = get_inactive_users()
    for user in inactive_users:
        message = get_inactivity_reminder(user['name'], user['days_inactive'])
        
        if send_notification(user['user_id'], user['platform'], message):
            mark_reminder_sent(user['user_id'])
            sent_count += 1
            secure_log("INFO", f"Inactivity reminder sent to user on {user['platform']}")
    
    # 2. Check budget warnings
    alert = check_budget_alert()
    if alert.get('alert_type'):
        message = get_budget_warning(
            alert['percent_used'],
            alert['spent'],
            alert['budget']
        )
        # Send to all active users
        data = _load_user_activity()
        for user_id, info in data.items():
            if info.get('reminder_enabled', True):
                send_notification(user_id, info.get('platform', 'telegram'), message)
                sent_count += 1
    
    return sent_count


def _scheduler_loop():
    """Background scheduler loop."""
    global _scheduler_running
    
    secure_log("INFO", "Reminder scheduler started")
    
    while _scheduler_running:
        try:
            sent = check_and_send_reminders()
            if sent > 0:
                secure_log("INFO", f"Sent {sent} reminder(s)")
        except Exception as e:
            secure_log("ERROR", f"Scheduler error: {type(e).__name__}")
        
        # Sleep with interrupt check
        for _ in range(int(REMINDER_CHECK_INTERVAL / 10)):
            if not _scheduler_running:
                break
            time.sleep(10)
    
    secure_log("INFO", "Reminder scheduler stopped")


def start_scheduler() -> None:
    """Start the background reminder scheduler."""
    global _scheduler_thread, _scheduler_running
    
    if _scheduler_thread and _scheduler_thread.is_alive():
        return  # Already running
    
    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()
    secure_log("INFO", f"Scheduler started. Check interval: {REMINDER_CHECK_INTERVAL}s")


def stop_scheduler() -> None:
    """Stop the background reminder scheduler."""
    global _scheduler_running
    _scheduler_running = False
    secure_log("INFO", "Scheduler stop requested")


# ===================== TESTING =====================

if __name__ == '__main__':
    print("=" * 50)
    print("Smart Reminder Module Test")
    print("=" * 50)
    
    # Test user activity
    print("\n1. Testing user activity tracking:")
    update_user_activity("test_123", "telegram", "Test User")
    print("   User activity updated")
    
    # Test inactive check
    print("\n2. Testing inactive user detection:")
    inactive = get_inactive_users(days=0)  # Get all users (0 days = everyone is "inactive")
    print(f"   Found {len(inactive)} users")
    
    # Test message generation
    print("\n3. Testing message generation:")
    print("   Inactivity reminder:")
    print(get_inactivity_reminder("Budi", 3)[:100] + "...")
    
    print("\n   Budget warning:")
    print(get_budget_warning(85, 8500000, 10000000)[:100] + "...")
    
    print("\n" + "=" * 50)
    print("All tests completed!")
