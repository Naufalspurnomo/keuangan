"""Agentic natural-language finance queries.

Groq plans the question and writes the final prose. Python remains responsible
for retrieving rows, filtering them, and calculating every number.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from ai_helper import call_groq_api
from agent_core.audit_log import log_event
from agent_core.query_engine import execute, parse_ast, select_rows
from config.wallets import resolve_dompet_from_text
from security import detect_prompt_injection, log_timing
from sheets_helper import find_open_hutang, get_all_data, get_hutang_summary, get_wallet_balances
from utils.amounts import parse_money_token
from utils.parsers import parse_revision_amount


logger = logging.getLogger(__name__)
QUERY_MODEL = os.getenv("QUERY_AGENT_MODEL", "llama-3.1-8b-instant")
MAX_EVIDENCE_ROWS = 60
PROJECT_IGNORES = {"", "umum", "saldo umum", "operasional", "operasional kantor", "-"}


def _extract_json_object(text: str) -> Dict[str, Any]:
    start = (text or "").find("{")
    end = (text or "").rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM did not return JSON")
    return json.loads(text[start:end + 1])


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value or "").strip()
        if text and any(token in text.casefold() for token in ("rb", "ribu", "jt", "juta", "perak")):
            return parse_revision_amount(text)
        parsed = parse_money_token(text)
        if parsed:
            return parsed
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_text(value: Any, limit: int, *, fallback: str = "") -> str:
    raw_text = str(value or "")
    return fallback if detect_prompt_injection(raw_text)[0] else raw_text[:limit]


def _ask_llm_for_plan(question: str, default_days: Optional[int]) -> Dict[str, Any]:
    today = datetime.now().date().isoformat()
    default_period = "all_time" if default_days is None else default_days
    system = f"""You route Indonesian finance questions into a safe retrieval plan.
Today is {today}. The caller's default period is {default_period}.
Return JSON only with this schema:
{{
  "intent": "project_activity|project_detail|summary|wallet|debt|comparison|category|ranking|transaction_search|unknown",
  "metric": "sum|count|avg|max|min",
  "filters": {{"project": null, "category": null, "tipe": null, "company": null, "dompet": null, "date_from": null, "date_to": null}},
  "group_by": null|"project"|"category"|"tipe"|"company"|"dompet",
  "period_days": {default_period}|null,
  "detail": false
}}

Rules:
- "project yang dikerjakan", "project aktif", "project apa saja" => project_activity, group_by project.
- A named project with "rincian", "detail", or a specific amount question => project_detail, filter project.
- Preserve explicit project, dompet, category, and Pemasukan/Pengeluaran terms.
- period_days is an integer: 1 for today, 7 for this week, 30 for this month/30 days; null means all history.
- Do not calculate amounts. Do not invent project names. Use unknown when the question is not a finance query.
"""
    response = call_groq_api(
        model=QUERY_MODEL,
        temperature=0,
        max_tokens=500,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({"question": question}, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )
    return _extract_json_object(response.choices[0].message.content)


def _normalize_plan(raw: Dict[str, Any], default_days: Optional[int]) -> Dict[str, Any]:
    raw_intent = str(raw.get("intent") or "unknown").strip().lower()
    intent_aliases = {
        "project": "project_detail",
        "project_list": "project_activity",
        "project_active": "project_activity",
        "projects": "project_activity",
    }
    intent = intent_aliases.get(raw_intent, raw_intent)
    allowed_intents = {
        "project_activity", "project_detail", "summary", "wallet", "debt",
        "comparison", "category", "ranking", "transaction_search", "unknown",
    }
    if intent not in allowed_intents:
        intent = "unknown"

    raw_filters = raw.get("filters") if isinstance(raw.get("filters"), dict) else {}
    filters = {}
    for key in ("project", "category", "tipe", "company", "dompet", "date_from", "date_to"):
        value = raw_filters.get(key)
        if value not in (None, ""):
            filters[key] = str(value).strip()[:120]

    ast = {
        "metric": str(raw.get("metric") or "sum").strip().lower(),
        "filters": filters,
        "group_by": raw.get("group_by") or None,
    }
    try:
        ast = parse_ast(ast)
    except ValueError:
        # Never broaden a malformed model plan into an unfiltered financial
        # query. Let the legacy deterministic router handle it instead.
        return {
            "intent": "unknown",
            "ast": {"metric": "sum", "filters": {}, "group_by": None},
            "period_days": default_days,
            "detail": bool(raw.get("detail")),
        }

    if intent == "project_activity":
        ast["metric"] = "count"
        ast["group_by"] = "project"

    period_raw = raw.get("period_days", default_days)
    period_days = None if period_raw in (None, "", 0, "all_time") else _safe_int(period_raw, default_days or 30)
    if period_days is not None:
        period_days = max(1, min(period_days, 3650))

    return {
        "intent": intent,
        "ast": ast,
        "period_days": period_days,
        "detail": bool(raw.get("detail")),
    }


def _is_real_project(row: Dict[str, Any]) -> bool:
    project = str(row.get("nama_projek") or "").strip().casefold()
    return project not in PROJECT_IGNORES and bool(project)


def _safe_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only finance evidence needed by the answer model."""
    row = row if isinstance(row, dict) else {}
    return {
        "tanggal": _safe_text(row.get("tanggal"), 32, fallback="[tanggal disensor]"),
        "jumlah": _safe_int(row.get("jumlah")),
        "tipe": _safe_text(row.get("tipe"), 24, fallback="[tipe disensor]"),
        "keterangan": _safe_text(row.get("keterangan"), 180, fallback="[deskripsi disensor]"),
        "project": _safe_text(row.get("nama_projek"), 120, fallback="[project disensor]"),
        "dompet": _safe_text(
            row.get("company_sheet") or row.get("sheet_name"),
            80,
            fallback="[dompet disensor]",
        ),
        "kategori": _safe_text(row.get("kategori"), 80, fallback="[kategori disensor]"),
    }


def _safe_wallet_balances(balances: Dict[str, Any], requested_dompet: Optional[str] = None) -> Dict[str, Dict[str, int]]:
    fields = ("saldo", "pemasukan", "pengeluaran", "operational_debit", "utang_open_in")
    safe = {}
    for name, info in (balances or {}).items():
        if requested_dompet and name != requested_dompet:
            continue
        info_dict = info if isinstance(info, dict) else {}
        safe_name = _safe_text(name, 80, fallback="[dompet disensor]")
        safe[safe_name] = {field: _safe_int(info_dict.get(field)) for field in fields}
    return safe


def _safe_hutang_row(row: Dict[str, Any]) -> Dict[str, Any]:
    row = row if isinstance(row, dict) else {}
    return {
        "tanggal": _safe_text(row.get("tanggal"), 32, fallback="[tanggal disensor]"),
        "amount": _safe_int(row.get("amount")),
        "keterangan": _safe_text(row.get("keterangan"), 180, fallback="[deskripsi disensor]"),
        "yang_hutang": _safe_text(row.get("yang_hutang"), 80, fallback="[dompet disensor]"),
        "yang_dihutangi": _safe_text(row.get("yang_dihutangi"), 80, fallback="[dompet disensor]"),
        "status": _safe_text(row.get("status"), 20, fallback="[status disensor]"),
    }


def _retrieval_context(question: str, plan: Dict[str, Any], supplied_rows: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    ast = plan["ast"]
    days = plan["period_days"]
    requested_dompet = resolve_dompet_from_text(
        ast["filters"].get("dompet") or question
    )
    question_norm = str(question or "").casefold()
    needs_wallet_balance = any(word in question_norm for word in ("saldo", "balance", "sisa"))

    if plan["intent"] == "debt":
        debt_summary = get_hutang_summary(days=days or 0)
        debt_facts = {"summary": debt_summary}
        if requested_dompet:
            borrower_rows = find_open_hutang(yang_hutang=requested_dompet)
            lender_rows = find_open_hutang(yang_dihutangi=requested_dompet)
            borrower_total = sum(_safe_int(row.get("amount")) for row in borrower_rows)
            lender_total = sum(_safe_int(row.get("amount")) for row in lender_rows)
            debt_facts["position"] = {
                "dompet": requested_dompet,
                "borrower_total": borrower_total,
                "lender_total": lender_total,
                "net": lender_total - borrower_total,
                "borrower_count": len(borrower_rows),
                "lender_count": len(lender_rows),
                "borrower_rows": [_safe_hutang_row(row) for row in borrower_rows],
                "lender_rows": [_safe_hutang_row(row) for row in lender_rows],
            }
        return {
            "intent": plan["intent"],
            "period_days": days,
            "period_row_count": 0,
            "period_stats": {"metric": "count", "value": 0, "row_count": 0, "groups": {}},
            "historical_row_count": 0,
            "historical_stats": None,
            "evidence": [],
            "debt": debt_facts,
            "question": question,
        }

    period_rows = list(supplied_rows) if supplied_rows is not None else get_all_data(days)
    if plan["intent"] == "project_activity":
        period_rows = [row for row in period_rows if _is_real_project(row)]

    period_selected = select_rows(ast, period_rows)
    historical_rows: List[Dict[str, Any]] = []
    historical_selected: List[Dict[str, Any]] = []
    if days is not None and not period_selected:
        historical_rows = get_all_data(None)
        if plan["intent"] == "project_activity":
            historical_rows = [row for row in historical_rows if _is_real_project(row)]
        historical_selected = select_rows(ast, historical_rows)

    selected = period_selected or historical_selected
    selected = sorted(
        selected,
        key=lambda row: str(row.get("tanggal") or ""),
        reverse=True,
    )
    stats = execute(ast, period_selected)
    historical_stats = execute(ast, historical_selected) if historical_selected else None
    facts = {
        "intent": plan["intent"],
        "period_days": days,
        "period_row_count": len(period_selected),
        "period_stats": stats,
        "historical_row_count": len(historical_selected),
        "historical_stats": historical_stats,
        "evidence": [_safe_row(row) for row in selected[:MAX_EVIDENCE_ROWS]],
        "question": question,
    }
    if needs_wallet_balance:
        facts["wallet_balances"] = _safe_wallet_balances(
            get_wallet_balances(), requested_dompet=requested_dompet
        )
    return facts


def _answer_from_facts(question: str, facts: Dict[str, Any]) -> str:
    system = """You answer an Indonesian finance question using only the supplied FACTS.
The numbers in FACTS were calculated by Python and are authoritative.
Never invent a transaction, amount, project, date, or explanation.
If period_row_count is 0 but historical_row_count is positive, clearly say there is no activity in the requested period and label historical facts separately.
For saldo/balance questions, use wallet_balances as authoritative; do not derive saldo from period_stats.
For debt questions, use debt.summary or debt.position as authoritative; do not infer debt from transaction evidence.
Answer naturally and directly in Indonesian for WhatsApp. Do not output a generic report template, do not say 'Hasil:', do not expose JSON/tags, and do not offer unrelated slash commands.
Use short paragraphs or bullets only when they make the answer easier to read. Mention the evidence (date, amount, description) when the user asks for detail."""
    response = call_groq_api(
        model=QUERY_MODEL,
        temperature=0.1,
        max_tokens=800,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps({"question": question, "facts": facts}, ensure_ascii=False),
            },
        ],
    )
    return response.choices[0].message.content.strip()


def handle_nl_query(
    question: str,
    rows: Optional[Iterable[Dict[str, Any]]] = None,
    default_days: Optional[int] = 30,
) -> Optional[str]:
    """Plan -> retrieve -> calculate -> answer, with safe fallback to legacy routing."""
    if detect_prompt_injection(question or "")[0]:
        logger.warning("Query agent rejected prompt-injection input")
        return None
    plan_started = time.perf_counter()
    try:
        raw_plan = _ask_llm_for_plan(question, default_days)
        plan = _normalize_plan(raw_plan, default_days)
    except Exception as exc:
        logger.warning("Query agent planning failed: %s", type(exc).__name__)
        return None
    finally:
        log_timing("query_agent.plan", plan_started)

    if plan["intent"] == "unknown":
        return None

    retrieval_started = time.perf_counter()
    try:
        facts = _retrieval_context(question, plan, supplied_rows=rows)
    except Exception as exc:
        logger.warning("Query agent retrieval failed: %s", type(exc).__name__)
        return None
    finally:
        log_timing("query_agent.retrieve", retrieval_started, intent=plan["intent"])

    answer_started = time.perf_counter()
    try:
        answer = _answer_from_facts(question, facts)
        log_event("query_agent", {
            "question": (question or "")[:120],
            "intent": plan["intent"],
            "period_rows": facts["period_row_count"],
            "historical_rows": facts["historical_row_count"],
        })
        return answer or None
    except Exception as exc:
        logger.warning("Query agent answer failed: %s", type(exc).__name__)
        return None
    finally:
        log_timing("query_agent.answer", answer_started)
