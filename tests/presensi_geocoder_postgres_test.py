from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.presensi_geocoder import (
    LookupResult,
    PostgresGeocodeCoordinator,
    _location_key,
)

DSN = os.getenv("PRESENSI_GEOCODER_TEST_DATABASE_URL", "")
ROOT = Path(__file__).parents[1]

pytestmark = pytest.mark.skipif(not DSN, reason="PRESENSI_GEOCODER_TEST_DATABASE_URL is required")


@pytest.fixture()
def coordinator():
    import psycopg

    migration = (ROOT / "dashboard_api/migrations/021_presensi_geocode_cache.sql").read_text(encoding="utf-8")
    with psycopg.connect(DSN, autocommit=True) as connection:
        connection.execute(migration)
        connection.execute("DELETE FROM presensi_geocode_cache WHERE provider = 'nominatim'")
        connection.execute(
            "UPDATE presensi_geocode_rate_limits SET next_request_at = '-infinity' WHERE provider = 'nominatim'"
        )
    yield PostgresGeocodeCoordinator(DSN)
    with psycopg.connect(DSN, autocommit=True) as connection:
        connection.execute("DELETE FROM presensi_geocode_cache WHERE provider = 'nominatim'")
        connection.execute(
            "UPDATE presensi_geocode_rate_limits SET next_request_at = '-infinity' WHERE provider = 'nominatim'"
        )


def test_shared_cache_uses_coarse_location_key_and_survives_worker_instances(coordinator):
    now = datetime(2026, 11, 16, tzinfo=UTC)
    key, latitude, longitude = _location_key(-7.2575123, 112.7521234)
    assert (key, latitude, longitude) == ("-7.258,112.752", -7.258, 112.752)

    cached, allowed = coordinator.reserve("nominatim", key, now)
    assert (cached, allowed) == ("", True)
    other_worker = PostgresGeocodeCoordinator(DSN)
    assert other_worker.reserve("nominatim", key, now) == ("", False)

    coordinator.store(
        "nominatim", key, LookupResult("Tunjungan, Surabaya, Jawa Timur", "found"), now
    )
    assert other_worker.reserve("nominatim", key, now + timedelta(seconds=2)) == (
        "Tunjungan, Surabaya, Jawa Timur",
        False,
    )


def test_negative_cache_and_429_backoff_are_shared(coordinator):
    now = datetime(2026, 11, 16, tzinfo=UTC)
    first_key = "-7.258,112.752"
    assert coordinator.reserve("nominatim", first_key, now) == ("", True)
    coordinator.store("nominatim", first_key, LookupResult("", "not_found"), now)
    assert PostgresGeocodeCoordinator(DSN).reserve(
        "nominatim", first_key, now + timedelta(seconds=2)
    ) == ("", False)

    second_key = "-6.200,106.817"
    assert coordinator.reserve("nominatim", second_key, now + timedelta(seconds=2)) == ("", True)
    coordinator.store(
        "nominatim", second_key, LookupResult("", "error", retry_after_seconds=120),
        now + timedelta(seconds=2),
    )
    assert PostgresGeocodeCoordinator(DSN).reserve(
        "nominatim", "-6.201,106.818", now + timedelta(seconds=30)
    ) == ("", False)
