"""
probe_resolver.py - Stress-probe otomatis untuk narrow_resolver.

TUJUAN
------
"Mengumpulkan data sendiri" tanpa menunggu log produksi: membangkitkan banyak
variasi frasa dari ATURAN DOMAIN user (project/operasional, 3 dompet, HOLLA/
HOJJA, hutang antar-dompet), menjalankannya lewat resolver, lalu MENANDAI
output yang mencurigakan secara heuristik.

Ini BUKAN ground truth — ia tidak tahu jawaban benar. Ia hanya memburu pola
yang HAMPIR PASTI salah (sanity violations), supaya kandidat gap muncul ke
permukaan tanpa pelabelan manual satu per satu. Output mencurigakan lalu bisa
diangkat jadi fixture berlabel (oleh manusia) atau diperbaiki di resolver.

Pure & offline. Pakai:
    python -m tests.replay.probe_resolver
    python -m tests.replay.probe_resolver --all   # tampilkan semua, bukan hanya suspicious
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys
from typing import Any, Dict, List

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from services.narrow_resolver import resolve_finance_message, PROJECT_NAME_BLOCKLIST  # noqa: E402

# Building blocks derived from the user's domain rules.
ACTIONS = ["beli material", "bayar fee tukang", "beli semen", "bayar upah", "transfer"]
PROJECTS = ["vadim", "ronald", "taman kota", "ruko bu sari", "mural pvj", "gudang"]
WALLET_PHRASES = {
    "dari TX SBY": "TX SBY(216)",
    "dari TX BALI": "TX BALI(087)",
    "dari CV HB": "CV HB(101)",
    "pakai dompet TX SBY": "TX SBY(216)",
    "dari rekening 216": "TX SBY(216)",
    "dari rekening 087": "TX BALI(087)",
}
DEBT_PHRASES = {
    "utang CV HB": "CV HB(101)",
    "pinjam HOLLA": "CV HB(101)",
    "minjam TX BALI": "TX BALI(087)",
    "utang TX SBY": "TX SBY(216)",
    "utang rekening 216": "TX SBY(216)",
    "pinjem rek 087": "TX BALI(087)",
}
# Words that must NEVER become a project name.
NOISE_PROJECTS = sorted(PROJECT_NAME_BLOCKLIST)


def _suspicions(text: str, decision, *, expect_debt: str = "", expect_wallet: str = "") -> List[str]:
    """Heuristic sanity checks. Return list of likely-bug descriptions."""
    issues: List[str] = []

    proj = (decision.project or "").strip().lower()

    # 1. Project must never be a blocklisted noise word.
    if proj and proj in PROJECT_NAME_BLOCKLIST:
        issues.append(f"project is noise word: {decision.project!r}")

    # 2. If a debt clause names a lender, debt_source must be set (not main_wallet).
    if expect_debt:
        if decision.debt_source != expect_debt:
            issues.append(f"debt_source expected {expect_debt!r}, got {decision.debt_source!r}")
        if decision.main_wallet == expect_debt and expect_wallet != expect_debt:
            issues.append(f"lender {expect_debt!r} leaked into main_wallet")

    # 3. If a main wallet phrase is present, resolver should find that wallet.
    if expect_wallet and decision.main_wallet != expect_wallet:
        issues.append(f"main_wallet expected {expect_wallet!r}, got {decision.main_wallet!r}")

    # 4. Confidence sanity: if both wallet+project resolved, should not need_confirmation.
    if decision.main_wallet and decision.project and decision.needs_confirmation and not expect_debt:
        issues.append("needs_confirmation=True despite wallet+project resolved (no debt)")

    return issues


def generate_cases() -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []

    # A) Clean: action + project + wallet (no debt) -> expect that wallet, no debt.
    for action, project, (wphrase, wcanon) in itertools.product(ACTIONS[:3], PROJECTS[:4], WALLET_PHRASES.items()):
        text = f"{action} project {project} {wphrase}"
        cases.append({"text": text, "expect_wallet": wcanon, "expect_debt": ""})

    # B) Debt-funded: action + project + debt clause (no main wallet) -> lender only.
    for action, project, (dphrase, dcanon) in itertools.product(ACTIONS[:3], PROJECTS[:4], DEBT_PHRASES.items()):
        text = f"{action} project {project} {dphrase}"
        cases.append({"text": text, "expect_wallet": "", "expect_debt": dcanon})

    # C) Both: main wallet + debt clause, must split correctly.
    for project, (wphrase, wcanon), (dphrase, dcanon) in itertools.product(
        PROJECTS[:3], list(WALLET_PHRASES.items())[:3], list(DEBT_PHRASES.items())[:3]
    ):
        if wcanon == dcanon:
            continue  # same wallet as lender is a different (degenerate) case
        text = f"beli material project {project} {wphrase} {dphrase}"
        cases.append({"text": text, "expect_wallet": wcanon, "expect_debt": dcanon})

    # D) Noise-as-project: ensure blocklist words never leak as project.
    for noise, (wphrase, wcanon) in itertools.product(NOISE_PROJECTS, list(WALLET_PHRASES.items())[:2]):
        text = f"bayar project {noise} {wphrase}"
        cases.append({"text": text, "expect_wallet": wcanon, "expect_debt": ""})

    # E) MESSY tier — closer to real WhatsApp chat: no 'project' keyword,
    #    casual phrasing, typos. These are where real gaps hide. We assert only
    #    the debt-split rule (lender must not become main wallet) since that is
    #    unambiguous regardless of phrasing.
    messy_debt = [
        "fee tukang vadim pinjem holla",          # typo 'pinjem', no 'project'
        "bayar material ronald, utang cv hb",     # comma, lowercase
        "kasih upah taman kota minjam tx bali",   # 'kasih', no project word
        "fee paw ronald pinjam hojja",            # hojja -> same CV HB(101)
    ]
    debt_canon = {
        "holla": "CV HB(101)", "cv hb": "CV HB(101)", "hojja": "CV HB(101)",
        "tx bali": "TX BALI(087)", "tx sby": "TX SBY(216)",
    }
    for text in messy_debt:
        lower = text.lower()
        expect_debt = next((c for k, c in debt_canon.items() if k in lower), "")
        cases.append({"text": text, "expect_wallet": "", "expect_debt": expect_debt})

    return cases



def run(show_all: bool = False) -> int:
    cases = generate_cases()
    suspicious: List[Dict[str, Any]] = []

    for c in cases:
        decision = resolve_finance_message(c["text"])
        issues = _suspicions(
            c["text"], decision,
            expect_debt=c.get("expect_debt", ""),
            expect_wallet=c.get("expect_wallet", ""),
        )
        if issues:
            suspicious.append({"text": c["text"], "issues": issues,
                               "got": {"project": decision.project,
                                       "main_wallet": decision.main_wallet,
                                       "debt_source": decision.debt_source,
                                       "needs_confirmation": decision.needs_confirmation}})

    print("=" * 70)
    print(f"RESOLVER PROBE — {len(cases)} generated cases")
    print("=" * 70)

    if show_all:
        for c in cases:
            d = resolve_finance_message(c["text"])
            print(f"- {c['text']}")
            print(f"    -> project={d.project!r} wallet={d.main_wallet!r} "
                  f"debt={d.debt_source!r} conf={d.confidence} need={d.needs_confirmation}")

    print(f"\nSUSPICIOUS: {len(suspicious)}/{len(cases)} cases have likely issues")
    for s in suspicious[:40]:
        print(f"\n[?] {s['text']}")
        for issue in s["issues"]:
            print(f"    - {issue}")
        print(f"    got: {s['got']}")
    if len(suspicious) > 40:
        print(f"\n… and {len(suspicious) - 40} more suspicious cases.")
    print("=" * 70)

    # Exit non-zero only if blocklist leaks exist (the hardest must-never rule).
    blocklist_leaks = sum(
        1 for s in suspicious if any("noise word" in i for i in s["issues"])
    )
    print(f"Blocklist leaks (must be 0): {blocklist_leaks}")
    return 1 if blocklist_leaks else 0


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Stress-probe narrow_resolver from domain rules.")
    parser.add_argument("--all", action="store_true", help="Print every generated case, not just suspicious.")
    args = parser.parse_args(argv)
    return run(show_all=args.all)


if __name__ == "__main__":
    raise SystemExit(main())
