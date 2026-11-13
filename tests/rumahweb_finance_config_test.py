from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "configure_rumahweb_admin_finance.py"


def load_module():
    spec = importlib.util.spec_from_file_location("finance_config", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finance_config_replaces_only_expected_values() -> None:
    module = load_module()
    original = """<?php
return [
  'upstream_canonical_transactions_url' => '',
  'canonical_finance_writes_enabled' => false,
  'dashboard_actor_assertion_audience' => '',
  'dashboard_actor_assertion_secret' => '',
  'owner_email' => 'owner@example.com',
];
"""
    updated = module.replace_php_value(
        original,
        "upstream_canonical_transactions_url",
        module.DEFAULT_CANONICAL_URL,
    )
    updated = module.replace_php_value(
        updated,
        "dashboard_actor_assertion_audience",
        module.DEFAULT_AUDIENCE,
    )
    updated = module.replace_php_value(
        updated,
        "dashboard_actor_assertion_secret",
        "x" * 48,
    )
    updated = module.replace_php_bool(updated, "canonical_finance_writes_enabled", True)

    assert module.DEFAULT_CANONICAL_URL in updated
    assert "'canonical_finance_writes_enabled' => true" in updated
    assert "'dashboard_actor_assertion_audience' => 'hollawall-finance-api'" in updated
    assert "'dashboard_actor_assertion_secret' => '" + ("x" * 48) + "'" in updated
    assert "'owner_email' => 'owner@example.com'" in updated


def test_finance_config_fails_closed_for_missing_or_duplicate_keys() -> None:
    module = load_module()
    for source in (
        "<?php return [];",
        "'canonical_finance_writes_enabled' => false, 'canonical_finance_writes_enabled' => true,",
    ):
        try:
            module.replace_php_bool(source, "canonical_finance_writes_enabled", True)
        except RuntimeError:
            pass
        else:
            raise AssertionError("unsafe config must fail closed")
