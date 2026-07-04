from __future__ import annotations

import json
import os
import re
import threading
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List


_LOCK = threading.Lock()
_VALID_ROLES = {"user", "bot"}


def _enabled() -> bool:
    raw = os.getenv("CONVERSATION_MEMORY_ENABLED", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _path() -> Path:
    return Path(os.getenv("CONVERSATION_MEMORY_PATH", "data/conversation_memory.jsonl"))


def _ttl_seconds() -> int:
    try:
        return int(os.getenv("CONVERSATION_MEMORY_TTL_SECONDS", str(24 * 60 * 60)))
    except (TypeError, ValueError):
        return 24 * 60 * 60


def _max_bytes() -> int:
    try:
        return int(os.getenv("CONVERSATION_MEMORY_MAX_BYTES", str(5 * 1024 * 1024)))
    except (TypeError, ValueError):
        return 5 * 1024 * 1024


def _parse_ts(value: str):
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def _rotate_if_needed(path: Path) -> None:
    max_bytes = _max_bytes()
    if max_bytes <= 0 or not path.exists() or path.stat().st_size < max_bytes:
        return
    rotated = path.with_name(path.name + ".1")
    if rotated.exists():
        rotated.unlink()
    path.replace(rotated)


def _clean_text(text: str, limit: int = 800) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned[:limit]


def record_message(chat_id: str, user_id: str, role: str, text: str) -> None:
    """Record one chat turn. Best effort; never blocks bot flow."""
    if not _enabled() or role not in _VALID_ROLES:
        return
    clean = _clean_text(text)
    if not clean:
        return

    event = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "chat_id": str(chat_id or ""),
        "user_id": str(user_id or ""),
        "role": role,
        "text": clean,
    }
    try:
        path = _path()
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed(path)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception:
        return


def get_recent(chat_id: str, user_id: str, limit: int = 6) -> List[Dict]:
    if not _enabled() or limit <= 0:
        return []
    path = _path()
    if not path.exists():
        return []

    target_chat = str(chat_id or "")
    target_user = str(user_id or "")
    ttl = _ttl_seconds()
    cutoff = datetime.now() - timedelta(seconds=ttl) if ttl > 0 else None
    recent = deque(maxlen=limit)
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(item.get("chat_id", "")) != target_chat:
                    continue
                if str(item.get("user_id", "")) != target_user:
                    continue
                if item.get("role") not in _VALID_ROLES:
                    continue
                ts = _parse_ts(item.get("ts"))
                if cutoff and (not ts or ts < cutoff):
                    continue
                recent.append(item)
    except Exception:
        return []
    return list(recent)


def render_for_prompt(messages: List[Dict]) -> str:
    lines = []
    for item in messages or []:
        role = item.get("role")
        text = _clean_text(item.get("text", ""), limit=300)
        if role in _VALID_ROLES and text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)
