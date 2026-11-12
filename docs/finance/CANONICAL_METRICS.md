# Canonical Finance Metrics v1

**Version:** `canonical.finance.metrics.v1`

**Service oracle:** `services/canonical_finance_metrics.py`

**SQL oracle:** `dashboard_api/queries/canonical_finance_metrics_v1.sql`

Every dashboard, wallet, project, debt, WhatsApp, and report value must be compared to this oracle at the same inclusive UTC cutoff. A formula change requires a new oracle version, compatibility note, fixtures, and reconciliation evidence.

## Time and money contract

- All timestamps require an explicit timezone and normalize to UTC.
- The cutoff is inclusive: state timestamps and business timestamps equal to the cutoff are included.
- Money is exact signed IDR integer units. Booleans, floats, coercion, and non-IDR postings fail closed.
- Every effective transaction must contain balanced postings whose signed sum is zero.
- Margin and runway use integer basis points; integer division truncates toward zero.

## Effective state and exclusions

For each immutable transaction root, select the latest state at or before the cutoff. A latest reversal removes the root. A correction replaces the previous state; original rows remain audit evidence.

Exclude from business totals:

- `evidence.is_acceptance_test = true` or a non-empty `test_namespace`;
- quarantined rows or `excluded_from_canonical_totals` rows;
- review states other than `approved`;
- rows after the cutoff;
- reversed roots.

The result reports exclusion counts by reason. Source review/quarantine resolution never mutates the original record.

## Wallet formulas

For each wallet:

- **opening balance:** sum of the latest opening snapshot per wallet/business-unit pair at or before cutoff;
- **cash balance:** opening balance plus effective `cash` postings;
- **adjustments:** effective immutable balance-adjustment deltas at or before cutoff;
- **available balance:** cash balance plus adjustments;
- **receivable:** outstanding debt where the wallet is lender;
- **payable:** outstanding debt where the wallet is borrower;
- **adjusted balance:** available balance plus receivable minus payable;
- **runway basis points:** `available_balance * 10000 / monthly_operating_outflow`; `null` when monthly outflow is zero;
- **Critical:** available balance `<= 0`;
- **Watch:** positive available balance and runway below `30000` basis points (3 months);
- **Healthy:** all other positive balances.

Health thresholds are v1 policy. Changing them requires a version bump.

## Group cashflow

- **external inflow:** positive effective transaction cashflow outside internal flow;
- **external outflow:** absolute negative effective transaction cashflow outside internal flow;
- **group net cashflow:** external inflow minus external outflow.

Internal transfer/debt has zero group cash and never contributes revenue or expense.

## Project formulas

Only exact canonical `project_id` linkage is accepted.

- **revenue:** negated signed `revenue` postings;
- **cost:** signed `expense` postings;
- **cashflow:** signed project `cash` postings;
- **gross profit:** revenue minus cost;
- **margin basis points:** `gross_profit * 10000 / revenue`, or zero if revenue is zero;
- **contribution:** gross profit in v1.

## Debt exposure and aging

Outstanding debt equals effective disbursement minus effective repayment after correction/reversal replay. Zero/paid/reversed debts are excluded.

Aging uses cutoff date minus due date:

- no due date or not yet due: `current`;
- 1–30 days: `days_1_30`;
- 31–60 days: `days_31_60`;
- 61–90 days: `days_61_90`;
- over 90 days: `days_over_90`.

## Compatibility

v1 depends on canonical financial schema `013_interwallet_debt_event_contract`. Google Sheets remains a protected derived export until authority cutover. No interface may silently substitute a Sheets formula, UI-derived total, or stale cached value for this oracle.