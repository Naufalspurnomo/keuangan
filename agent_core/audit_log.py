from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


_LOCK = threading.Lock()


def log_event(event_type: str, payload: Dict[str, Any] | None = None) -> None:
    """Append a best-effort local audit event."""
    backend = os.getenv("AGENT_AUDIT_BACKEND", "local").strip().lower()
    if backend in {"", "0", "false", "no", "off", "none"}:
        return
    if backend != "local":
        return

    path = Path(os.getenv("AGENT_AUDIT_PATH", "data/agent_audit.jsonl"))
    event = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event_type": str(event_type or "unknown"),
        "payload": payload or {},
    }

    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception:
        return

