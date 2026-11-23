from contextlib import nullcontext

import pytest

from services.project_document_repository import ProjectDocumentRepository

PROJECT = '00000000-0000-4000-8000-000000000101'


class Cursor:
    def __init__(self, history):
        self.history = history
        self.sql = []
        self.rowcount = 1
    def execute(self, sql, params=None):
        self.sql.append(sql)
    def fetchone(self):
        if 'SELECT id FROM projects' in self.sql[-1]:
            return ('00000000-0000-4000-8000-000000000101',)
        return None
    def fetchall(self):
        return []


@pytest.mark.parametrize('history', [True, False])
def test_delete_removes_project_with_or_without_financial_history(monkeypatch, history):
    cursor = Cursor(history)
    class Connection:
        def cursor(self):
            return nullcontext(cursor)
    repository = object.__new__(ProjectDocumentRepository)
    monkeypatch.setattr(repository, '_connect', lambda: nullcontext(Connection()))
    monkeypatch.setattr(repository, '_claim', lambda *args: ('key', None, None))
    monkeypatch.setattr(repository, '_complete', lambda cur, key, response: response)
    def delete():
        return repository.delete_project(PROJECT, confirmation='hapus',
                                         idempotency_key='delete-regression-key', actor={'email': 'owner@example.com'})
    assert delete()['deleted'] is True
    assert any('DELETE FROM projects' in sql for sql in cursor.sql)
    assert not any('SELECT EXISTS' in sql for sql in cursor.sql)
