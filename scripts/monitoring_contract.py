#!/usr/bin/env python3
"""Validate and evaluate the versioned Hollawall numeric monitoring contract."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "hollawall.monitoring/v1"
ALERT_SCHEMA = "hollawall.monitoring-alert/v1"
REQUIRED_SIGNALS = frozenset(
    {"inbox", "export", "error", "api", "backup", "review", "wuzapi", "presensi"}
)
UNITS = frozenset({"count", "ratio", "seconds", "milliseconds"})


class MonitoringContractError(RuntimeError):
    """Raised when monitoring configuration or observations are invalid."""


def _number(value: object, *, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MonitoringContractError(f"{field} must be numeric")
    if not math.isfinite(value):
        raise MonitoringContractError(f"{field} must be a finite number")
    return value


def validate_contract(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise MonitoringContractError("monitoring schema is unsupported")
    signals = value.get("signals")
    if not isinstance(signals, dict) or set(signals) != REQUIRED_SIGNALS:
        raise MonitoringContractError("monitoring signals must exactly match the release contract")
    for name, signal in signals.items():
        if not isinstance(signal, dict):
            raise MonitoringContractError(f"{name} signal must be an object")
        if set(signal) != {"metric", "unit", "window_seconds", "warning", "critical"}:
            raise MonitoringContractError(f"{name} signal fields are invalid")
        if not isinstance(signal["metric"], str) or not signal["metric"].strip():
            raise MonitoringContractError(f"{name}.metric must be a non-empty string")
        if signal["unit"] not in UNITS:
            raise MonitoringContractError(f"{name}.unit is unsupported")
        window = signal["window_seconds"]
        if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
            raise MonitoringContractError(f"{name}.window_seconds must be a positive integer")
        warning = _number(signal["warning"], field=f"{name}.warning")
        critical = _number(signal["critical"], field=f"{name}.critical")
        if warning < 0 or critical <= warning:
            raise MonitoringContractError(f"{name} thresholds must satisfy 0 <= warning < critical")
    return value


def load_contract(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MonitoringContractError("monitoring contract cannot be read") from error
    return validate_contract(payload)


def evaluate(contract: Mapping[str, Any], signal: str, value: object) -> dict[str, object]:
    validated = validate_contract(dict(contract))
    if signal not in REQUIRED_SIGNALS:
        raise MonitoringContractError(f"unknown monitoring signal: {signal}")
    observation = _number(value, field="observation")
    configured = validated["signals"][signal]
    if observation >= configured["critical"]:
        severity = "critical"
        threshold = configured["critical"]
    elif observation >= configured["warning"]:
        severity = "warning"
        threshold = configured["warning"]
    else:
        severity = "ok"
        threshold = configured["warning"]
    return {
        "schema": ALERT_SCHEMA,
        "signal": signal,
        "severity": severity,
        "value": observation,
        "threshold": threshold,
        "window_seconds": configured["window_seconds"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--signal", choices=sorted(REQUIRED_SIGNALS))
    parser.add_argument("--value", type=float)
    args = parser.parse_args()
    contract = load_contract(args.contract)
    if args.signal is None and args.value is None:
        print(json.dumps({"schema": contract["schema"], "signals": sorted(contract["signals"]), "valid": True}))
        return
    if args.signal is None or args.value is None:
        parser.error("--signal and --value must be provided together")
    print(json.dumps(evaluate(contract, args.signal, args.value), sort_keys=True))


if __name__ == "__main__":
    main()
