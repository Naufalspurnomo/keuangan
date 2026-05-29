"""
Transaction scope detection helpers.

Compatibility wrapper around utils.context_detector. New imports should use
this module name to distinguish project/operational classification from
reply/mention addressing context.
"""

from .context_detector import *  # noqa: F401,F403
