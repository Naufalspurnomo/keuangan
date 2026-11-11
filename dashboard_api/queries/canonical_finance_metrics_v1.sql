-- canonical.finance.metrics.v1
-- Psycopg named parameters: cutoff and monthly_operating_outflow.
WITH RECURSIVE transaction_lineage AS (
    SELECT id, id AS root_id
    FROM financial_transactions
    WHERE revision_of_id IS NULL AND reversal_of_id IS NULL
    UNION ALL
    SELECT child.id, parent.root_id
    FROM financial_transactions AS child
    JOIN transaction_lineage AS parent
      ON COALESCE(child.revision_of_id, child.reversal_of_id) = parent.id
),
transaction_ranked AS (
    SELECT transaction_lineage.root_id, transaction.*,
           ROW_NUMBER() OVER (
               PARTITION BY transaction_lineage.root_id
               ORDER BY transaction.version DESC, transaction.created_at DESC, transaction.id DESC
           ) AS state_rank
    FROM transaction_lineage
    JOIN financial_transactions AS transaction ON transaction.id = transaction_lineage.id
    WHERE transaction.created_at <= %(cutoff)s::timestamptz
      AND transaction.occurred_at <= %(cutoff)s::timestamptz
),
effective_transactions AS (
    SELECT *
    FROM transaction_ranked
    WHERE state_rank = 1
      AND status <> 'reversal'
      AND NOT (evidence @> '{"is_acceptance_test": true}'::jsonb)
      AND COALESCE(evidence->>'test_namespace', '') = ''
      AND NOT (evidence @> '{"quarantined": true}'::jsonb)
      AND NOT (evidence @> '{"excluded_from_canonical_totals": true}'::jsonb)
      AND COALESCE(evidence->>'review_status', 'approved') = 'approved'
),
effective_postings AS (
    SELECT transaction.root_id, transaction.scope, transaction.project_id,
           transaction.flow_class, posting.wallet_id, posting.business_unit_id,
           posting.account_class, posting.signed_amount
    FROM effective_transactions AS transaction
    JOIN financial_postings AS posting ON posting.transaction_id = transaction.id
),
transaction_cash AS (
    SELECT root_id, flow_class,
           SUM(signed_amount) FILTER (WHERE account_class = 'cash') AS cashflow
    FROM effective_postings
    GROUP BY root_id, flow_class
),
group_metrics AS (
    SELECT
        COALESCE(SUM(cashflow) FILTER (WHERE flow_class <> 'internal' AND cashflow > 0), 0)::bigint AS external_inflow,
        COALESCE(SUM(-cashflow) FILTER (WHERE flow_class <> 'internal' AND cashflow < 0), 0)::bigint AS external_outflow
    FROM transaction_cash
),
latest_opening_per_unit AS (
    SELECT DISTINCT ON (wallet_id, business_unit_id)
           wallet_id, business_unit_id, amount
    FROM wallet_opening_balances
    WHERE effective_at <= %(cutoff)s::timestamptz
    ORDER BY wallet_id, business_unit_id, effective_at DESC, id DESC
),
wallet_openings AS (
    SELECT wallet_id, SUM(amount)::bigint AS opening_balance
    FROM latest_opening_per_unit
    GROUP BY wallet_id
),
wallet_adjustments AS (
    SELECT wallet_id, SUM(delta_amount)::bigint AS adjustments
    FROM balance_adjustments
    WHERE effective_at <= %(cutoff)s::timestamptz
    GROUP BY wallet_id
),
wallet_cash AS (
    SELECT wallet_id, SUM(signed_amount)::bigint AS cash_postings
    FROM effective_postings
    WHERE account_class = 'cash'
    GROUP BY wallet_id
),
debt_lineage AS (
    SELECT id, id AS root_id, debt_id
    FROM interwallet_debt_events
    WHERE event_type IN ('disbursement', 'repayment')
    UNION ALL
    SELECT child.id, parent.root_id, child.debt_id
    FROM interwallet_debt_events AS child
    JOIN debt_lineage AS parent
      ON COALESCE(child.corrects_event_id, child.reverses_event_id) = parent.id
     AND child.debt_id = parent.debt_id
),
debt_ranked AS (
    SELECT debt_lineage.root_id, event.*,
           ROW_NUMBER() OVER (
               PARTITION BY event.debt_id, debt_lineage.root_id
               ORDER BY event.created_at DESC, event.id DESC
           ) AS state_rank
    FROM debt_lineage
    JOIN interwallet_debt_events AS event ON event.id = debt_lineage.id
    WHERE event.created_at <= %(cutoff)s::timestamptz
      AND event.occurred_at <= %(cutoff)s::timestamptz
),
effective_debt_events AS (
    SELECT debt_id, COALESCE(corrected_event_type, event_type) AS effective_type, amount
    FROM debt_ranked
    WHERE state_rank = 1 AND event_type <> 'reversal'
),
debt_outstanding AS (
    SELECT debt.id, debt.lender_wallet_id, debt.borrower_wallet_id, debt.due_at,
           GREATEST(COALESCE(SUM(
               CASE event.effective_type
                   WHEN 'disbursement' THEN event.amount
                   WHEN 'repayment' THEN -event.amount
                   ELSE 0
               END
           ), 0), 0)::bigint AS outstanding
    FROM interwallet_debts AS debt
    LEFT JOIN effective_debt_events AS event ON event.debt_id = debt.id
    GROUP BY debt.id, debt.lender_wallet_id, debt.borrower_wallet_id, debt.due_at
),
wallet_exposure AS (
    SELECT wallet_id,
           SUM(receivable)::bigint AS receivable,
           SUM(payable)::bigint AS payable
    FROM (
        SELECT lender_wallet_id AS wallet_id, outstanding AS receivable, 0::bigint AS payable
        FROM debt_outstanding WHERE outstanding > 0
        UNION ALL
        SELECT borrower_wallet_id AS wallet_id, 0::bigint AS receivable, outstanding AS payable
        FROM debt_outstanding WHERE outstanding > 0
    ) AS exposure
    GROUP BY wallet_id
),
wallet_ids AS (
    SELECT wallet_id FROM wallet_openings
    UNION SELECT wallet_id FROM wallet_adjustments
    UNION SELECT wallet_id FROM wallet_cash
    UNION SELECT wallet_id FROM wallet_exposure
),
wallet_metrics AS (
    SELECT wallet_ids.wallet_id,
           COALESCE(wallet_openings.opening_balance, 0)::bigint AS opening_balance,
           (COALESCE(wallet_openings.opening_balance, 0) + COALESCE(wallet_cash.cash_postings, 0))::bigint AS cash_balance,
           COALESCE(wallet_adjustments.adjustments, 0)::bigint AS adjustments,
           (COALESCE(wallet_openings.opening_balance, 0) + COALESCE(wallet_cash.cash_postings, 0) + COALESCE(wallet_adjustments.adjustments, 0))::bigint AS available_balance,
           COALESCE(wallet_exposure.receivable, 0)::bigint AS receivable,
           COALESCE(wallet_exposure.payable, 0)::bigint AS payable
    FROM wallet_ids
    LEFT JOIN wallet_openings USING (wallet_id)
    LEFT JOIN wallet_cash USING (wallet_id)
    LEFT JOIN wallet_adjustments USING (wallet_id)
    LEFT JOIN wallet_exposure USING (wallet_id)
),
project_metrics AS (
    SELECT project_id,
           COALESCE(-SUM(signed_amount) FILTER (WHERE account_class = 'revenue'), 0)::bigint AS revenue,
           COALESCE(SUM(signed_amount) FILTER (WHERE account_class = 'expense'), 0)::bigint AS cost,
           COALESCE(SUM(signed_amount) FILTER (WHERE account_class = 'cash'), 0)::bigint AS cashflow
    FROM effective_postings
    WHERE project_id IS NOT NULL
    GROUP BY project_id
),
debt_aging AS (
    SELECT CASE
               WHEN due_at IS NULL OR due_at::date >= (%(cutoff)s::timestamptz)::date THEN 'current'
               WHEN ((%(cutoff)s::timestamptz)::date - due_at::date) <= 30 THEN 'days_1_30'
               WHEN ((%(cutoff)s::timestamptz)::date - due_at::date) <= 60 THEN 'days_31_60'
               WHEN ((%(cutoff)s::timestamptz)::date - due_at::date) <= 90 THEN 'days_61_90'
               ELSE 'days_over_90'
           END AS bucket,
           SUM(outstanding)::bigint AS amount
    FROM debt_outstanding
    WHERE outstanding > 0
    GROUP BY bucket
)
SELECT 'group' AS metric_scope, 'group' AS metric_key,
       jsonb_build_object(
           'external_inflow', external_inflow,
           'external_outflow', external_outflow,
           'net_cashflow', external_inflow - external_outflow
       ) AS metric_payload
FROM group_metrics
UNION ALL
SELECT 'wallet', wallet_id::text,
       jsonb_build_object(
           'opening_balance', opening_balance,
           'cash_balance', cash_balance,
           'adjustments', adjustments,
           'available_balance', available_balance,
           'receivable', receivable,
           'payable', payable,
           'adjusted_balance', available_balance + receivable - payable,
           'runway_months_basis_points', CASE WHEN %(monthly_operating_outflow)s::bigint > 0 THEN available_balance * 10000 / %(monthly_operating_outflow)s::bigint ELSE NULL END,
           'health', CASE
               WHEN available_balance <= 0 THEN 'Critical'
               WHEN %(monthly_operating_outflow)s::bigint > 0 AND available_balance * 10000 / %(monthly_operating_outflow)s::bigint < 30000 THEN 'Watch'
               ELSE 'Healthy'
           END
       )
FROM wallet_metrics
UNION ALL
SELECT 'project', project_id::text,
       jsonb_build_object(
           'revenue', revenue,
           'cost', cost,
           'cashflow', cashflow,
           'gross_profit', revenue - cost,
           'margin_basis_points', CASE WHEN revenue <> 0 THEN (revenue - cost) * 10000 / revenue ELSE 0 END,
           'contribution', revenue - cost
       )
FROM project_metrics
UNION ALL
SELECT 'debt_aging', bucket, jsonb_build_object('amount', amount)
FROM debt_aging
ORDER BY metric_scope, metric_key;
