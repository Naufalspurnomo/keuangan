
import json
import uuid
import time
import os
import threading
from datetime import datetime
from typing import List, Dict, Optional

# File to store pending writes persistently
QUEUE_FILE = 'pending_writes.json'

# Lock for file operations
_queue_lock = threading.Lock()

def load_queue() -> List[Dict]:
    """Load pending queue from disk."""
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_queue(queue: List[Dict]) -> None:
    """Save pending queue to disk."""
    try:
        with open(QUEUE_FILE, 'w') as f:
            json.dump(queue, f, indent=2)
    except IOError as e:
        print(f"[RETRY_SERVICE] Failed to save queue: {e}")

def add_to_retry_queue(transaction: Dict, metadata: Dict) -> str:
    """
    Add a failed transaction to the retry queue.
    
    Args:
        transaction: The transaction data dict
        metadata: Context needed for saving (sender, dompet_sheet, etc.)
        
    Returns:
        QUEUE_ID string
    """
    queue_item = {
        'id': str(uuid.uuid4()),
        'created_at': time.time(),
        'attempts': 0,
        'transaction': transaction,
        'metadata': metadata
    }
    
    with _queue_lock:
        queue = load_queue()
        queue.append(queue_item)
        save_queue(queue)
        
    print(f"[RETRY_SERVICE] Transaction queued for retry. Queue size: {len(queue)+1}")
    return queue_item['id']

def get_queue_status() -> Dict:
    """Get stats about current queue."""
    with _queue_lock:
        queue = load_queue()
        return {
            'count': len(queue),
            'oldest': min([q['created_at'] for q in queue]) if queue else None,
            'file_size': os.path.getsize(QUEUE_FILE) if os.path.exists(QUEUE_FILE) else 0
        }

def process_retry_queue(process_func) -> int:
    """
    Process items in the queue using the provided function.
    
    Args:
        process_func: Function(transaction, metadata) -> bool (success)
        
    Returns:
        Number of successfully processed items
    """
    with _queue_lock:
        queue = load_queue()
        
    if not queue:
        return 0
        
    active_queue = queue[:] # Copy
    remaining_queue = []
    success_count = 0
    
    print(f"[RETRY_SERVICE] Processing {len(active_queue)} items...")
    
    for item in active_queue:
        tx = item['transaction']
        meta = item['metadata']
        
        try:
            # Attempt to process
            print(f"[RETRY_SERVICE] Retrying item {item['id']} ({meta.get('dompet_sheet')})...")
            success = process_func(tx, meta)
            
            if success:
                success_count += 1
                item['status'] = 'processed'
            else:
                item['attempts'] += 1
                remaining_queue.append(item)
                
        except Exception as e:
            print(f"[RETRY_SERVICE] Error processing item {item['id']}: {e}")
            item['attempts'] += 1
            remaining_queue.append(item)
            
    # Save back failures
    with _queue_lock:
        save_queue(remaining_queue)
        
    if success_count > 0:
        print(f"[RETRY_SERVICE] Batch complete. Success: {success_count}. Remaining: {len(remaining_queue)}")
        
    return success_count
