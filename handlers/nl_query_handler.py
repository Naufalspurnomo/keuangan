"""Natural language query: LLM -> AST -> deterministic calculation."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from ai_helper import groq_client
from agent_core.audit_log import log_event
from agent_core.query_engine import execute, format_idr, parse_ast


logger = logging.getLogger(__name__)


def _extract_json_object(text: str) -> Dict:
    start = (text or "").find("{")
    end = (text or "").rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM did not return JSON")
    return json.loads(text[start:end + 1])


def _ask_llm_for_ast(question: str) -> Dict:
    today = datetime.now().date().isoformat()
    system = (
        "Convert an Indonesian finance question into JSON only. "
        f"Today is {today}. "
        "Schema: {\"metric\":\"sum|count|avg|max|min\","
        "\"filters\":{\"project\":null,\"category\":null,"
        "\"tipe\":\"Pemasukan|Pengeluaran|null\","
        "\"date_from\":\"YYYY-MM-DD|null\",\"date_to\":\"YYYY-MM-DD|null\"},"
        "\"group_by\":null}. "
        "Do not calculate numbers. Empty filters must be null."
    )
    response = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        response_format={"type": "json_object"},
    )
    return _extract_json_object(response.choices[0].message.content)


def _format_value(metric: str, value) -> str:
    if metric == "count":
        return f"{int(value or 0)} transaksi"
    return format_idr(value)


def handle_nl_query(question: str, rows: List[Dict]) -> Optional[str]:
    try:
        ast = parse_ast(_ask_llm_for_ast(question))
        result = execute(ast, rows)
    except Exception as exc:
        error_type = type(exc).__name__
        logger.warning("NL query fallback: %s", error_type)
        log_event("nl_query_fallback", {
            "question": (question or "")[:120],
            "error_type": error_type,
        })
        return None

    log_event("nl_query", {"question": (question or "")[:120], "ast": ast, "result": result})

    metric = result.get("metric", "sum")
    answer = f"Hasil: {_format_value(metric, result.get('value'))} ({result.get('row_count', 0)} transaksi)"
    groups = result.get("groups") or {}
    if groups:
        answer += "\n" + "\n".join(
            f"- {key}: {_format_value(metric, value)}"
            for key, value in groups.items()
        )
    return answer
