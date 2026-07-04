from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict

from agent_core.audit_log import log_event


INTENTS = {
    "RECORD",
    "REVISE",
    "QUERY",
    "DEBT",
    "TRANSFER",
    "CONFIRM_PENDING",
    "CHITCHAT",
    "UNCLEAR",
}

_FINANCE_WORDS = (
    "catat", "beli", "bayar", "biaya", "keluar", "masuk", "dp", "fee",
    "gaji", "upah", "honor", "invoice", "nota", "struk", "ongkir",
    "projek", "project", "proyek", "kantor", "operasional", "dompet",
)
_QUERY_WORDS = (
    "berapa", "cek", "check", "lihat", "tanya", "total", "rekap", "laporan",
    "saldo", "profit", "omset", "pengeluaran", "pemasukan", "status",
)
_REVISION_WORDS = ("revisi", "ubah", "ganti", "edit", "koreksi", "ralat", "undo", "hapus")
_TRANSFER_WORDS = ("transfer", "pindah", "mutasi", "geser", "set saldo", "update saldo")
_DEBT_WORDS = ("hutang", "utang", "piutang", "lunas", "cicil", "pinjam")
_CHITCHAT_WORDS = ("halo", "hai", "makasih", "terima kasih", "siapa", "test", "tes")


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    confidence: float
    gate: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _mode() -> str:
    return os.getenv("INTENT_ROUTER_MODE", "off").strip().lower()


def _has_amount(text: str) -> bool:
    return bool(re.search(r"(?:rp\s*)?\d[\d.,]*(?:\s*(?:rb|ribu|jt|juta|k))?\b", text or "", re.I))


def _has_any(text: str, words) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def _gate(intent: str, confidence: float) -> str:
    if intent in {"CHITCHAT", "UNCLEAR"}:
        return "ignore"
    if confidence >= 0.85:
        return "auto"
    if confidence >= 0.55:
        return "confirm"
    return "clarify"


def _decision(intent: str, confidence: float, reason: str) -> IntentDecision:
    confidence = max(0.0, min(1.0, float(confidence)))
    return IntentDecision(intent=intent, confidence=confidence, gate=_gate(intent, confidence), reason=reason)


def route_intent(
    text: str,
    *,
    has_media: bool = False,
    is_group: bool = False,
    has_pending: bool = False,
    is_reply: bool = False,
) -> IntentDecision:
    """Cheap deterministic intent router for shadow-mode measurement."""
    raw = text or ""
    lower = " ".join(raw.casefold().split())
    stripped = lower.strip()
    has_amount = _has_amount(stripped)

    if has_pending:
        if re.fullmatch(r"\d{1,2}|ya|y|yes|ok|oke|lanjut|tidak|no|batal", stripped):
            return _decision("CONFIRM_PENDING", 0.93, "pending_control_reply")
        if has_media or has_amount:
            return _decision("RECORD", 0.72, "pending_transaction_update")

    if not stripped and has_media:
        return _decision("RECORD", 0.78, "media_without_text")
    if not stripped:
        return _decision("UNCLEAR", 0.2, "empty_text")

    if stripped.startswith(("/catat", "+catat", "catat ")):
        return _decision("RECORD", 0.96, "explicit_record_command")
    if stripped.startswith(("/tanya", "/status", "/saldo", "/laporan")):
        return _decision("QUERY", 0.95, "explicit_query_command")

    if _has_any(stripped, _REVISION_WORDS) and (is_reply or "yang tadi" in stripped or has_amount):
        return _decision("REVISE", 0.84, "revision_words")
    if _has_any(stripped, _DEBT_WORDS):
        return _decision("DEBT", 0.8 if has_amount else 0.68, "debt_words")
    if _has_any(stripped, _TRANSFER_WORDS) and re.search(r"\b(dari|ke|saldo|dompet)\b", stripped):
        return _decision("TRANSFER", 0.82 if has_amount else 0.64, "transfer_words")

    looks_query = "?" in stripped or _has_any(stripped, _QUERY_WORDS)
    if looks_query and any(word in stripped for word in ("saldo", "total", "rekap", "laporan", "pengeluaran", "pemasukan", "profit", "omset", "hutang", "piutang")):
        return _decision("QUERY", 0.88, "finance_query_words")

    has_finance_word = _has_any(stripped, _FINANCE_WORDS)
    if has_amount and has_finance_word:
        return _decision("RECORD", 0.88, "amount_and_finance_words")
    if has_media and (has_amount or has_finance_word):
        return _decision("RECORD", 0.74, "media_with_finance_hint")
    if has_amount:
        return _decision("RECORD", 0.62 if is_group else 0.7, "amount_only")

    if _has_any(stripped, _CHITCHAT_WORDS):
        return _decision("CHITCHAT", 0.78, "smalltalk_words")
    return _decision("UNCLEAR", 0.42 if is_group else 0.5, "no_finance_signal")


def record_intent_shadow(text: str, **context: Any) -> IntentDecision | None:
    """Log router decisions without changing runtime behavior."""
    if _mode() != "shadow":
        return None
    try:
        decision = route_intent(
            text,
            has_media=bool(context.get("has_media")),
            is_group=bool(context.get("is_group")),
            has_pending=bool(context.get("has_pending")),
            is_reply=bool(context.get("is_reply")),
        )
        log_event("intent_router_shadow", {
            "decision": decision.to_dict(),
            "context": {
                "chat_id": str(context.get("chat_id") or "")[:80],
                "user_id": str(context.get("user_id") or "")[:80],
                "source": str(context.get("source") or "")[:40],
                "is_group": bool(context.get("is_group")),
                "has_media": bool(context.get("has_media")),
                "has_pending": bool(context.get("has_pending")),
                "is_reply": bool(context.get("is_reply")),
            },
            "text_preview": str(text or "")[:160],
        })
        return decision
    except Exception:
        return None