from pathlib import Path


MOJIBAKE_MARKERS = (
    chr(0x00C3),  # repeated UTF-8 misdecode marker
    chr(0x00C2),  # extra-byte mojibake marker
    chr(0x00E2) + "€",  # cp1252 punctuation/emoji mojibake prefix
)


def test_main_whatsapp_messages_do_not_contain_mojibake_markers():
    """Guard against UTF-8 emoji text being saved as cp1252 mojibake."""
    text = Path("main.py").read_text(encoding="utf-8")

    assert not any(marker in text for marker in MOJIBAKE_MARKERS)
    assert "🔍 Scan..." in text
    assert "📁 *PROJECT BARU*" in text
    assert "↩️ Reply angka 1-5" in text
