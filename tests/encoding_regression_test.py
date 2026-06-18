from pathlib import Path


MOJIBAKE_MARKERS = (
    chr(0x00C3),  # repeated UTF-8 misdecode marker
    chr(0x00C2),  # extra-byte mojibake marker
    chr(0x00E2) + "€",  # cp1252 punctuation/emoji mojibake prefix
)


USER_FACING_FILES = [
    "main.py",
    "config/errors.py",
    "handlers/pending_handler.py",
    "handlers/revision_handler.py",
    "handlers/smart_handler.py",
    "handlers/telegram_webhook.py",
    "handlers/wuzapi_webhook.py",
    "services/hutang_flow.py",
]


def test_user_facing_messages_do_not_contain_mojibake_markers():
    """Guard against UTF-8 emoji text being saved as cp1252 mojibake."""
    for file_name in USER_FACING_FILES:
        text = Path(file_name).read_text(encoding="utf-8")

        assert not any(marker in text for marker in MOJIBAKE_MARKERS), file_name


def test_main_whatsapp_prompt_text_stays_readable():
    text = Path("main.py").read_text(encoding="utf-8")

    assert "🔍 Scan..." in text
    assert "📁 *PROJECT BARU*" in text
    assert "↩️ Reply angka 1-5" in text


def test_fallback_messages_do_not_expose_internal_error_labels():
    combined = "\n".join(
        Path(file_name).read_text(encoding="utf-8")
        for file_name in USER_FACING_FILES
    )

    assert "????" not in combined
    assert "System Error" not in combined
    assert "Error state" not in combined
    assert "Error sistem" not in combined
    assert "Jawaban angka di grup wajib" not in combined
