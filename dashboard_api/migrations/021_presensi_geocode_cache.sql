CREATE TABLE IF NOT EXISTS presensi_geocode_cache (
    provider TEXT NOT NULL,
    location_key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL CHECK (outcome IN ('found', 'not_found', 'error')),
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, location_key),
    CHECK (char_length(provider) BETWEEN 1 AND 40),
    CHECK (char_length(location_key) BETWEEN 3 AND 64),
    CHECK (char_length(label) <= 300)
);

CREATE INDEX IF NOT EXISTS presensi_geocode_cache_expiry_idx
    ON presensi_geocode_cache (expires_at);

CREATE TABLE IF NOT EXISTS presensi_geocode_rate_limits (
    provider TEXT PRIMARY KEY,
    next_request_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (char_length(provider) BETWEEN 1 AND 40)
);

INSERT INTO presensi_geocode_rate_limits (provider)
VALUES ('nominatim')
ON CONFLICT (provider) DO NOTHING;
