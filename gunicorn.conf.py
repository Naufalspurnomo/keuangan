"""Gunicorn lifecycle hooks for production workers."""


def post_worker_init(_worker):
    from main import start_background_workers

    from main import app

    pool = app.extensions.get("postgres_connection_pool")
    if pool is not None:
        pool.open()
    start_background_workers()
