from __future__ import annotations

import hashlib
import json

import pytest

from services.financial_export_reconstruction import (
    ExportReconstructionError,
    reconstruct_financial_export,
)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def document(*, ordinal, aggregate_type, aggregate_id, version, payload):
    payload_sha256 = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    body = {
        "export_ordinal": ordinal,
        "export_schema_version": "canonical.finance.export.v1",
        "export_key": f"{aggregate_type}:{aggregate_id}:v{version}",
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "aggregate_version": version,
        "outbox_created_at_utc": f"2026-11-12T00:00:0{ordinal}Z",
        "payload_sha256": payload_sha256,
        "payload_json": canonical_json(payload),
    }
    body["row_sha256"] = hashlib.sha256(canonical_json(body).encode()).hexdigest()
    return body


def transaction_payload(*, tx_id, version, status="posted", revision_of_id=None):
    return {
        "schema_version": "canonical.finance.transaction.v1",
        "id": tx_id,
        "scope": "project",
        "project_id": "00000000-0000-4000-8000-000000000501",
        "wallet_id": "34d6db17-e205-5dfa-a3b8-90f0e0a3ec6b",
        "business_unit_id": "d3261754-6ee5-5d37-b0e2-79614da60abb",
        "transaction_type": "outflow",
        "flow_class": "external",
        "amount": 125000,
        "currency": "IDR",
        "category": "materials",
        "description": "material",
        "occurred_at": "2026-11-12T00:00:00+00:00",
        "source": "whatsapp",
        "source_reference": "wamid.1",
        "evidence": {},
        "actor": {"id": "6281212042709", "role": "boss", "channel": "whatsapp"},
        "revision_of_id": revision_of_id,
        "reversal_of_id": None,
        "version": version,
        "status": status,
        "postings": [
            {
                "id": f"00000000-0000-4000-8000-0000000007{version}1",
                "transaction_id": tx_id,
                "wallet_id": "34d6db17-e205-5dfa-a3b8-90f0e0a3ec6b",
                "business_unit_id": "d3261754-6ee5-5d37-b0e2-79614da60abb",
                "account_class": "cash",
                "signed_amount": -125000,
                "currency": "IDR",
            },
            {
                "id": f"00000000-0000-4000-8000-0000000007{version}2",
                "transaction_id": tx_id,
                "wallet_id": None,
                "business_unit_id": "d3261754-6ee5-5d37-b0e2-79614da60abb",
                "account_class": "expense",
                "signed_amount": 125000,
                "currency": "IDR",
            },
        ],
    }


def debt_payload(debt_id):
    event_id = "00000000-0000-4000-8000-000000000801"
    return {
        "schema_version": "canonical.finance.debt.v1",
        "debt": {
            "id": debt_id,
            "lender_wallet_id": "34d6db17-e205-5dfa-a3b8-90f0e0a3ec6b",
            "borrower_wallet_id": "c23a1506-50d2-55a9-9469-8744b18fd85b",
            "lender_business_unit_id": "d3261754-6ee5-5d37-b0e2-79614da60abb",
            "borrower_business_unit_id": "9f91cd70-58b6-52c8-aeaa-55ebf3006d13",
            "project_id": None,
            "principal": 125000,
            "currency": "IDR",
            "occurred_at": "2026-11-12T00:00:00+00:00",
            "due_at": None,
            "description": "loan",
            "actor": {"id": "6281212042709", "role": "boss", "channel": "whatsapp"},
        },
        "events": [{
            "id": event_id,
            "debt_id": debt_id,
            "event_type": "created",
            "amount": 125000,
            "actor": {"id": "6281212042709", "role": "boss", "channel": "whatsapp"},
            "occurred_at": "2026-11-12T00:00:00+00:00",
            "description": "loan",
            "postings": [
                {"id": "00000000-0000-4000-8000-000000000811", "wallet_id": "34d6db17-e205-5dfa-a3b8-90f0e0a3ec6b", "business_unit_id": "d3261754-6ee5-5d37-b0e2-79614da60abb", "account_class": "cash", "signed_amount": -125000, "currency": "IDR"},
                {"id": "00000000-0000-4000-8000-000000000812", "wallet_id": "c23a1506-50d2-55a9-9469-8744b18fd85b", "business_unit_id": "9f91cd70-58b6-52c8-aeaa-55ebf3006d13", "account_class": "cash", "signed_amount": 125000, "currency": "IDR"},
                {"id": "00000000-0000-4000-8000-000000000813", "wallet_id": None, "business_unit_id": "d3261754-6ee5-5d37-b0e2-79614da60abb", "account_class": "receivable", "signed_amount": 125000, "currency": "IDR"},
                {"id": "00000000-0000-4000-8000-000000000814", "wallet_id": None, "business_unit_id": "9f91cd70-58b6-52c8-aeaa-55ebf3006d13", "account_class": "payable", "signed_amount": -125000, "currency": "IDR"},
            ],
        }],
        "version": 1,
    }


def test_reconstructs_transaction_history_and_debt_without_legacy_sheet_reads():
    first_id = "00000000-0000-4000-8000-000000000601"
    correction_id = "00000000-0000-4000-8000-000000000602"
    debt_id = "00000000-0000-4000-8000-000000000701"
    docs = [
        document(ordinal=1, aggregate_type="transaction", aggregate_id=first_id, version=1, payload=transaction_payload(tx_id=first_id, version=1)),
        document(ordinal=2, aggregate_type="transaction", aggregate_id=correction_id, version=2, payload=transaction_payload(tx_id=correction_id, version=2, status="correction", revision_of_id=first_id)),
        document(ordinal=3, aggregate_type="debt", aggregate_id=debt_id, version=1, payload=debt_payload(debt_id)),
    ]

    state = reconstruct_financial_export(docs)

    assert state["transaction_count"] == 2
    assert state["debt_count"] == 1
    assert state["effective_transaction_ids"] == [correction_id]
    assert state["debt_versions"] == {debt_id: 1}
    assert state["ordinal_sha256"] == hashlib.sha256("1\n2\n3".encode()).hexdigest()


@pytest.mark.parametrize("mutation", ["gap", "hash", "key", "version", "posting"])
def test_reconstruction_fails_closed_on_incomplete_or_mutated_export(mutation):
    tx_id = "00000000-0000-4000-8000-000000000601"
    payload = transaction_payload(tx_id=tx_id, version=1)
    doc = document(ordinal=1, aggregate_type="transaction", aggregate_id=tx_id, version=1, payload=payload)
    docs = [doc]
    if mutation == "gap":
        docs[0]["export_ordinal"] = 2
    elif mutation == "hash":
        docs[0]["payload_json"] = "{}"
    elif mutation == "key":
        docs[0]["export_key"] = "transaction:wrong:v1"
    elif mutation == "version":
        payload["version"] = 2
        docs[0] = document(ordinal=1, aggregate_type="transaction", aggregate_id=tx_id, version=1, payload=payload)
    else:
        payload["postings"] = payload["postings"][:1]
        docs[0] = document(ordinal=1, aggregate_type="transaction", aggregate_id=tx_id, version=1, payload=payload)

    with pytest.raises(ExportReconstructionError):
        reconstruct_financial_export(docs)
