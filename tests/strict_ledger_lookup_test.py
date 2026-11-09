from __future__ import annotations

from unittest.mock import patch

import pytest

from config.constants import (
    OPERASIONAL_COLS, OPERASIONAL_SHEET_NAME, SPLIT_LAYOUT_DATA_START,
    SPLIT_PEMASUKAN, SPLIT_PENGELUARAN,
)
from sheets_helper import LedgerScanIncomplete, find_all_transactions_by_message_id_strict


class FakeWalletSheet:
    def __init__(self, message_id: str = "") -> None:
        width = max((*SPLIT_PEMASUKAN.values(), *SPLIT_PENGELUARAN.values()))
        self.row = [""] * width
        if message_id:
            self.row[SPLIT_PEMASUKAN["MESSAGE_ID"] - 1] = message_id
            self.row[SPLIT_PEMASUKAN["JUMLAH"] - 1] = "125000"
            self.row[SPLIT_PEMASUKAN["KETERANGAN"] - 1] = "Pembayaran"
            self.row[SPLIT_PEMASUKAN["OLEH"] - 1] = "Admin"
            self.row[SPLIT_PEMASUKAN["PROJECT"] - 1] = "Proyek A"

    def col_values(self, column: int):
        value = self.row[column - 1]
        return (["header"] * (SPLIT_LAYOUT_DATA_START - 1)) + [value]

    def row_values(self, row: int):
        assert row == SPLIT_LAYOUT_DATA_START
        return list(self.row)


class FakeOperationalSheet:
    def col_values(self, column: int):
        assert column == OPERASIONAL_COLS["MESSAGE_ID"]
        return ["MessageID"]

    def row_values(self, row: int):
        if row == 1:
            header = [""] * max(OPERASIONAL_COLS.values())
            header[OPERASIONAL_COLS["MESSAGE_ID"] - 1] = "MessageID"
            return header
        return []


def test_strict_lookup_returns_complete_structured_proof():
    with patch("sheets_helper.DOMPET_SHEETS", ["WALLET-A"]), \
         patch("sheets_helper.get_dompet_sheet", return_value=FakeWalletSheet("msg-1")), \
         patch("sheets_helper.get_operational_sheet_read_only", return_value=FakeOperationalSheet()):
        proof = find_all_transactions_by_message_id_strict("msg-1")

    assert proof["status"] == "complete"
    assert proof["message_id"] == "msg-1"
    assert proof["checked_sources"] == ["WALLET-A", OPERASIONAL_SHEET_NAME]
    assert proof["failed_sources"] == []
    assert proof["matches"][0]["source_key"] == "msg-1"
    assert proof["matches"][0]["dompet"] == "WALLET-A"


def test_strict_lookup_raises_when_any_source_cannot_be_read():
    def fail_wallet(_name: str):
        raise RuntimeError("sheet unavailable")

    with patch("sheets_helper.DOMPET_SHEETS", ["WALLET-A"]), \
         patch("sheets_helper.get_dompet_sheet", side_effect=fail_wallet), \
         patch("sheets_helper.get_operational_sheet_read_only", return_value=FakeOperationalSheet()):
        with pytest.raises(LedgerScanIncomplete) as captured:
            find_all_transactions_by_message_id_strict("msg-2")

    assert captured.value.proof["status"] == "partial"
    assert captured.value.proof["failed_sources"] == ["WALLET-A"]


def test_strict_lookup_never_creates_a_missing_operational_sheet():
    with patch("sheets_helper.DOMPET_SHEETS", []), \
         patch("sheets_helper.get_operational_sheet_read_only", create=True, side_effect=RuntimeError("missing")) as read_only, \
         patch("sheets_helper.get_or_create_operational_sheet", side_effect=AssertionError("strict proof must not create")) as creator:
        with pytest.raises(LedgerScanIncomplete) as captured:
            find_all_transactions_by_message_id_strict("msg-missing-operational")

    read_only.assert_called_once_with()
    creator.assert_not_called()
    assert captured.value.proof["status"] == "partial"
    assert captured.value.proof["failed_sources"] == [OPERASIONAL_SHEET_NAME]
