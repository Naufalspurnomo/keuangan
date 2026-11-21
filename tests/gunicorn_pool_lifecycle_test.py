from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_post_worker_init_warms_pool_before_starting_background_workers(monkeypatch) -> None:
    events: list[str] = []
    pool = type("Pool", (), {"open": lambda self: events.append("pool")})()
    main = type("Main", (), {
        "app": type("App", (), {"extensions": {"postgres_connection_pool": pool}})(),
        "start_background_workers": lambda: events.append("workers"),
    })
    monkeypatch.setitem(__import__("sys").modules, "main", main)

    spec = importlib.util.spec_from_file_location("gunicorn_pool_test", ROOT / "gunicorn.conf.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    module.post_worker_init(object())

    assert events == ["pool", "workers"]
