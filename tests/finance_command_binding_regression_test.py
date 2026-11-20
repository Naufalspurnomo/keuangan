import pytest

from tests.canonical_finance_core_test import ACTOR, make_service, payload
from services.canonical_finance import FinanceConflict


@pytest.mark.parametrize('operation', ['correct_transaction', 'reverse_transaction'])
def test_idempotency_key_cannot_replay_against_another_target(operation):
    service, repository = make_service()
    first = service.create_transaction(payload(), actor=ACTOR)['transaction']
    second = service.create_transaction(payload(idempotency_key='second-create-key-0001'), actor=ACTOR)['transaction']
    command = {'idempotency_key': 'shared-command-key-0001', 'expected_version': 1, 'reason': 'Bank verification'}
    if operation == 'correct_transaction':
        command['amount'] = 42
    result = getattr(service, operation)(first['id'], command, actor=ACTOR)
    assert getattr(service, operation)(first['id'], command, actor=ACTOR)['duplicate'] is True
    with pytest.raises(FinanceConflict, match='idempotency'):
        getattr(service, operation)(second['id'], command, actor=ACTOR)
    assert service.get_transaction(second['id'])['version'] == 1
    assert repository.outbox_count == 3
    assert result['duplicate'] is False


def test_request_hash_binds_operation_even_when_body_is_identical():
    from services.canonical_finance import CanonicalFinanceService

    class Capture:
        def __init__(self):
            self.hashes = []
        def append(self, record, **kwargs):
            self.hashes.append(kwargs['request_hash'])
            return record, False

    repository = Capture()
    service = CanonicalFinanceService(repository)
    body = {'idempotency_key': 'operation-binding-key'}
    for operation in ('create', 'correct', 'reverse'):
        service._append({'id': 'record', 'version': 1}, body['idempotency_key'], body,
                        operation=operation, command_target_id='target')
    assert len(set(repository.hashes)) == 3
