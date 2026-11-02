"""Pure validation contract for dashboard transaction write requests.

No route bindings, I/O, network access, or production mutation belong here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from config.constants import OPERATIONAL_CATEGORIES
from config.wallets import DOMPET_COMPANIES
from security import ALLOWED_CATEGORIES

MAX_SAFE_INTEGER = 9_007_199_254_740_991
DASHBOARD_TIMEZONE = ZoneInfo("Asia/Jakarta")
DIRECTIONS = frozenset({"Pemasukan", "Pengeluaran"})
SCOPES = frozenset({"project", "office"})
FORMULA_PREFIXES = ("=", "+", "-", "@")

# These values come from the runtime Sheets configuration rather than a second
# dashboard-specific catalog.
WALLET_COMPANY_PAIRS = frozenset(
    (wallet, company)
    for wallet, companies in DOMPET_COMPANIES.items()
    for company in companies
)
PROJECT_CATEGORIES = frozenset(ALLOWED_CATEGORIES)
OFFICE_CATEGORIES = frozenset(OPERATIONAL_CATEGORIES)

REQUIRED_FIELDS = frozenset(
    {
        "idempotency_key",
        "date",
        "scope",
        "direction",
        "amount",
        "description",
        "wallet",
        "company",
        "category",
    }
)
OPTIONAL_FIELDS = frozenset({"project"})
TEXT_LIMITS = {
    "description": 200,
    "wallet": 100,
    "company": 100,
    "category": 100,
    "project": 100,
}


class TransactionValidationError(ValueError):
    """A request cannot be represented safely by the current ledger writers."""


@dataclass(frozen=True, slots=True)
class TransactionRequest:
    """Canonical immutable request accepted by the dashboard write boundary."""

    idempotency_key: str
    date: date
    scope: str
    direction: str
    amount: int
    description: str
    wallet: str
    company: str
    category: str
    project: str | None


ProjectExists = Callable[[str], bool]


def _fail(field: str, reason: str) -> NoReturn:
    raise TransactionValidationError(f"{field}: {reason}")


def _validate_text(
    payload: Mapping[str, Any],
    field: str,
    *,
    limit: int | None = None,
) -> str:
    value = payload[field]
    if not isinstance(value, str):
        _fail(field, "must be a string")
    if value != value.strip():
        _fail(field, "must not have leading or trailing whitespace")
    maximum = limit if limit is not None else TEXT_LIMITS[field]
    if not 1 <= len(value) <= maximum:
        _fail(field, f"length must be 1..{maximum}")
    if value.startswith(FORMULA_PREFIXES):
        _fail(field, "must not start with =, +, -, or @")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail(field, "must not contain control characters")
    return value


def _today_jakarta() -> date:
    return datetime.now(DASHBOARD_TIMEZONE).date()


def _validate_idempotency_key(value: Any) -> str:
    if not isinstance(value, str):
        _fail("idempotency_key", "must be a string")
    if not 16 <= len(value) <= 128:
        _fail("idempotency_key", "length must be 16..128")
    if value != value.strip() or any(character.isspace() for character in value):
        _fail("idempotency_key", "must be opaque printable text without whitespace")
    if not value.isprintable():
        _fail("idempotency_key", "must be opaque printable text without whitespace")
    return value


def _validate_date(value: Any, current_date: date) -> date:
    if not isinstance(value, str):
        _fail("date", "must be an ISO date string")
    try:
        request_date = date.fromisoformat(value)
    except ValueError:
        _fail("date", "must be a valid ISO date in YYYY-MM-DD format")
    if value != request_date.isoformat():
        _fail("date", "must use canonical ISO format YYYY-MM-DD")
    if request_date != current_date:
        _fail("date", "must be the current Asia/Jakarta date")
    return request_date


def validate_transaction_request(
    payload: Mapping[str, Any],
    *,
    project_exists: ProjectExists,
    today: Callable[[], date] = _today_jakarta,
) -> TransactionRequest:
    """Validate one dashboard transaction request without performing any I/O.

    ``project_exists`` receives the canonical project string so callers can
    inject a preloaded catalog. It must not perform network I/O inside this
    validator.
    """

    if not isinstance(payload, Mapping):
        raise TransactionValidationError("request: must be an object")

    keys = frozenset(payload)
    unknown = sorted(keys - REQUIRED_FIELDS - OPTIONAL_FIELDS)
    if unknown:
        raise TransactionValidationError(f"unknown field(s): {', '.join(unknown)}")
    missing = sorted(REQUIRED_FIELDS - keys)
    if missing:
        raise TransactionValidationError(f"missing field(s): {', '.join(missing)}")

    idempotency_key = _validate_idempotency_key(payload["idempotency_key"])

    current_date = today()
    if not isinstance(current_date, date) or isinstance(current_date, datetime):
        raise TypeError("today must return datetime.date")
    request_date = _validate_date(payload["date"], current_date)

    scope = payload["scope"]
    if not isinstance(scope, str) or scope not in SCOPES:
        _fail("scope", "must be project or office")

    direction = payload["direction"]
    if not isinstance(direction, str) or direction not in DIRECTIONS:
        _fail("direction", "must be Pemasukan or Pengeluaran")
    if scope == "office" and direction != "Pengeluaran":
        _fail("direction", "office transactions must be Pengeluaran")

    amount = payload["amount"]
    if isinstance(amount, bool) or not isinstance(amount, int):
        _fail("amount", "must be an exact integer; booleans and decimals are not allowed")
    if not 1 <= amount <= MAX_SAFE_INTEGER:
        _fail("amount", f"must be between 1 and {MAX_SAFE_INTEGER}")

    description = _validate_text(
        payload,
        "description",
        limit=150 if scope == "office" else TEXT_LIMITS["description"],
    )
    wallet = _validate_text(payload, "wallet")
    company = _validate_text(payload, "company")
    category = _validate_text(payload, "category")
    if (wallet, company) not in WALLET_COMPANY_PAIRS:
        _fail("wallet", "unknown wallet/company combination")

    project: str | None = None
    if scope == "project":
        if "project" not in payload:
            _fail("project", "is required for project scope")
        project = _validate_text(payload, "project")
        try:
            exists = project_exists(project)
        except Exception as exc:
            raise TransactionValidationError("project: existence validation failed") from exc
        if not isinstance(exists, bool):
            raise TypeError("project_exists must return bool")
        if not exists:
            _fail("project", "does not exist for wallet/company")
        if category not in PROJECT_CATEGORIES:
            _fail("category", "is not an operational project category")
    else:
        if "project" in payload:
            _fail("project", "must be omitted for office scope")
        if category not in OFFICE_CATEGORIES:
            _fail("category", "is not an operational office expense category")

    return TransactionRequest(
        idempotency_key=idempotency_key,
        date=request_date,
        scope=scope,
        direction=direction,
        amount=amount,
        description=description,
        wallet=wallet,
        company=company,
        category=category,
        project=project,
    )
