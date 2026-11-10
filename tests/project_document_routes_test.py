import hashlib
import io
import json
import unittest
from unittest.mock import patch

from flask import Flask

from dashboard_api import register_dashboard
from services.project_document_repository import (
    ProjectDocumentConflict,
    ProjectDocumentNotFound,
    ProjectDocumentUnavailable,
)


PROXY_TOKEN = "project-document-proxy-token"
PROXY_TOKEN_HASH = hashlib.sha256(PROXY_TOKEN.encode()).hexdigest()
CSRF_TOKEN = "project-document-csrf-token"
IDEMPOTENCY_KEY = "project-document-test-0001"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
DOCUMENT_ID = "22222222-2222-4222-8222-222222222222"
EVIDENCE_ID = "44444444-4444-4444-8444-444444444444"


class FakeDashboardRepository:
    def fetch_filter_options(self):
        return {"projects": []}

    def fetch_project_identities(self):
        return []


class FakeProjectDocumentRepository:
    def __init__(self):
        self.calls = []
        self.error = None
        self.project = {
            "id": PROJECT_ID,
            "name": "Project Alpha",
            "status": "planned",
            "lock_version": 3,
        }
        self.document = {
            "id": DOCUMENT_ID,
            "project_id": PROJECT_ID,
            "document_type": "invoice",
            "invoice_kind": "DP",
            "status": "draft",
            "official_number": None,
            "lock_version": 4,
            "lines": [],
            "allocations": [],
        }

    def _raise(self):
        if self.error:
            raise self.error

    def project_exists(self, project_id, wallet=None, company=None):
        return project_id == PROJECT_ID

    def list_projects(self):
        self._raise()
        self.calls.append(("list_projects",))
        return [dict(self.project)]

    def get_project(self, project_id):
        self._raise()
        self.calls.append(("get_project", project_id))
        if project_id != PROJECT_ID:
            raise ProjectDocumentNotFound("project not found")
        return dict(self.project)

    def create_project_with_sales_order(self, values, **kwargs):
        self._raise()
        self.calls.append(("create_project", dict(values), kwargs))
        return {
            "project": dict(self.project),
            "sales_order": {**self.document, "document_type": "sales_order"},
        }

    def update_project(self, project_id, changes, **kwargs):
        self._raise()
        self.calls.append(("update_project", project_id, dict(changes), kwargs))
        return {**self.project, **changes, "lock_version": kwargs["expected_version"] + 1}

    def list_documents(self, project_id):
        self._raise()
        self.calls.append(("list_documents", project_id))
        return [dict(self.document)]

    def get_project_payment_summary(self, project_id):
        self._raise()
        self.calls.append(("get_project_payment_summary", project_id))
        return {
            "project_id": project_id,
            "contract_total": 1_000_000,
            "invoiced_total": 400_000,
            "unbilled_total": 600_000,
            "paid_total": 200_000,
            "contract_outstanding": 800_000,
            "overpaid_total": 0,
            "unapplied_total": 0,
            "payment_status": "PARTIALLY_PAID",
            "invoices": [],
        }

    def list_receipt_candidates(self, project_id):
        self._raise()
        self.calls.append(("list_receipt_candidates", project_id))
        return [{"source_key": "ledger:1", "available_amount": 200_000}]

    def get_document(self, document_id):
        self._raise()
        self.calls.append(("get_document", document_id))
        if document_id != DOCUMENT_ID:
            raise ProjectDocumentNotFound("document not found")
        return dict(self.document)

    def create_invoice_draft(self, project_id, **kwargs):
        self._raise()
        self.calls.append(("create_invoice", project_id, kwargs))
        return dict(self.document)

    def create_receipt_draft(self, project_id, **kwargs):
        self._raise()
        self.calls.append(("create_receipt", project_id, kwargs))
        return {**self.document, "document_type": "receipt", "invoice_kind": None}

    def update_draft(self, document_id, changes, **kwargs):
        self._raise()
        self.calls.append(("update_draft", document_id, dict(changes), kwargs))
        return {**self.document, **changes, "lock_version": kwargs["expected_version"] + 1}

    def issue_document(self, document_id, **kwargs):
        self._raise()
        self.calls.append(("issue_document", document_id, kwargs))
        return {**self.document, "status": "issued", "official_number": "INV/HW/2026/000001", "lock_version": 5}

    def void_document(self, document_id, **kwargs):
        self._raise()
        self.calls.append(("void_document", document_id, kwargs))
        return {**self.document, "status": "void", "void_reason": kwargs["reason"], "lock_version": 5}

    def revise_document(self, document_id, **kwargs):
        self._raise()
        self.calls.append(("revise_document", document_id, kwargs))
        return {**self.document, "id": "33333333-3333-4333-8333-333333333333", "revision_of_id": document_id}

    def replay_audit(self, **kwargs):
        self._raise()
        self.calls.append(("replay_audit", kwargs))
        return [{"id": 1, "event_type": "document.created"}]

    def list_project_quotations(self, project_id):
        self._raise()
        self.calls.append(("list_project_quotations", project_id))
        return [{"id": EVIDENCE_ID, "project_id": project_id, "version": 1, "canva_url": "https://canva.com/design/test", "amount": 1_000_000, "status": "draft", "channel": "whatsapp", "negotiation_notes": None, "sent_at": None, "decided_at": None, "created_at": "2026-11-10T00:00:00Z", "updated_at": "2026-11-10T00:00:00Z", "lock_version": 1}]

    def create_project_quotation(self, project_id, **kwargs):
        self.calls.append(("create_project_quotation", project_id, kwargs))
        return self.list_project_quotations(project_id)[0]

    def transition_project_quotation(self, quotation_id, **kwargs):
        self.calls.append(("transition_project_quotation", quotation_id, kwargs))
        return {**self.list_project_quotations(PROJECT_ID)[0], "status": kwargs["status"], "lock_version": kwargs["expected_version"] + 1}

    def apply_accepted_quotation_to_sales_order(self, quotation_id, **kwargs):
        self.calls.append(("apply_accepted_quotation_to_sales_order", quotation_id, kwargs))
        return dict(self.document)

    def list_transaction_evidence(self, project_id):
        self._raise()
        self.calls.append(("list_transaction_evidence", project_id))
        return [{
            "id": EVIDENCE_ID, "project_id": project_id, "ledger_source_key": "ledger:1",
            "mime_type": "image/png", "byte_size": 12, "sha256": "a" * 64,
            "original_name": "bukti.png", "review_status": "pending", "review_note": None,
            "reviewed_at": None, "created_at": "2026-11-10T00:00:00+00:00", "lock_version": 0,
        }]

    def upload_transaction_evidence(self, project_id, **kwargs):
        self._raise()
        self.calls.append(("upload_transaction_evidence", project_id, kwargs))
        return {**self.list_transaction_evidence(project_id)[0], "sha256": hashlib.sha256(kwargs["image_bytes"]).hexdigest(), "byte_size": len(kwargs["image_bytes"])}

    def review_transaction_evidence(self, evidence_id, **kwargs):
        self._raise()
        self.calls.append(("review_transaction_evidence", evidence_id, kwargs))
        return {**self.list_transaction_evidence(PROJECT_ID)[0], "review_status": kwargs["status"], "review_note": kwargs["note"], "lock_version": kwargs["expected_version"] + 1}

    def get_transaction_evidence_bytes(self, evidence_id):
        self._raise()
        image = b"\x89PNG\r\n\x1a\nroute-evidence"
        self.calls.append(("get_transaction_evidence_bytes", evidence_id))
        return {"mime_type": "image/png", "byte_size": len(image), "sha256": hashlib.sha256(image).hexdigest(), "original_name": "bukti.png", "bytes": image}

    def get_artifact(self, document_id):
        self._raise()
        pdf = b"%PDF-1.4\nsynthetic persisted artifact\n%%EOF\n"
        self.calls.append(("get_artifact", document_id))
        return {
            "document_id": document_id,
            "mime_type": "application/pdf",
            "byte_size": len(pdf),
            "sha256": hashlib.sha256(pdf).hexdigest(),
            "renderer_version": "test-renderer/1",
            "bytes": pdf,
        }


class ProjectDocumentRouteTests(unittest.TestCase):
    def make_app(self, *, enabled=False):
        repository = FakeProjectDocumentRepository()
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret",
            DASHBOARD_OWNER_EMAIL="owner@example.com",
            DASHBOARD_PROXY_TOKEN_HASH=PROXY_TOKEN_HASH,
            PROJECT_DOCUMENT_WRITES_ENABLED=enabled,
        )
        register_dashboard(
            app,
            repository=FakeDashboardRepository(),
            project_document_repository=repository,
        )
        return app, repository

    @staticmethod
    def login(client, *, role="owner"):
        with client.session_transaction() as session:
            session["dashboard_user"] = "owner@example.com"
            session["dashboard_role"] = role
            session["dashboard_csrf_token"] = CSRF_TOKEN

    @staticmethod
    def write_headers(*, version="*", csrf=CSRF_TOKEN, key=IDEMPOTENCY_KEY):
        return {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": key,
            "If-Match": version,
        }

    @staticmethod
    def envelope(response):
        payload = response.get_json()
        assert payload["api_version"] == "dashboard.v1"
        assert payload["meta"]["capabilities"]["transaction_correction_reversal"] is False
        assert payload["meta"]["capabilities"]["hard_delete"] is False
        return payload

    def test_owner_auth_reads_work_while_independent_write_gate_is_off(self):
        app, repository = self.make_app(enabled=False)
        client = app.test_client()

        denied = client.get("/api/dashboard/v1/projects")
        self.assertEqual(denied.status_code, 401)
        self.login(client)

        listed = client.get("/api/dashboard/v1/projects")
        self.assertEqual(listed.status_code, 200)
        payload = self.envelope(listed)
        self.assertEqual(payload["data"]["items"][0]["id"], PROJECT_ID)
        self.assertFalse(payload["meta"]["capabilities"]["project_document_writes_enabled"])
        self.assertIn("no-store", listed.headers["Cache-Control"])

        blocked = client.post(
            "/api/dashboard/v1/projects",
            headers=self.write_headers(),
            data=json.dumps({"idempotency_key": IDEMPOTENCY_KEY, "values": {"name": "X"}}),
        )
        self.assertEqual(blocked.status_code, 503)
        self.assertEqual(blocked.get_json()["error"]["code"], "project_document_writes_disabled")
        self.assertFalse(any(call[0] == "create_project" for call in repository.calls))

    def test_capabilities_explicitly_reject_fake_cash_correction_or_hard_delete(self):
        app, _repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)

        response = client.get("/api/dashboard/v1/project-documents/capabilities")
        self.assertEqual(response.status_code, 200)
        data = self.envelope(response)["data"]
        self.assertEqual(data["transaction_correction_reversal"], False)
        self.assertEqual(data["hard_delete"], False)
        self.assertEqual(data["reads_enabled"], True)
        self.assertEqual(client.delete(f"/api/dashboard/v1/projects/{PROJECT_ID}").status_code, 405)
        self.assertEqual(client.delete(f"/api/dashboard/v1/documents/{DOCUMENT_ID}").status_code, 405)

    def test_project_create_update_status_archive_contract(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)

        create = client.post(
            "/api/dashboard/v1/projects",
            headers=self.write_headers(),
            json={
                "idempotency_key": IDEMPOTENCY_KEY,
                "values": {
                    "name": "Project Alpha",
                    "client_name": "Client",
                    "issuer_key": "hollawall",
                    "wallet": "CV HB(101)",
                    "company": "HOLLA",
                },
            },
        )
        self.assertEqual(create.status_code, 201, create.get_data(as_text=True))
        self.assertEqual(self.envelope(create)["data"]["project"]["id"], PROJECT_ID)

        get = client.get(f"/api/dashboard/v1/projects/{PROJECT_ID}")
        self.assertEqual(get.status_code, 200)
        self.assertEqual(self.envelope(get)["data"]["lock_version"], 3)

        update = client.patch(
            f"/api/dashboard/v1/projects/{PROJECT_ID}",
            headers=self.write_headers(version='"3"'),
            json={"idempotency_key": IDEMPOTENCY_KEY, "expected_version": 3, "changes": {"client_contact": "0812"}},
        )
        self.assertEqual(update.status_code, 200, update.get_data(as_text=True))

        status = client.post(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/status",
            headers=self.write_headers(version='"3"'),
            json={"idempotency_key": IDEMPOTENCY_KEY, "expected_version": 3, "status": "active"},
        )
        self.assertEqual(status.status_code, 200)

        archive = client.post(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/archive",
            headers=self.write_headers(version='"3"'),
            json={"idempotency_key": IDEMPOTENCY_KEY, "expected_version": 3},
        )
        self.assertEqual(archive.status_code, 200)
        updates = [call for call in repository.calls if call[0] == "update_project"]
        self.assertEqual(updates[-2][2], {"status": "active"})
        self.assertEqual(updates[-1][2], {"status": "cancelled"})

    def test_project_create_rejects_missing_wallet_company_binding(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)

        response = client.post(
            "/api/dashboard/v1/projects",
            headers=self.write_headers(),
            json={
                "idempotency_key": IDEMPOTENCY_KEY,
                "values": {
                    "name": "Unbound Project",
                    "client_name": "Client",
                    "issuer_key": "hollawall",
                    "wallet": "",
                    "company": "",
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_project_document_request")
        self.assertFalse(any(call[0] == "create_project" for call in repository.calls))

    def test_every_write_requires_csrf_idempotency_and_matching_if_match(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)
        endpoint = f"/api/dashboard/v1/projects/{PROJECT_ID}"
        body = {"idempotency_key": IDEMPOTENCY_KEY, "expected_version": 3, "changes": {"name": "Changed"}}

        missing_csrf = client.patch(endpoint, headers={k: v for k, v in self.write_headers(version='"3"').items() if k != "X-CSRF-Token"}, json=body)
        self.assertEqual(missing_csrf.status_code, 403)
        missing_idempotency = client.patch(endpoint, headers={k: v for k, v in self.write_headers(version='"3"').items() if k != "Idempotency-Key"}, json=body)
        self.assertEqual(missing_idempotency.status_code, 422)
        missing_match = client.patch(endpoint, headers={k: v for k, v in self.write_headers(version='"3"').items() if k != "If-Match"}, json=body)
        self.assertEqual(missing_match.status_code, 428)
        mismatch = client.patch(endpoint, headers=self.write_headers(version='"2"'), json=body)
        self.assertEqual(mismatch.status_code, 412)
        bad_key = client.patch(endpoint, headers=self.write_headers(version='"3"', key="short"), json={**body, "idempotency_key": "short"})
        self.assertEqual(bad_key.status_code, 422)
        self.assertFalse(any(call[0] == "update_project" for call in repository.calls))

    def test_strict_json_and_body_limit_are_enforced_before_service(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)
        endpoint = "/api/dashboard/v1/projects"

        wrong_type = client.post(endpoint, headers={**self.write_headers(), "Content-Type": "text/plain"}, data="{}")
        self.assertEqual(wrong_type.status_code, 415)
        malformed = client.post(endpoint, headers=self.write_headers(), data="{")
        self.assertEqual(malformed.status_code, 422)
        array = client.post(endpoint, headers=self.write_headers(), data="[]")
        self.assertEqual(array.status_code, 422)
        oversized = client.post(endpoint, headers=self.write_headers(), data=json.dumps({"padding": "x" * 300000}))
        self.assertEqual(oversized.status_code, 413)
        self.assertFalse(any(call[0] == "create_project" for call in repository.calls))

    def test_document_list_get_create_update_lifecycle_audit_and_pdf(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)

        listed = client.get(f"/api/dashboard/v1/projects/{PROJECT_ID}/documents")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(self.envelope(listed)["data"]["items"][0]["id"], DOCUMENT_ID)
        got = client.get(f"/api/dashboard/v1/documents/{DOCUMENT_ID}")
        self.assertEqual(got.status_code, 200)

        invoice = client.post(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/documents/invoices",
            headers=self.write_headers(),
            json={"idempotency_key": IDEMPOTENCY_KEY, "kind": "DP", "values": {}},
        )
        self.assertEqual(invoice.status_code, 201, invoice.get_data(as_text=True))
        receipt = client.post(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/documents/receipts",
            headers=self.write_headers(),
            json={
                "idempotency_key": IDEMPOTENCY_KEY,
                "allocations": [{"source_key": "sheet:1", "amount": 1000}],
                "values": {},
            },
        )
        self.assertEqual(receipt.status_code, 201, receipt.get_data(as_text=True))

        version_headers = self.write_headers(version='"4"')
        update = client.patch(
            f"/api/dashboard/v1/documents/{DOCUMENT_ID}",
            headers=version_headers,
            json={"idempotency_key": IDEMPOTENCY_KEY, "expected_version": 4, "changes": {"notes": "Revised draft"}},
        )
        self.assertEqual(update.status_code, 200)
        issue = client.post(
            f"/api/dashboard/v1/documents/{DOCUMENT_ID}/issue",
            headers=version_headers,
            json={"idempotency_key": IDEMPOTENCY_KEY, "expected_version": 4},
        )
        self.assertEqual(issue.status_code, 200)
        void = client.post(
            f"/api/dashboard/v1/documents/{DOCUMENT_ID}/void",
            headers=version_headers,
            json={"idempotency_key": IDEMPOTENCY_KEY, "expected_version": 4, "reason": "Client cancelled"},
        )
        self.assertEqual(void.status_code, 200)
        revise = client.post(
            f"/api/dashboard/v1/documents/{DOCUMENT_ID}/revise",
            headers=version_headers,
            json={"idempotency_key": IDEMPOTENCY_KEY, "expected_version": 4},
        )
        self.assertEqual(revise.status_code, 201)

        audit = client.get(f"/api/dashboard/v1/documents/{DOCUMENT_ID}/audit")
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(self.envelope(audit)["data"]["items"][0]["event_type"], "document.created")

        download = client.get(f"/api/dashboard/v1/documents/{DOCUMENT_ID}/download")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.mimetype, "application/pdf")
        self.assertTrue(download.data.startswith(b"%PDF-"))
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertIn("no-store", download.headers["Cache-Control"])
        self.assertIn(("get_artifact", DOCUMENT_ID), repository.calls)

    def test_project_audit_and_proxy_owner_auth(self):
        app, _repository = self.make_app(enabled=False)
        client = app.test_client()
        response = client.get(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/audit",
            headers={"X-Hollawall-Proxy-Token": PROXY_TOKEN},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.envelope(response)["data"]["items"][0]["event_type"], "document.created")

    def test_domain_failures_use_stable_error_envelopes(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)

        for error, status, code in [
            (ProjectDocumentNotFound("secret detail"), 404, "project_document_not_found"),
            (ProjectDocumentConflict("secret detail"), 409, "project_document_conflict"),
            (ProjectDocumentUnavailable("secret detail"), 503, "project_document_unavailable"),
            (ValueError("secret detail"), 422, "invalid_project_document_request"),
        ]:
            repository.error = error
            response = client.get(f"/api/dashboard/v1/projects/{PROJECT_ID}")
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.get_json()["error"]["code"], code)
            self.assertNotIn("secret detail", response.get_data(as_text=True))
            self.assertIn("no-store", response.headers["Cache-Control"])

    def test_pdf_integrity_mismatch_fails_closed(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)
        original = repository.get_artifact

        def corrupt(document_id):
            artifact = original(document_id)
            artifact["sha256"] = "0" * 64
            return artifact

        repository.get_artifact = corrupt
        response = client.get(f"/api/dashboard/v1/documents/{DOCUMENT_ID}/download")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "project_document_unavailable")


    def test_payment_summary_and_receipt_options_are_owner_scoped_reads(self):
        app, repository = self.make_app(enabled=False)
        client = app.test_client()
        self.login(client)

        summary_response = client.get(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/payment-summary"
        )
        options_response = client.get(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/receipt-options"
        )

        self.assertEqual(summary_response.status_code, 200)
        summary = self.envelope(summary_response)["data"]
        self.assertEqual(summary["paid_total"], 200_000)
        self.assertEqual(summary["contract_outstanding"], 800_000)
        self.assertEqual(options_response.status_code, 200)
        options = self.envelope(options_response)["data"]
        self.assertEqual(options["transactions"][0]["source_key"], "ledger:1")
        self.assertIn(("get_project_payment_summary", PROJECT_ID), repository.calls)
        self.assertIn(("list_receipt_candidates", PROJECT_ID), repository.calls)
        self.assertIn("no-store", summary_response.headers["Cache-Control"])

    def test_receipt_route_forwards_invoice_target(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)
        response = client.post(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/documents/receipts",
            headers=self.write_headers(),
            json={
                "idempotency_key": IDEMPOTENCY_KEY,
                "invoice_id": DOCUMENT_ID,
                "allocations": [{"ledger_source_key": "ledger:1", "amount": 200_000}],
                "values": {},
            },
        )
        self.assertEqual(response.status_code, 201)
        call = next(item for item in repository.calls if item[0] == "create_receipt")
        self.assertEqual(call[2]["values"]["applies_to_invoice_id"], DOCUMENT_ID)


    def test_evidence_upload_list_review_and_download_are_owner_scoped(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)
        image = b"\x89PNG\r\n\x1a\nroute-upload"

        uploaded = client.post(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/evidence",
            data={"ledger_source_key": "ledger:1", "evidence": (io.BytesIO(image), "bukti.png", "image/png")},
            headers={"X-CSRF-Token": CSRF_TOKEN, "Idempotency-Key": IDEMPOTENCY_KEY},
        )
        self.assertEqual(uploaded.status_code, 201)
        self.assertEqual(self.envelope(uploaded)["data"]["review_status"], "pending")
        upload_call = next(call for call in repository.calls if call[0] == "upload_transaction_evidence")
        self.assertEqual(upload_call[1], PROJECT_ID)
        self.assertEqual(upload_call[2]["image_bytes"], image)

        listed = client.get(f"/api/dashboard/v1/projects/{PROJECT_ID}/evidence")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(self.envelope(listed)["data"]["items"][0]["id"], EVIDENCE_ID)

        reviewed = client.post(
            f"/api/dashboard/v1/evidence/{EVIDENCE_ID}/review",
            data=json.dumps({
                "idempotency_key": IDEMPOTENCY_KEY, "expected_version": 0,
                "status": "approved", "note": "",
            }),
            headers=self.write_headers(version='"0"'),
        )
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(self.envelope(reviewed)["data"]["review_status"], "approved")

        downloaded = client.get(f"/api/dashboard/v1/evidence/{EVIDENCE_ID}/download")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content_type, "image/png")
        self.assertEqual(downloaded.headers["Cache-Control"], "no-store, private")
        self.assertEqual(downloaded.data, b"\x89PNG\r\n\x1a\nroute-evidence")

    def test_evidence_upload_rejects_invalid_signature_before_repository(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)
        response = client.post(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/evidence",
            data={"ledger_source_key": "ledger:1", "evidence": (io.BytesIO(b"fake"), "fake.png", "image/png")},
            headers={"X-CSRF-Token": CSRF_TOKEN, "Idempotency-Key": IDEMPOTENCY_KEY},
        )
        self.assertEqual(response.status_code, 415)
        self.assertFalse(any(call[0] == "upload_transaction_evidence" for call in repository.calls))

    def test_quotation_routes_preserve_version_and_apply_to_sales_order(self):
        app, repository = self.make_app(enabled=True)
        client = app.test_client()
        self.login(client)
        listed = client.get(f"/api/dashboard/v1/projects/{PROJECT_ID}/quotations")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(self.envelope(listed)["data"]["items"][0]["version"], 1)

        created = client.post(
            f"/api/dashboard/v1/projects/{PROJECT_ID}/quotations",
            data=json.dumps({
                "idempotency_key": IDEMPOTENCY_KEY,
                "values": {"canva_url": "https://canva.com/design/test", "amount": 1_000_000},
            }),
            headers=self.write_headers(version="*"),
        )
        self.assertEqual(created.status_code, 201)
        create_call = next(call for call in repository.calls if call[0] == "create_project_quotation")
        self.assertEqual(create_call[2]["values"]["amount"], 1_000_000)

        transitioned = client.post(
            f"/api/dashboard/v1/quotations/{EVIDENCE_ID}/transition",
            data=json.dumps({
                "idempotency_key": IDEMPOTENCY_KEY,
                "expected_version": 1, "status": "sent", "note": "",
            }),
            headers=self.write_headers(version='"1"'),
        )
        self.assertEqual(transitioned.status_code, 200)
        self.assertEqual(self.envelope(transitioned)["data"]["status"], "sent")

        applied = client.post(
            f"/api/dashboard/v1/quotations/{EVIDENCE_ID}/apply",
            data=json.dumps({"idempotency_key": IDEMPOTENCY_KEY, "sales_order_version": 4}),
            headers=self.write_headers(version="*"),
        )
        self.assertEqual(applied.status_code, 200)
        apply_call = next(call for call in repository.calls if call[0] == "apply_accepted_quotation_to_sales_order")
        self.assertEqual(apply_call[2]["expected_document_version"], 4)


class ProjectDocumentProductionWiringTests(unittest.TestCase):
    def test_default_repository_receives_the_committed_a5_renderer(self):
        from services.project_document_pdf import render_project_document_artifact

        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret",
            DASHBOARD_OWNER_EMAIL="owner@example.com",
            DASHBOARD_PROXY_TOKEN_HASH=PROXY_TOKEN_HASH,
        )
        repository = FakeProjectDocumentRepository()
        with patch.dict(
            "os.environ",
            {"STATE_DATABASE_URL": "postgresql://local-test-only"},
            clear=False,
        ), patch(
            "services.project_document_repository.ProjectDocumentRepository",
            return_value=repository,
        ) as repository_factory:
            register_dashboard(app, repository=FakeDashboardRepository())

        self.assertIs(
            repository_factory.call_args.kwargs["renderer"],
            render_project_document_artifact,
        )
        self.assertTrue(app.config["PROJECT_DOCUMENT_READS_ENABLED"])


class ProjectDocumentHealthContractTests(unittest.TestCase):
    def test_health_gate_uses_independent_project_document_flag(self):
        import main

        with patch.dict(main.os.environ, {"PROJECT_DOCUMENT_WRITES_ENABLED": "true", "DASHBOARD_TRANSACTION_WRITES_ENABLED": "false"}, clear=False), patch.object(
            main, "read_project_document_runtime_health", return_value={"ready": True, "tables": True, "canonical_issuer": True}
        ):
            status = main.project_document_schema_health()
        self.assertTrue(status["writes_enabled"])

        provider = {"configured": False, "reachable": False, "connected": False, "logged_in": False}
        with main.app.test_request_context("/health"), patch.dict(
            main.app.config,
            {"PROJECT_DOCUMENT_WRITES_ENABLED": True, "DASHBOARD_TRANSACTION_WRITES_ENABLED": False},
        ), patch.object(main, "inbox_health", return_value={"durable": True}), patch.object(
            main, "get_wuzapi_status", return_value=provider
        ), patch.object(main, "dashboard_write_schema_health", return_value={"ready": False}), patch.object(
            main, "project_document_schema_health", return_value={"ready": False, "writes_enabled": True}
        ), patch.object(main, "allowlist_required", return_value=False), patch.object(
            main, "webhook_secret_required", return_value=False
        ):
            response, code = main.health_check()
        self.assertEqual(code, 503)
        body = response.get_json()
        self.assertFalse(body["project_document_readiness"]["ready"])
        self.assertTrue(body["project_document_readiness"]["writes_enabled"])
        self.assertFalse(body["project_document_readiness"]["transaction_correction_reversal"])

    def test_health_fails_when_configured_reads_have_unready_schema(self):
        import main

        provider = {"configured": False, "reachable": False, "connected": False, "logged_in": False}
        with main.app.test_request_context("/health"), patch.dict(
            main.app.config,
            {
                "PROJECT_DOCUMENT_READS_ENABLED": True,
                "PROJECT_DOCUMENT_WRITES_ENABLED": False,
                "DASHBOARD_TRANSACTION_WRITES_ENABLED": False,
            },
        ), patch.object(main, "inbox_health", return_value={"durable": True}), patch.object(
            main, "get_wuzapi_status", return_value=provider
        ), patch.object(main, "dashboard_write_schema_health", return_value={"ready": False}), patch.object(
            main,
            "project_document_schema_health",
            return_value={"configured": True, "ready": False, "writes_enabled": False},
        ), patch.object(main, "allowlist_required", return_value=False), patch.object(
            main, "webhook_secret_required", return_value=False
        ):
            response, code = main.health_check()

        self.assertEqual(code, 503)
        readiness = response.get_json()["project_document_readiness"]
        self.assertTrue(readiness["reads_enabled"])
        self.assertFalse(readiness["writes_enabled"])
        self.assertFalse(readiness["schema_ready"])
        self.assertFalse(readiness["ready"])

    def test_health_does_not_advertise_unconfigured_project_reads(self):
        import main

        provider = {"configured": False, "reachable": False, "connected": False, "logged_in": False}
        with main.app.test_request_context("/health"), patch.dict(
            main.app.config,
            {
                "PROJECT_DOCUMENT_READS_ENABLED": False,
                "PROJECT_DOCUMENT_WRITES_ENABLED": False,
                "DASHBOARD_TRANSACTION_WRITES_ENABLED": False,
            },
        ), patch.object(main, "inbox_health", return_value={"durable": True}), patch.object(
            main, "get_wuzapi_status", return_value=provider
        ), patch.object(main, "dashboard_write_schema_health", return_value={"ready": False}), patch.object(
            main,
            "project_document_schema_health",
            return_value={"configured": False, "ready": False, "writes_enabled": False},
        ), patch.object(main, "allowlist_required", return_value=False), patch.object(
            main, "webhook_secret_required", return_value=False
        ):
            response, code = main.health_check()

        self.assertEqual(code, 200)
        readiness = response.get_json()["project_document_readiness"]
        self.assertFalse(readiness["reads_enabled"])
        self.assertFalse(readiness["writes_enabled"])
        self.assertFalse(readiness["schema_ready"])
        self.assertTrue(readiness["ready"])



if __name__ == "__main__":
    unittest.main()
