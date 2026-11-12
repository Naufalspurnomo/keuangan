-- Deterministic registry for the three canonical wallets and explicit legacy
-- business units. UUIDv5 values are fixed release identifiers, not runtime IDs.

INSERT INTO business_units (id, code, legal_name, currency, active)
VALUES
    ('d3261754-6ee5-5d37-b0e2-79614da60abb', 'CV_HB_101', 'CV HB(101)', 'IDR', TRUE),
    ('9f91cd70-58b6-52c8-aeaa-55ebf3006d13', 'TX_SBY_216', 'TX SBY(216)', 'IDR', TRUE),
    ('0e21a9d9-4bda-5cb2-965b-bc2202e981ce', 'TX_BALI_087', 'TX BALI(087)', 'IDR', TRUE),
    ('253cd0fa-9f33-5051-821a-e1e4fd650472', 'OFFICE', 'Operasional Kantor', 'IDR', TRUE)
ON CONFLICT (id) DO UPDATE
SET code = EXCLUDED.code,
    legal_name = EXCLUDED.legal_name,
    currency = EXCLUDED.currency,
    active = EXCLUDED.active;

INSERT INTO wallets (id, code, display_name, currency, active)
VALUES
    ('34d6db17-e205-5dfa-a3b8-90f0e0a3ec6b', 'CV_HB_101', 'CV HB(101)', 'IDR', TRUE),
    ('c23a1506-50d2-55a9-9469-8744b18fd85b', 'TX_SBY_216', 'TX SBY(216)', 'IDR', TRUE),
    ('07743a6c-1ad0-5c00-9d96-0beaee4b8e01', 'TX_BALI_087', 'TX BALI(087)', 'IDR', TRUE)
ON CONFLICT (id) DO UPDATE
SET code = EXCLUDED.code,
    display_name = EXCLUDED.display_name,
    currency = EXCLUDED.currency,
    active = EXCLUDED.active;

INSERT INTO wallet_business_units (wallet_id, business_unit_id)
VALUES
    ('34d6db17-e205-5dfa-a3b8-90f0e0a3ec6b', 'd3261754-6ee5-5d37-b0e2-79614da60abb'),
    ('c23a1506-50d2-55a9-9469-8744b18fd85b', '9f91cd70-58b6-52c8-aeaa-55ebf3006d13'),
    ('07743a6c-1ad0-5c00-9d96-0beaee4b8e01', '0e21a9d9-4bda-5cb2-965b-bc2202e981ce')
ON CONFLICT (wallet_id, business_unit_id) DO NOTHING;
