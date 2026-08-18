# Finance Agent Layer

Bot now has a finance-agent planning layer before the legacy extractor.

## Contract

The agent may:

- read message text and structured bank fields,
- read cached spreadsheet context such as known projects,
- produce a structured transaction plan,
- ask for fallback when confidence is low.

The agent may not:

- write to Google Sheets directly,
- bypass `validate_transaction_data`,
- choose a wallet/dompet silently when the text does not mention one,
- invent project names from nothing.

Execution still goes through the existing deterministic validation, pending flow,
wallet selection, duplicate checks, and Sheets append code.

## Flow

1. `extract_from_text()` sanitizes the message.
2. `services.finance_agent.plan_finance_message()` runs first.
3. If the agent returns a high-confidence `PROCESS` decision, its transactions
   enter the existing validator.
4. If the agent is uncertain, errors, or returns low confidence, legacy Groq
   extraction runs as fallback.
5. The existing main flow handles missing project/wallet/amount prompts.

## Environment

- `FINANCE_AGENT_ENABLED=true` enables the layer. Set `false` to disable.
- `FINANCE_AGENT_MODE=hybrid` controls rollout:
  - `off`: agent disabled, legacy extractor only.
  - `deterministic`: only structured deterministic parsing, no agent LLM call.
  - `hybrid`: deterministic parser first, then LLM planner for unstructured text.
  - `shadow`: agent plans/logs, but its output is not accepted for execution.
- `FINANCE_AGENT_SHEET_CONTEXT=true` lets the agent read cached project context.
- `FINANCE_AGENT_MIN_CONFIDENCE=0.78` controls acceptance threshold.
- `FINANCE_AGENT_MODEL=openai/gpt-oss-20b` controls the planner model.

## Safety Gates

- Structured `/catat` bank messages are parsed deterministically first.
- Amount parsing supports `480,000.00`, `480.000,00`, and plain IDR numbers.
- Agent output must pass `validate_transaction_data`.
- Agent output is accepted only when every planned transaction has valid date,
  amount, type, and description. Missing project is allowed because the existing
  pending flow can ask the user for it.
- If wallet/dompet is unclear, the existing confirmation flow must ask the user.

## Replay Tests

Real bug examples should be added as tests under `tests/`.
Current coverage includes:

- `/catat` group command detection,
- `Kategori sementara: Perlu Review` not being treated as future plan,
- `Nominal: 480,000.00` parsed as `480000`,
- deterministic finance-agent parsing of bank-form messages,
- LLM-agent JSON schema coercion.
- missing-date agent plans not accepted for execution,
- shadow/deterministic rollout behavior,
- partial multi-transaction plans rejected.
