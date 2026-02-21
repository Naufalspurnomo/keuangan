# OCR QA Matrix

Date: 2026-02-21
Scope: OCR extraction safety for bank transfer receipts and statement tables.

## Goal
- Prevent numeric noise (`Kurs Valas`, account/reference/date/time) from becoming transaction amounts.
- Keep fee extraction realistic and block obvious bugs (`fee == main amount`, `fee = 1`).
- Support statement-table autopilot with safe fallback to existing flow.

## Core Cases
1. Single receipt, no admin fee.
Input hint:
- `Amount: Rp 200.000`
- `Fee: Rp 0.00` or no fee line
Expected:
- 1 transaction (main amount only)
- no `Biaya transfer` row

2. Single receipt, realistic fee 2.500.
Input hint:
- `Amount: Rp 200.000`
- `Fee: Rp 2.500`
Expected:
- 2 transactions: main `Rp200.000` + fee `Rp2.500`

3. Kurs valas noise.
Input hint:
- `Kurs Valas 1.00`
- `Amount: Rp 50.000`
Expected:
- fee must NOT become `1`
- only main amount (and fee only if explicit realistic fee exists)

4. Fee equals main amount (bug guard).
Input hint:
- main `Rp 40.000`
- OCR accidentally reads fee `Rp 40.000`
Expected:
- fee is dropped as unrealistic
- only main transaction kept

5. Statement table with multi rows.
Input hint:
- table headers (`Transfer Dana`, `Jumlah`, `Biaya`, `Status`, `No Referensi`)
- >= 2 valid rows with `Rp` amounts
Expected:
- autopilot extracts per-row transactions
- fee per row only when explicit and realistic

6. Statement table but low confidence.
Input hint:
- broken OCR text, weak row segmentation
Expected:
- statement autopilot returns empty
- fallback to existing AI text extraction path

7. Incoming transfer context (should not record sender-side fee).
Input hint:
- text contains `transfer masuk`, `pemasukan`, `diterima`
Expected:
- fee row dropped in incoming context

8. Tiny fee invalid.
Input hint:
- fee `Rp 1`, `Rp 10`, `Rp 50`
Expected:
- fee dropped (below minimum sanity)

9. Large but plausible RTGS-like fee.
Input hint:
- explicit fee keyword and fee <= 25.000 with large transfer
Expected:
- fee can be accepted when still below realistic ratio/limit

10. Account/reference-only numbers.
Input hint:
- long digits in `No. Referensi` / account columns, but no `Rp` amount near fee label
Expected:
- numbers not treated as fee/main amount.

## Runtime Switches
- `OCR_ENABLE_STATEMENT_AUTOPILOT=true|false`
- `OCR_STATEMENT_MIN_ROWS` (default `2`)
- `OCR_STATEMENT_MIN_CONFIDENCE` (default `0.72`)

## Notes
- This matrix is intended for manual QA or staging replay.
- In this workspace session, automated Python execution is unavailable.
