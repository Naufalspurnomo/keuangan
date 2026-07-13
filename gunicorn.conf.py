"""Gunicorn lifecycle hooks for production workers."""


def post_worker_init(_worker):
    from main import start_background_workers

    start_background_workers()
