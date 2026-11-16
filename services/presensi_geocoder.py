"""Shared, privacy-minimized reverse geocoding for presensi captions."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests

_PROVIDER = "nominatim"
_LOCK_ID = 0x50524553474F43  # stable "PRESGOC" advisory-lock namespace
_MAX_RESPONSE_BYTES = 65_536
_DEFAULT_URL = "https://nominatim.openstreetmap.org/reverse"


@dataclass(frozen=True)
class LookupResult:
    label: str
    outcome: str
    retry_after_seconds: int = 0


def _database_url() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def _provider() -> str:
    value = str(os.getenv("PRESENSI_GEOCODER_PROVIDER", _PROVIDER)).strip().casefold()
    return value if value in {_PROVIDER, "disabled"} else "disabled"


def _provider_url() -> str:
    value = str(os.getenv("PRESENSI_GEOCODER_URL", _DEFAULT_URL)).strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return ""
    return value


def _coarse_coordinate(value: float) -> float:
    return round(value, 3)


def _location_key(latitude: float, longitude: float) -> tuple[str, float, float]:
    lat = _coarse_coordinate(latitude)
    lon = _coarse_coordinate(longitude)
    return f"{lat:.3f},{lon:.3f}", lat, lon


def _location_part(address: Any, *keys: str) -> str:
    if not isinstance(address, dict):
        return ""
    for key in keys:
        value = str(address.get(key) or "").strip()
        if value and len(value) <= 120 and not any(ord(char) < 32 or ord(char) == 127 for char in value):
            return value
    return ""


def _format_label(payload: Any) -> str:
    address = payload.get("address") if isinstance(payload, dict) else None
    locality = _location_part(address, "neighbourhood", "quarter", "suburb", "village")
    city = _location_part(address, "city", "town", "municipality", "county", "city_district")
    state = _location_part(address, "state")
    country = _location_part(address, "country")
    parts: list[str] = []
    for part in (locality, city, state):
        if part and part.casefold() not in {item.casefold() for item in parts}:
            parts.append(part)
    if country and country.casefold() != "indonesia" and country.casefold() not in {item.casefold() for item in parts}:
        parts.append(country)
    return ", ".join(parts)[:300]


def _bounded_json(response: Any) -> Any:
    content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().casefold()
    if content_type not in {"application/json", "application/geo+json"}:
        raise ValueError("geocoder content type invalid")
    declared = str(response.headers.get("Content-Length") or "").strip()
    if declared and int(declared) > _MAX_RESPONSE_BYTES:
        raise ValueError("geocoder response too large")
    body = bytearray()
    for chunk in response.iter_content(chunk_size=8192):
        body.extend(chunk)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("geocoder response too large")
    return json.loads(bytes(body).decode("utf-8"))


def _retry_after(response: Any) -> int:
    try:
        value = int(str(response.headers.get("Retry-After") or "60").strip())
    except ValueError:
        value = 60
    return min(max(value, 5), 300)


def _lookup_nominatim(
    latitude: float,
    longitude: float,
    *,
    session: Any,
    url: str,
) -> LookupResult:
    response = None
    try:
        response = session.get(
            url,
            params={
                "format": "jsonv2",
                "lat": f"{latitude:.3f}",
                "lon": f"{longitude:.3f}",
                "zoom": "14",
                "addressdetails": "1",
            },
            headers={
                "Accept": "application/json",
                "Accept-Language": "id",
                "User-Agent": "Hollawall-Presensi/1.0 (location evidence)",
            },
            timeout=(0.8, 1.2),
            allow_redirects=False,
            stream=True,
        )
        if response.status_code == 429:
            return LookupResult("", "error", _retry_after(response))
        if response.status_code == 404:
            return LookupResult("", "not_found")
        if response.status_code != 200:
            return LookupResult("", "error")
        label = _format_label(_bounded_json(response))
        return LookupResult(label, "found" if label else "not_found")
    except Exception:  # noqa: BLE001 - optional lookup must always fail open
        return LookupResult("", "error")
    finally:
        if response is not None:
            response.close()


class GeocodeCoordinator(Protocol):
    def reserve(self, provider: str, location_key: str, now: datetime) -> tuple[str, bool]: ...
    def store(self, provider: str, location_key: str, result: LookupResult, now: datetime) -> None: ...


class PostgresGeocodeCoordinator:
    """Application-wide cache and request reservation using canonical PostgreSQL."""

    def __init__(self, dsn: str, *, connection_factory: Callable[[str], Any] | None = None) -> None:
        self._dsn = str(dsn or "").strip()
        self._connection_factory = connection_factory

    def _connect(self):
        if self._connection_factory is not None:
            return self._connection_factory(self._dsn)
        import psycopg

        return psycopg.connect(self._dsn)

    def reserve(self, provider: str, location_key: str, now: datetime) -> tuple[str, bool]:
        try:
            with self._connect() as connection:  # noqa: SIM117 - explicit DB contexts preserve fail-open handling
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_ID,))
                    cursor.execute(
                        """
                        SELECT label FROM presensi_geocode_cache
                        WHERE provider = %s AND location_key = %s AND expires_at > %s
                        """,
                        (provider, location_key, now),
                    )
                    cached = cursor.fetchone()
                    if cached is not None:
                        return str(cached[0] or ""), False
                    cursor.execute(
                        """
                        SELECT next_request_at <= %s
                        FROM presensi_geocode_rate_limits
                        WHERE provider = %s
                        FOR UPDATE
                        """,
                        (now, provider),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            "INSERT INTO presensi_geocode_rate_limits (provider, next_request_at) VALUES (%s, %s)",
                            (provider, now),
                        )
                    elif not bool(row[0]):
                        return "", False
                    cursor.execute(
                        """
                        UPDATE presensi_geocode_rate_limits
                        SET next_request_at = %s, updated_at = %s
                        WHERE provider = %s
                        """,
                        (now + timedelta(seconds=1.1), now, provider),
                    )
            return "", True
        except Exception:  # noqa: BLE001 - optional cache must fail open
            return "", False

    def store(self, provider: str, location_key: str, result: LookupResult, now: datetime) -> None:
        ttl = timedelta(days=30) if result.outcome == "found" else (
            timedelta(hours=1) if result.outcome == "not_found" else timedelta(minutes=5)
        )
        try:
            with self._connect() as connection:  # noqa: SIM117 - explicit DB contexts preserve fail-open handling
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO presensi_geocode_cache
                            (provider, location_key, label, outcome, expires_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (provider, location_key) DO UPDATE SET
                            label = EXCLUDED.label,
                            outcome = EXCLUDED.outcome,
                            expires_at = EXCLUDED.expires_at,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (provider, location_key, result.label, result.outcome, now + ttl, now),
                    )
                    if result.retry_after_seconds:
                        cursor.execute(
                            """
                            UPDATE presensi_geocode_rate_limits
                            SET next_request_at = GREATEST(next_request_at, %s), updated_at = %s
                            WHERE provider = %s
                            """,
                            (now + timedelta(seconds=result.retry_after_seconds), now, provider),
                        )
        except Exception:  # noqa: BLE001 - optional cache must fail open
            return


def reverse_geocode(
    latitude: float,
    longitude: float,
    *,
    coordinator: GeocodeCoordinator | None = None,
    session_factory: Callable[[], Any] = requests.Session,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    if (
        _provider() != _PROVIDER
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return ""
    dsn = _database_url()
    url = _provider_url()
    if not url or (coordinator is None and not dsn):
        return ""
    selected = coordinator or PostgresGeocodeCoordinator(dsn)
    key, coarse_latitude, coarse_longitude = _location_key(latitude, longitude)
    instant = now()
    cached, allowed = selected.reserve(_PROVIDER, key, instant)
    if not allowed:
        return cached
    session = session_factory()
    try:
        result = _lookup_nominatim(coarse_latitude, coarse_longitude, session=session, url=url)
    finally:
        session.close()
    selected.store(_PROVIDER, key, result, now())
    return result.label
