"""Pytest-only environment defaults.

Production still fails closed when GROQ_API_KEY is absent. This synthetic value only
allows modules to import before tests replace all provider calls with mocks.
"""

import os

os.environ.setdefault("GROQ_API_KEY", "pytest-synthetic-groq-key")
