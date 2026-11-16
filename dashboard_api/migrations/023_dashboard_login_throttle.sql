-- Shared, restart-safe login throttling for the private owner dashboard.
CREATE TABLE IF NOT EXISTS dashboard_login_throttle (
    key_hash TEXT PRIMARY KEY CHECK (key_hash ~ '^[0-9a-f]{64}$'),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    blocked_until BIGINT NOT NULL DEFAULT 0 CHECK (blocked_until >= 0),
    updated_at BIGINT NOT NULL CHECK (updated_at >= 0)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_login_throttle_cleanup
    ON dashboard_login_throttle(updated_at);
