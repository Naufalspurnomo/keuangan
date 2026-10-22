"""Pure dashboard filter contracts.

The module deliberately has no Flask or database dependency.  It is shared by
HTTP routes, deterministic metric builders, repository queries, and tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping, Optional

from config.wallets import DOMPET_COMPANIES, DOMPET_SHEETS


DASHBOARD_TIMEZONE = "Asia/Jakarta"
ALLOWED_PERIODS = {"this_month", "last_7_days", "today", "custom"}
ALLOWED_KEYS = {"period", "date_from", "date_to", "wallet", "company", "project"}
ALLOWED_COMPANIES = frozenset(
    company
    for companies in DOMPET_COMPANIES.values()
    for company in companies
)


class DashboardContractError(ValueError):
    """Raised when a client filter cannot be represented safely."""


@dataclass(frozen=True, slots=True)
class DashboardFilters:
    period: str
    date_from: date
    date_to: date
    timezone: str = DASHBOARD_TIMEZONE
    wallet: Optional[str] = None
    company: Optional[str] = None
    project: Optional[str] = None

    def to_query(self) -> dict[str, str]:
        query = {
            "period": self.period,
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
        }
        for key in ("wallet", "company", "project"):
            value = getattr(self, key)
            if value:
                query[key] = value
        return query


def _clean_optional(value: object) -> Optional[str]:
    cleaned = str(value or "").strip()
    if not cleaned or cleaned.lower() in {"all", "semua"}:
        return None
    return cleaned


def _parse_iso_date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise DashboardContractError(f"{field} must be an ISO date") from exc


def parse_filters(
    args: Mapping[str, object],
    *,
    today: Optional[date] = None,
    allowed_projects: Optional[Iterable[str]] = None,
) -> DashboardFilters:
    """Parse one canonical, inclusive dashboard filter set.

    Unknown keys and unknown canonical values fail closed.  The repository may
    obtain ``allowed_projects`` from the compact project index; an omitted
    project catalog means project filters are rejected instead of silently
    returning an empty dashboard.
    """

    unknown_keys = set(args) - ALLOWED_KEYS
    if unknown_keys:
        raise DashboardContractError(
            "unsupported filter(s): " + ", ".join(sorted(unknown_keys))
        )

    current = today or date.today()
    period = str(args.get("period") or "this_month").strip().lower()
    if period not in ALLOWED_PERIODS:
        raise DashboardContractError("unsupported period")

    if period == "custom":
        if not args.get("date_from") or not args.get("date_to"):
            raise DashboardContractError("custom period requires date_from and date_to")
        date_from = _parse_iso_date(args.get("date_from"), "date_from")
        date_to = _parse_iso_date(args.get("date_to"), "date_to")
    elif period == "today":
        date_from = date_to = current
    elif period == "last_7_days":
        date_from = current - timedelta(days=6)
        date_to = current
    else:
        date_from = current.replace(day=1)
        date_to = current

    if date_from > date_to:
        raise DashboardContractError("date_from cannot be after date_to")

    wallet = _clean_optional(args.get("wallet"))
    company = _clean_optional(args.get("company"))
    project = _clean_optional(args.get("project"))

    if wallet and wallet not in DOMPET_SHEETS:
        raise DashboardContractError("unknown wallet")
    if company and company not in ALLOWED_COMPANIES:
        raise DashboardContractError("unknown company")
    if project:
        catalog = frozenset(str(item).strip() for item in (allowed_projects or ()) if str(item).strip())
        if project not in catalog:
            raise DashboardContractError("unknown project")

    return DashboardFilters(
        period=period,
        date_from=date_from,
        date_to=date_to,
        wallet=wallet,
        company=company,
        project=project,
    )
