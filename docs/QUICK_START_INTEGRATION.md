# 🚀 QUICK START - Integrate Ultra-Robust Context Detection

## ⚡ 3-Step Integration

### **Step 1: Import the Enhanced Layer**

In your `main.py`, replace the old layer import with:

```python
# OLD (remove this):
# from layer_integration import process_with_layers

# NEW (use this):
from layer_integration_v2 import (
    process_with_enhanced_layers,
    parse_user_response,
    learn_from_confirmation
)
```

---

### **Step 2: Process Messages with Context Detection**

Replace your message processing logic:

```python
# When a transaction message comes in
def handle_transaction_message(message_text, user_id, chat_id, is_group=False):
    """Handle potential transaction message."""

    # Process with enhanced layers
    result = process_with_enhanced_layers(
        text=message_text,
        user_id=user_id,
        chat_id=chat_id,
        is_group=is_group
    )

    action = result['action']
    category_scope = result['category_scope']
    confidence = result['confidence']

    if action == 'AUTO':
        # ✅ High confidence - proceed automatically
        logger.info(f"AUTO classify: {category_scope} (confidence: {confidence:.2f})")

        # Continue with transaction processing
        # Use category_scope for routing to OPERATIONAL or PROJECT sheets
        continue_transaction_flow(message_text, category_scope, user_id, chat_id)

    elif action == 'CONFIRM':
        # 🤔 Medium confidence - ask confirmation
        logger.info(f"CONFIRM needed: {category_scope} (confidence: {confidence:.2f})")

        # Send confirmation prompt to user
        send_message(user_id, result['prompt'])

        # Store pending confirmation state
        store_pending_confirmation(user_id, {
            'type': 'CONFIRM',
            'original_text': message_text,
            'suggested_category': category_scope,
            'timestamp': datetime.now()
        })

    elif action == 'ASK':
        # ❓ Low confidence - ask for clarification
        logger.info(f"ASK for clarification: {category_scope} (confidence: {confidence:.2f})")

        # Send clarification prompt
        send_message(user_id, result['prompt'])

        # Store pending state
        store_pending_confirmation(user_id, {
            'type': 'ASK',
            'original_text': message_text,
            'timestamp': datetime.now()
        })

    else:  # IGNORE
        # Not a transaction
        return
```

---

### **Step 3: Handle User Responses**

Add response handling for confirmations:

```python
def handle_user_response(message_text, user_id, chat_id):
    """Handle user response to confirmation/clarification."""

    # Check if user has pending confirmation
    pending = get_pending_confirmation(user_id)

    if not pending:
        # No pending confirmation, process as new message
        handle_transaction_message(message_text, user_id, chat_id)
        return

    # Parse user response
    confirmed_category = parse_user_response(message_text)

    if confirmed_category:
        # ✅ User confirmed category
        logger.info(f"User confirmed: {confirmed_category}")

        # Learn from this confirmation for future
        learn_from_confirmation(
            original_text=pending['original_text'],
            confirmed_category=confirmed_category
        )

        # Process the original transaction with confirmed category
        continue_transaction_flow(
            text=pending['original_text'],
            category_scope=confirmed_category,
            user_id=user_id,
            chat_id=chat_id
        )

        # Clear pending state
        clear_pending_confirmation(user_id)

    else:
        # ❌ Could not parse response
        # Maybe user provided more details instead of "1" or "2"

        if pending['type'] == 'ASK':
            # User might have given more detail like "gaji admin"
            # Re-process with the new detailed text
            logger.info("User provided detailed response, re-processing...")

            # Clear pending first
            clear_pending_confirmation(user_id)

            # Re-process with potentially more context
            handle_transaction_message(message_text, user_id, chat_id)
        else:
            # Ask again
            send_message(user_id, "Maaf, jawab dengan '1' atau '2', atau kasih detail lebih.")
```

---

## 🗄️ State Management (Pending Confirmations)

You need to store pending confirmations. Here are two options:

### **Option A: In-Memory (Simple, for development)**

```python
# At module level
_pending_confirmations = {}

def store_pending_confirmation(user_id: str, data: dict):
    _pending_confirmations[user_id] = data

def get_pending_confirmation(user_id: str) -> dict:
    return _pending_confirmations.get(user_id)

def clear_pending_confirmation(user_id: str):
    if user_id in _pending_confirmations:
        del _pending_confirmations[user_id]
```

### **Option B: Redis/Database (Production)**

```python
import redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def store_pending_confirmation(user_id: str, data: dict):
    import json
    key = f"pending:confirmation:{user_id}"
    r.setex(key, 600, json.dumps(data))  # Expire after 10 min

def get_pending_confirmation(user_id: str) -> dict:
    import json
    key = f"pending:confirmation:{user_id}"
    data = r.get(key)
    return json.loads(data) if data else None

def clear_pending_confirmation(user_id: str):
    key = f"pending:confirmation:{user_id}"
    r.delete(key)
```

### **Option C: Using Existing State Manager**

```python
# If you already have state_manager.py
from services.state_manager import (
    save_state,
    load_state,
    clear_state
)

def store_pending_confirmation(user_id: str, data: dict):
    save_state(f"pending_confirm:{user_id}", data)

def get_pending_confirmation(user_id: str) -> dict:
    return load_state(f"pending_confirm:{user_id}")

def clear_pending_confirmation(user_id: str):
    clear_state(f"pending_confirm:{user_id}")
```

---

## 🎯 Integration with Your Routing Logic

Update your category routing:

```python
def continue_transaction_flow(text: str, category_scope: str, user_id: str, chat_id: str):
    """Continue with transaction after category is determined."""

    if category_scope == "OPERATIONAL":
        # 💼 OPERATIONAL - Go to Operasional Kantor flow
        logger.info("Routing to OPERATIONAL flow")

        # 1. Detect sub-category (Gaji, Listrik, Air, etc.)
        sub_category = detect_operational_subcategory(text)

        # 2. Ask which wallet to deduct from (1-3)
        send_message(user_id,
            f"💼 Catat Operasional:\n"
            f"Kategori: {sub_category}\n\n"
            f"Potong dari dompet mana?\n"
            f"1. CV HB (101)\n"
            f"2. TX SBY (216)\n"
            f"3. TX BALI (087)"
        )

        # Store state for wallet selection
        save_transaction_state(user_id, {
            'type': 'OPERATIONAL',
            'category': sub_category,
            'text': text,
            'waiting_for': 'wallet_selection'
        })

    elif category_scope == "PROJECT":
        # 📋 PROJECT - Go to Project flow
        logger.info("Routing to PROJECT flow")

        # 1. Extract or ask for project name
        project_name = extract_project_name(text)

        if project_name:
            # 2. Ask which wallet (1-4)
            send_message(user_id,
                f"📋 Catat Pengeluaran:\n"
                f"Project: {project_name}\n\n"
                f"Simpan ke dompet mana?\n"
                f"1. CV HB (101)\n"
                f"2. TX SBY (216)\n"
                f"3. TX BALI (087)\n"
                f"4. Lainnya"
            )

            save_transaction_state(user_id, {
                'type': 'PROJECT',
                'project_name': project_name,
                'text': text,
                'waiting_for': 'wallet_selection'
            })
        else:
            # Ask for project name
            send_message(user_id, "Untuk project apa?")

            save_transaction_state(user_id, {
                'type': 'PROJECT',
                'text': text,
                'waiting_for': 'project_name'
            })
```

---

## ✅ Testing Your Integration

### **Test 1: AUTO Classification**

```python
# Input:
"Gaji admin bulan Januari 5jt"

# Expected Flow:
# 1. process_with_enhanced_layers() returns { action: "AUTO", category_scope: "OPERATIONAL" }
# 2. continue_transaction_flow() routes to OPERATIONAL
# 3. User sees: "Potong dari dompet mana? 1-3"
```

### **Test 2: CONFIRM**

```python
# Input 1:
"Gajian tukang Wooftopia 2jt"

# Expected:
# Bot asks: "✅ Ini untuk *Project* (Project: Wooftopia), kan? 1️⃣ Ya 2️⃣ Bukan"

# Input 2:
"1"

# Expected:
# Bot confirms and asks wallet: "📋 Simpan ke dompet mana? 1-4"
# Pattern learned for future
```

### **Test 3: ASK Clarification**

```python
# Input 1:
"Gajian 5jt"

# Expected:
# Bot asks: "🤔 Ini maksudnya gaji staff kantor atau bayar orang project?"

# Input 2a (user picks option):
"1"

# Expected:
# Routes to OPERATIONAL

# Input 2b (user gives detail):
"gaji admin"

# Expected:
# Re-processes with more context, AUTO routes to OPERATIONAL
```

---

## 🐛 Common Issues & Fixes

### **Issue 1: Pattern Learning Not Working**

**Problem:** Patterns not saved to `_BOT_STATE` sheet

**Fix:**

- Ensure `_BOT_STATE` sheet exists in your spreadsheet
- Add headers: `Pattern | Category | Count | LastUpdated | Examples`
- Check `sheets_helper.py` has access to `_BOT_STATE`

### **Issue 2: Prompts Not Showing**

**Problem:** Confirmation prompts not sent

**Fix:**

```python
# Make sure you're sending the prompt
if result['action'] in ['CONFIRM', 'ASK']:
    prompt = result.get('prompt')
    if prompt:
        send_message(user_id, prompt)  # <- Don't forget this!
```

### **Issue 3: Confidence Too Low/High**

**Problem:** Too many ASK prompts or too few confirmations

**Fix:** Adjust thresholds in `utils/confidence_router.py`:

```python
# Lower threshold for more AUTO classifications
CONFIDENCE_HIGH = 0.80  # was 0.85

# Or adjust MEDIUM for more CONFIRM instead of ASK
CONFIDENCE_MEDIUM = 0.55  # was 0.60
```

---

## 📊 Monitoring & Analytics

Add logging to track performance:

```python
def handle_transaction_message(message_text, user_id, chat_id, is_group=False):
    result = process_with_enhanced_layers(...)

    # Log for analytics
    logger.info(f"[CONTEXT_DETECTION] "
                f"Action={result['action']} "
                f"Category={result['category_scope']} "
                f"Confidence={result['confidence']:.2f} "
                f"Text='{message_text[:50]}...'")

    # Track metrics (optional)
    track_metric('context_detection.action', result['action'])
    track_metric('context_detection.confidence', result['confidence'])
```

---

## 🎓 Best Practices

1. **Always learn from confirmations**

   ```python
   if confirmed_category:
       learn_from_confirmation(original_text, confirmed_category)
   ```

2. **Set timeout for pending confirmations**

   ```python
   # Clear pending after 10 minutes of inactivity
   if pending and (now - pending['timestamp']) > timedelta(minutes=10):
       clear_pending_confirmation(user_id)
   ```

3. **Provide fallback for unclear responses**

   ```python
   if not confirmed_category:
       send_message(user_id, "Balas '1' atau '2', atau kasih detail lebih")
   ```

4. **Monitor accuracy and adjust thresholds**
   - Track false positives (wrong AUTO classifications)
   - Track user corrections (CONFIRM → user picks opposite)
   - Adjust confidence thresholds based on data

---

## 🚀 You're Ready!

With these 3 steps, your bot now has **ultra-robust context detection**!

**Questions?** Check the full implementation guide: `docs/ULTRA_ROBUST_IMPLEMENTATION.md`

---

**Happy Coding! 🎉**
