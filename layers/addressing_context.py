"""
Addressing context helpers.

Compatibility wrapper around layers.context_detector. New imports should use
this module name to avoid confusion with transaction scope detection.
"""

from .context_detector import *  # noqa: F401,F403
