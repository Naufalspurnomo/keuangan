from contextlib import nullcontext

import pytest

from services.project_document_repository import ProjectDocumentConflict, ProjectDocumentRepository

PROJECT = '00000000-0000-4000-8000-000000000101'


class Cursor:
    def __init__(self, history):
        self.history = history
        self.sql = []
        self.rowcount = 1
    def execute(self, sql, params=None):
        self.sql.append(sql)
    def fetchone(self):
        if 'SELECT name, lock_version' in self.sql[-1]:
            return ('Empty project', 1)
        if 'SELECT EXISTS' in self.sql[-1]:
            return (self.history,)
        return None
    def fetchall(self):
        return []


@pytest.mark.parametrize('history', [True, False])
def test_delete_preserves_financial_history_but_allows_empty_project(monkeypatch, history):
    cursor = Cursor(history)
    class Connection:
        def cursor(self):
            return nullcontext(cursor)
    repository = object.__new__(ProjectDocumentRepository)
    monkeypatch.setattr(repository, '_connect', lambda: nullcontext(Connection()))
    monkeypatch.setattr(repository, '_claim', lambda *args: ('key', None, None))
    monkeypatch.setattr(repository, '_complete', lambda cur, key, response: response)
    def delete():
        return repository.delete_project(PROJECT, expected_version=1, expected_name='Empty project',
                                         idempotency_key='delete-regression-key', actor={'email': 'owner@example.com'})
    if history:
        with pytest.raises(ProjectDocumentConflict, match='financial history'):
            delete()
        assert not any('DELETE FROM' in sql or 'set_config' in sql for sql in cursor.sql)
    else:
        assert delete()['deleted'] is True
        assert any('DELETE FROM projects' in sql for sql in cursor.sql)
    guards = [sql for sql in cursor.sql if 'SELECT EXISTS' in sql]
    assert len(guards) == 1
    for table in ('financial_transactions', 'financial_ledger', 'interwallet_debts', 'project_documents'):
        assert table in guards[0]
