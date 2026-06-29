"""
utils/ - Shared Utilities Module

Keep package imports light. Submodules such as utils.parsers must not import
formatter/Sheets dependencies just because the package is initialized.
"""

_FORMATTER_EXPORTS = {
    "format_success_reply",
    "format_success_reply_new",
    "format_mention",
    "build_selection_prompt",
    "START_MESSAGE",
    "HELP_MESSAGE",
    "CATEGORIES_DISPLAY",
    "SELECTION_DISPLAY",
    "GROUP_TRIGGERS",
}

_PARSER_EXPORTS = {
    "parse_selection",
    "parse_revision_amount",
    "should_respond_in_group",
    "pending_key",
    "pending_is_expired",
    "is_command_match",
    "is_prefix_match",
}

__all__ = sorted(_FORMATTER_EXPORTS | _PARSER_EXPORTS)


def __getattr__(name):
    if name in _FORMATTER_EXPORTS:
        from . import formatters

        return getattr(formatters, name)
    if name in _PARSER_EXPORTS:
        from . import parsers

        return getattr(parsers, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
