"""
narrow_resolver.py - Typed resolver sempit (offline, deterministik)

TUJUAN
------
Ini BUKAN AI agent. Ini satu resolver bertipe yang menyerang satu masalah
paling sakit di bot: ambiguitas antara

    1. nama project
    2. dompet utama (sumber dana transaksi)
    3. sumber hutang (lender) ketika transaksi didanai pinjaman

Resolver ini sengaja dibuat:
- PURE: tidak menyentuh Google Sheets / jaringan, bisa dijalankan di test.
- TYPED: input jelas, output structured (ResolverDecision) + confidence + alasan.
- KONSERVATIF: kalau ragu, ia mengembalikan needs_confirmation=True, bukan menebak.

Resolver ini dipakai oleh replay harness (tests/replay) untuk diukur terhadap
label ground-truth dari chat nyata. Ia BELUM dipasang ke pipeline produksi;
promosi hanya dilakukan setelah akurasinya menang di replay cases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from config.wallets import (
    resolve_dompet_from_text,
    resolve_company_from_text,
    normalize_company_name,
    get_dompet_for_company,
)
from utils.parsers import extract_project_name_from_text


DEBT_KEYWORDS = ("utang", "hutang", "minjam", "minjem", "pinjam", "pinjem")
DEBT_WORD_RE = re.compile(r"\b(?:utang|hutang|minjam|minjem|pinjam|pinjem)\b", re.IGNORECASE)

PROJECT_WORD_RE = re.compile(r"\b(?:projek|project|proyek|prj)\b", re.IGNORECASE)

# Account-number -> canonical wallet, but ONLY when an account-context word
# precedes it. This closes the gap where config.resolve_dompet_from_text treats
# only "dompet|wallet|saldo" as context and ignores "rekening/rek".
# Guard (?![\d.\-/]) avoids matching long account numbers like "216-0737991".
_ACCOUNT_CODE_TO_WALLET = {
    "101": "CV HB(101)",
    "216": "TX SBY(216)",
    "087": "TX BALI(087)",
}
ACCOUNT_CTX_WALLET_RE = re.compile(
    r"\b(?:rekening|rek|no\.?\s*rek(?:ening)?|akun|account|rekening\s+tujuan)\b"
    r"[^0-9]{0,12}(101|216|087)(?![\d.\-/])",
    re.IGNORECASE,
)


def _wallet_from_account_context(text: str) -> Optional[str]:
    """Resolve wallet from 'rekening/rek <code>' phrasing. Returns None if absent."""
    if not text:
        return None
    m = ACCOUNT_CTX_WALLET_RE.search(text)
    if not m:
        return None
    return _ACCOUNT_CODE_TO_WALLET.get(m.group(1))


# OCR/bank-status noise that must never become a project name.
PROJECT_NAME_BLOCKLIST = {
    "successful",
    "success",
    "berhasil",
    "transaksi berhasil",
    "transfer successful",
    "pending",
    "completed",
    "failed",
    "settlement",
    "transaction",
}


@dataclass
class ResolverDecision:
    """Structured output of the narrow resolver."""

    project: Optional[str] = None
    main_wallet: Optional[str] = None  # canonical dompet sheet name
    debt_source: Optional[str] = None  # canonical dompet sheet name (lender)
    company: Optional[str] = None
    confidence: float = 0.0
    needs_confirmation: bool = False
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _strip_debt_clause(text: str) -> str:
    """Remove the trailing debt clause so the main scope is not polluted.

    "bayar fee sugeng project vadim utang CV HB"
        -> "bayar fee sugeng project vadim"
    The debt clause ("utang CV HB") names the LENDER, not the main wallet.
    """
    if not text:
        return ""
    # Reuse the shared DEBT_WORD_RE keyword set so variants like 'pinjem' are
    # stripped consistently (single source of truth, no pattern drift).
    return re.sub(
        DEBT_WORD_RE.pattern + r".*$",
        "",
        str(text),
        flags=re.IGNORECASE,
    ).strip()




def _debt_clause(text: str) -> str:
    """Return only the debt clause tail (where the lender lives)."""
    if not text:
        return ""
    m = DEBT_WORD_RE.search(text)
    if not m:
        return ""
    return text[m.start():]


def _looks_like_blocked_project(name: Optional[str]) -> bool:
    if not name:
        return False
    return name.strip().lower() in PROJECT_NAME_BLOCKLIST


def resolve_finance_message(text: str, ocr_text: str = "") -> ResolverDecision:
    """Resolve project / main wallet / debt source from a finance message.

    Args:
        text: the user's caption / free text (ground truth signal).
        ocr_text: optional OCR body from an attached receipt.

    Returns:
        ResolverDecision with confidence + reasons. Never raises.
    """
    decision = ResolverDecision()
    raw = (text or "").strip()
    if not raw:
        decision.needs_confirmation = True
        decision.reasons.append("empty_text")
        return decision

    lower = raw.lower()
    has_debt = bool(DEBT_WORD_RE.search(lower))
    main_scope = _strip_debt_clause(raw) if has_debt else raw
    debt_scope = _debt_clause(raw) if has_debt else ""

    # --- 1. Debt source (lender) lives in the debt clause only ---
    if has_debt:
        lender = resolve_dompet_from_text(debt_scope)
        if not lender:
            lender = _wallet_from_account_context(debt_scope)
            if lender:
                decision.reasons.append("debt_source_from_account_context")
        if lender:
            decision.debt_source = lender
            decision.reasons.append(f"debt_source_from_clause={lender}")
        else:
            decision.reasons.append("debt_keyword_without_resolvable_lender")

    # --- 2. Main wallet: from MAIN scope only (never the debt clause) ---
    # main_scope already has the debt clause stripped, so a wallet found here
    # genuinely belongs to the main transaction, not the lender.
    main_wallet = resolve_dompet_from_text(main_scope)
    if not main_wallet:
        # Fallback: "dari rekening 216" style that config resolver misses.
        main_wallet = _wallet_from_account_context(main_scope)
        if main_wallet:
            decision.reasons.append("main_wallet_from_account_context")
    if main_wallet:
        decision.main_wallet = main_wallet
        decision.reasons.append(f"main_wallet={main_wallet}")
    elif has_debt:
        decision.reasons.append("main_wallet_absent_funded_by_debt")



    # --- 3. Company (only used to derive wallet when explicit & unambiguous) ---
    company = resolve_company_from_text(main_scope, decision.main_wallet)
    if company:
        decision.company = company
        decision.reasons.append(f"company={company}")
        if not decision.main_wallet:
            derived = get_dompet_for_company(company)
            if derived:
                decision.main_wallet = derived
                decision.reasons.append(f"main_wallet_from_company={derived}")

    # --- 4. Project name from main scope, with blocklist guard ---
    project_scope = "\n".join(part for part in (main_scope, ocr_text or "") if str(part or "").strip())
    project = extract_project_name_from_text(project_scope)
    if _looks_like_blocked_project(project):
        decision.reasons.append(f"project_blocked_noise={project!r}")
        project = None
    if project:
        decision.project = project
        decision.reasons.append(f"project={project}")

    # --- 5. Confidence + confirmation policy ---
    score = 0.0
    if decision.main_wallet:
        score += 0.40
    if decision.project:
        score += 0.30
    if has_debt and decision.debt_source:
        score += 0.20
    if decision.company:
        score += 0.10

    # Ambiguity penalties / hard confirmation triggers.
    project_signal = bool(PROJECT_WORD_RE.search(lower))
    if project_signal and not decision.project:
        decision.needs_confirmation = True
        decision.reasons.append("project_word_but_no_project_name")
    if has_debt and not decision.debt_source:
        decision.needs_confirmation = True
        decision.reasons.append("debt_word_but_no_lender")
    if not decision.main_wallet:
        decision.needs_confirmation = True
        decision.reasons.append("no_main_wallet")

    decision.confidence = round(min(score, 0.99), 2)
    if decision.confidence < 0.6:
        decision.needs_confirmation = True

    return decision
