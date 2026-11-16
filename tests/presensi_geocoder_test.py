from __future__ import annotations

import json
from datetime import UTC, datetime

from services import presensi_geocoder as geocoder


class FakeResponse:
    def __init__(self, status_code=200, payload=None, *, headers=None):
        self.status_code = status_code
        self._body = json.dumps(payload or {}).encode("utf-8")
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(self._body)),
            **(headers or {}),
        }
        self.closed = False

    def iter_content(self, chunk_size=8192):
        del chunk_size
        yield self._body

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response

    def close(self):
        self.closed = True


class FakeCoordinator:
    def __init__(self, reserve_result=("", True)):
        self.reserve_result = reserve_result
        self.reservations = []
        self.stores = []

    def reserve(self, provider, location_key, now):
        self.reservations.append((provider, location_key, now))
        return self.reserve_result

    def store(self, provider, location_key, result, now):
        self.stores.append((provider, location_key, result, now))


def test_reverse_geocode_uses_coarse_coordinates_shared_reservation_and_attributed_label(monkeypatch):
    monkeypatch.setenv("PRESENSI_GEOCODER_PROVIDER", "nominatim")
    monkeypatch.setenv("PRESENSI_GEOCODER_URL", "https://nominatim.openstreetmap.org/reverse")
    instant = datetime(2026, 11, 16, tzinfo=UTC)
    coordinator = FakeCoordinator()
    response = FakeResponse(200, {
        "address": {
            "suburb": "Tunjungan",
            "city": "Surabaya",
            "state": "Jawa Timur",
            "country": "Indonesia",
        }
    })
    session = FakeSession(response)

    label = geocoder.reverse_geocode(
        -7.2575123,
        112.7521234,
        coordinator=coordinator,
        session_factory=lambda: session,
        now=lambda: instant,
    )

    assert label == "Tunjungan, Surabaya, Jawa Timur"
    assert coordinator.reservations == [("nominatim", "-7.258,112.752", instant)]
    assert len(coordinator.stores) == 1
    assert coordinator.stores[0][0:2] == ("nominatim", "-7.258,112.752")
    assert coordinator.stores[0][2].outcome == "found"
    url, kwargs = session.calls[0]
    assert url == "https://nominatim.openstreetmap.org/reverse"
    assert kwargs["params"]["lat"] == "-7.258"
    assert kwargs["params"]["lon"] == "112.752"
    assert session.closed is True
    assert response.closed is True


def test_shared_cache_hit_skips_external_request(monkeypatch):
    monkeypatch.setenv("PRESENSI_GEOCODER_PROVIDER", "nominatim")
    coordinator = FakeCoordinator(("Bojonggede, Jawa Barat", False))

    label = geocoder.reverse_geocode(
        -6.493,
        106.795,
        coordinator=coordinator,
        session_factory=lambda: (_ for _ in ()).throw(AssertionError("network must not run")),
    )

    assert label == "Bojonggede, Jawa Barat"
    assert coordinator.stores == []


def test_disabled_provider_keeps_coordinate_fallback_without_database_or_network(monkeypatch):
    monkeypatch.setenv("PRESENSI_GEOCODER_PROVIDER", "disabled")
    coordinator = FakeCoordinator()

    label = geocoder.reverse_geocode(
        -6.493,
        106.795,
        coordinator=coordinator,
        session_factory=lambda: (_ for _ in ()).throw(AssertionError("network must not run")),
    )

    assert label == ""
    assert coordinator.reservations == []


def test_nominatim_429_returns_bounded_shared_backoff():
    response = FakeResponse(429, {}, headers={"Retry-After": "9999"})
    session = FakeSession(response)

    result = geocoder._lookup_nominatim(
        -7.258,
        112.752,
        session=session,
        url="https://nominatim.openstreetmap.org/reverse",
    )

    assert result == geocoder.LookupResult("", "error", 300)
    assert response.closed is True
