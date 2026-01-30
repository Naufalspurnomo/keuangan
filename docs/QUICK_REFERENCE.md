# 🚀 QUICK REFERENCE - Ultra-Robust Context Detection

## 📦 Import

```python
from layer_integration_v2 import (
    process_with_enhanced_layers,
    parse_user_response,
    learn_from_confirmation
)
```

---

## 🎯 Main Processing

```python
result = process_with_enhanced_layers(
    text="Gaji admin 5jt",
    user_id="628123456789",
    chat_id="chat_id",
    is_group=False
)

# Returns:
{
    "action": "AUTO" | "CONFIRM" | "ASK",
    "category_scope": "OPERATIONAL" | "PROJECT" | "AMBIGUOUS",
    "confidence": 0.95,
    "prompt": "..." or None,
    "context_analysis": {...},
    "reasoning": "..."
}
```

---

## 🔀 Routing Logic

```python
if result['action'] == 'AUTO':
    # ✅ High confidence - proceed
    category = result['category_scope']
    process_transaction(text, category)

elif result['action'] == 'CONFIRM':
    # ❓ Ask confirmation
    send_message(user_id, result['prompt'])
    save_pending(user_id, {
        'text': text,
        'category': result['category_scope']
    })

elif result['action'] == 'ASK':
    # 🤔 Ask clarification
    send_message(user_id, result['prompt'])
    save_pending(user_id, {'text': text})
```

---

## 💬 Parse User Response

```python
# User replied "1", "2", or text
category = parse_user_response(user_reply)

if category:  # "OPERATIONAL" or "PROJECT"
    # Learn pattern
    learn_from_confirmation(original_text, category)

    # Process
    process_transaction(original_text, category)

    # Clear pending
    clear_pending(user_id)
```

---

## 🎨 Example Flows

### **AUTO (High Confidence)**

```
User: "Gaji admin Jan 5jt"
→ result['action'] = "AUTO"
→ result['category_scope'] = "OPERATIONAL"
→ result['confidence'] = 1.00
→ Process immediately
```

### **CONFIRM (Medium Confidence)**

```
User: "Gajian tukang Wooftopia 2jt"
→ result['action'] = "CONFIRM"
→ result['prompt'] = "✅ Ini untuk *Project*, kan? 1️⃣ Ya 2️⃣ Bukan"
→ Wait for "1" or "2"
→ Learn pattern
→ Process
```

### **ASK (Low Confidence)**

```
User: "Gajian 5jt"
→ result['action'] = "ASK"
→ result['prompt'] = "🤔 Ini gaji staff kantor atau tukang? ..."
→ Wait for "1", "2", or detailed response
→ Process after clarification
```

---

## 📊 Confidence Thresholds

| Range     | Action  | UX                  |
| --------- | ------- | ------------------- |
| ≥ 0.85    | AUTO    | No prompt           |
| 0.60-0.84 | CONFIRM | "Ini untuk X, kan?" |
| < 0.60    | ASK     | "Maksudnya apa?"    |

Adjust in `utils/confidence_router.py`

---

## 🔑 Key Signals

### **OPERATIONAL Indicators**

- Keywords: `gaji admin`, `listrik`, `pln`, `wifi`, `atk`
- Roles: `admin`, `staff`, `karyawan`
- Temporal: `bulan`, `bulanan`, `per bulan`

### **PROJECT Indicators**

- Keywords: `bayar tukang`, `material`, `semen`, `cat`
- Roles: `tukang`, `pekerja lapangan`, `mandor`
- Context: Project name present

### **AMBIGUOUS**

- Keywords: `gaji`, `bon`, `fee` (without role/context)

---

## 🧪 Testing

```bash
# Test context detector
python utils/context_detector.py

# Test confidence router
python utils/confidence_router.py

# Test integration
python layer_integration_v2.py

# Test with Groq AI
python tests/test_context_groq_integration.py
```

---

## 📝 State Management Pattern

```python
# Save pending confirmation
pending_state[user_id] = {
    'original_text': "Gajian 5jt",
    'suggested_category': "OPERATIONAL",
    'timestamp': datetime.now()
}

# Retrieve pending
pending = pending_state.get(user_id)

# Process response
if pending:
    category = parse_user_response(reply)
    if category:
        learn_from_confirmation(pending['original_text'], category)
        process_transaction(pending['original_text'], category)
        del pending_state[user_id]
```

---

## 🐛 Common Patterns

### **Handle Detail Response**

```python
# User gives detail instead of "1" or "2"
if pending and not category:
    # Re-process with more context
    new_result = process_with_enhanced_layers(
        text=reply,  # "gaji admin" instead of "1"
        ...
    )
```

### **Timeout Pending**

```python
# Clear stale confirmations
if pending and (now - pending['timestamp']) > timedelta(minutes=10):
    del pending_state[user_id]
```

### **Learn from Correction**

```python
# User said "2" (opposite of suggestion)
if category != pending['suggested_category']:
    # Still learn - user knows better
    learn_from_confirmation(pending['original_text'], category)
```

---

## 📈 Monitoring

```python
# Log for analytics
logger.info(f"[CONTEXT] action={result['action']} "
            f"category={result['category_scope']} "
            f"confidence={result['confidence']:.2f}")

# Track metrics
track('context.action', result['action'])
track('context.confidence', result['confidence'])
```

---

## 🔧 Configuration

**Edit Keywords:**

- File: `utils/context_detector.py`
- Sections: `OPERATIONAL_STRONG_KEYWORDS`, `PROJECT_STRONG_KEYWORDS`

**Edit Thresholds:**

- File: `utils/confidence_router.py`
- Variables: `CONFIDENCE_HIGH`, `CONFIDENCE_MEDIUM`

**Edit Prompts:**

- File: `utils/confidence_router.py`
- Methods: `_generate_confirmation_prompt()`, `_generate_clarification_prompt()`

---

## 📚 Full Documentation

- **Implementation Guide:** `docs/ULTRA_ROBUST_IMPLEMENTATION.md`
- **Quick Start:** `docs/QUICK_START_INTEGRATION.md`
- **Status:** `docs/IMPLEMENTATION_STATUS.md`
- **Summary:** `README_ULTRA_ROBUST.md`

---

## ✅ Checklist for Integration

- [ ] Import enhanced layers
- [ ] Replace message processing
- [ ] Add pending state management
- [ ] Handle user responses
- [ ] Route based on category_scope
- [ ] Test with real messages
- [ ] Monitor accuracy
- [ ] Tune thresholds if needed

---

**Quick Ref v2.0 | 2026-01-30 | Naufal + Antigravity**
