import unittest
from datetime import date, datetime, timezone

from dashboard_api.contracts import parse_filters
from dashboard_api.repository import DashboardRepository, decode_cursor, encode_cursor


class FakeCursor:
    def __init__(self, batches):
        self.batches = list(batches)
        self.executions = []
        self._rows = []

    def execute(self, sql, params=()):
        self.executions.append((" ".join(sql.split()), tuple(params)))
        self._rows = self.batches.pop(0) if self.batches else []

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DashboardRepositoryTests(unittest.TestCase):
    def make_repository(self, batches):
        cursor = FakeCursor(batches)
        repository = DashboardRepository(
            "postgresql://redacted",
            connection_factory=lambda *args, **kwargs: FakeConnection(cursor),
        )
        return repository, cursor

    def test_fetch_transactions_binds_filters_and_uses_inclusive_dates(self):
        filters = parse_filters(
            {
                "wallet": "TX SBY(216)",
                "company": "TEXTURIN-Surabaya",
                "project": "Hotel",
            },
            today=date(2026, 10, 21),
            allowed_projects=("Hotel",),
        )
        rows = [
            (
                9,
                "source:9",
                date(2026, 10, 21),
                2_500_000,
                "Pengeluaran",
                "TEXTURIN-Surabaya",
                "TX SBY(216)",
                "Hotel",
                "Produksi",
                "Bahan",
                "Naufal",
                "WhatsApp",
                None,
                "ledger",
                True,
                datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc),
            )
        ]
        repository, cursor = self.make_repository([rows])

        page = repository.fetch_transactions(filters, limit=50)

        sql, params = cursor.executions[0]
        self.assertIn("transaction_date >= %s", sql)
        self.assertIn("transaction_date <= %s", sql)
        self.assertIn("wallet = %s", sql)
        self.assertIn("company = %s", sql)
        self.assertIn("project = %s", sql)
        self.assertIn("is_valid = TRUE", sql)
        self.assertNotIn("TX SBY(216)", sql)
        self.assertEqual(
            params,
            (
                date(2026, 10, 1),
                date(2026, 10, 21),
                "TX SBY(216)",
                "TEXTURIN-Surabaya",
                "Hotel",
                51,
            ),
        )
        self.assertEqual(page.items[0]["source_key"], "source:9")
        self.assertIsNone(page.next_cursor)

    def test_cursor_round_trip_and_stable_descending_pagination(self):
        marker_date = date(2026, 10, 20)
        marker = encode_cursor(marker_date, 42)
        self.assertEqual(decode_cursor(marker), (marker_date, 42))
        repository, cursor = self.make_repository([[]])
        filters = parse_filters({}, today=date(2026, 10, 21))

        repository.fetch_transactions(filters, limit=25, cursor=marker)

        sql, params = cursor.executions[0]
        self.assertIn("(transaction_date, id) < (%s, %s)", sql)
        self.assertIn("ORDER BY transaction_date DESC, id DESC", sql)
        self.assertEqual(params[-3:], (marker_date, 42, 26))

    def test_page_uses_extra_row_to_create_next_cursor(self):
        base = datetime(2026, 10, 21, tzinfo=timezone.utc)
        rows = []
        for item_id in (5, 4, 3):
            rows.append(
                (
                    item_id,
                    f"source:{item_id}",
                    date(2026, 10, item_id),
                    1_000,
                    "Pemasukan",
                    "HOLLA",
                    "CV HB(101)",
                    "Alpha",
                    None,
                    None,
                    None,
                    None,
                    None,
                    "ledger",
                    True,
                    base,
                )
            )
        repository, _ = self.make_repository([rows])

        page = repository.fetch_transactions(
            parse_filters({}, today=date(2026, 10, 21)), limit=2
        )

        self.assertEqual([item["id"] for item in page.items], [5, 4])
        self.assertEqual(decode_cursor(page.next_cursor), (date(2026, 10, 4), 4))

    def test_filter_options_and_freshness_are_read_only(self):
        repository, cursor = self.make_repository(
            [
                [("CV HB(101)", "HOLLA", "Alpha")],
                [(datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc), 12, 2)],
            ]
        )

        options = repository.fetch_filter_options()
        freshness = repository.fetch_freshness()

        self.assertEqual(options["wallets"], ["CV HB(101)"])
        self.assertEqual(options["companies"], ["HOLLA"])
        self.assertEqual(options["projects"], ["Alpha"])
        self.assertEqual(freshness["row_count"], 12)
        self.assertEqual(freshness["invalid_count"], 2)
        self.assertTrue(all(execution[0].lstrip().upper().startswith("SELECT") for execution in cursor.executions))


if __name__ == "__main__":
    unittest.main()
