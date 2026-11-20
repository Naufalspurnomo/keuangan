"""Legacy body-only hashes must replay without widening command authority."""
import copy
import hashlib
import json

import pytest

from services.canonical_finance import CanonicalFinanceService, FinanceConflict
from services.financial_transaction_repository import (
    InMemoryFinancialRepository, PostgresFinancialTransactionRepository,
)
from tests.canonical_finance_core_test import ACTOR, payload


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Cursor:
    def __init__(self, repository):
        self.repository = repository
        self.row = None
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params):
        self.sql.append(sql)
        if 'WHERE idempotency_key_hash' in sql:
            hashed, identifier = self.repository._idempotency[params[0]]
            self.row = (identifier, hashed)
        elif 'pg_advisory_xact_lock' not in sql:
            raise AssertionError(f'Unexpected mutation/query: {sql}')

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, cursor):
        self.value = cursor
    def cursor(self):
        return self.value
    def commit(self):
        pass
    def rollback(self):
        pass
    def close(self):
        pass


@pytest.fixture(params=['memory', 'postgres-harness'])
def ledger(request, monkeypatch):
    memory = InMemoryFinancialRepository()
    service = CanonicalFinanceService(memory)

    def use_replay_repository():
        if request.param == 'postgres-harness':
            cursor = Cursor(memory)
            postgres = PostgresFinancialTransactionRepository('postgresql://test', connection_factory=lambda _: Connection(cursor))
            monkeypatch.setattr(postgres, '_read_record', lambda _, identifier: memory.get(identifier))
            monkeypatch.setattr(postgres, 'chain', memory.chain)
            service._repository = postgres
        return service

    return service, memory, use_replay_repository


@pytest.mark.parametrize('operation', ['create', 'correct', 'reverse'])
def test_legacy_identical_replay_preserves_ledger(ledger, operation):
    service, repository, replay_service = ledger
    body = payload()
    root = service.create_transaction(body, actor=ACTOR)['transaction']
    identifier = root['id']
    if operation != 'create':
        body = {'idempotency_key': 'legacy-command-00001', 'expected_version': 1, 'reason': 'Verified bank receipt'}
        if operation == 'correct':
            body['amount'] = 42
        stored = getattr(service, operation + '_transaction')(identifier, body, actor=ACTOR)['transaction']
    else:
        stored = root
    key = hashlib.sha256(body['idempotency_key'].encode()).hexdigest()
    repository._idempotency[key] = (digest(body), stored['id'])
    before = copy.deepcopy((repository._records, repository._idempotency, repository._outbox))
    replay = replay_service()
    result = (replay.create_transaction(body, actor=ACTOR) if operation == 'create' else
              getattr(replay, operation + '_transaction')(identifier, body, actor=ACTOR))
    assert result == {'transaction': stored, 'duplicate': True}
    assert (repository._records, repository._idempotency, repository._outbox) == before


@pytest.mark.parametrize('operation', ['correct', 'reverse'])
def test_legacy_cross_target_is_rejected(ledger, operation):
    service, repository, replay_service = ledger
    first = service.create_transaction(payload(), actor=ACTOR)['transaction']
    second = service.create_transaction(payload(idempotency_key='second-create-00001'), actor=ACTOR)['transaction']
    body = {'idempotency_key': 'legacy-command-00001', 'expected_version': 1, 'reason': 'Verified bank receipt'}
    if operation == 'correct':
        body['amount'] = 42
    stored = getattr(service, operation + '_transaction')(first['id'], body, actor=ACTOR)['transaction']
    key = hashlib.sha256(body['idempotency_key'].encode()).hexdigest()
    repository._idempotency[key] = (digest(body), stored['id'])
    before = copy.deepcopy((repository._records, repository._idempotency, repository._outbox))
    with pytest.raises(FinanceConflict, match='idempotency'):
        getattr(replay_service(), operation + '_transaction')(second['id'], body, actor=ACTOR)
    assert (repository._records, repository._idempotency, repository._outbox) == before
