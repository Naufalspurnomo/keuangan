# Hollawall Financial Command Center — Phase 0 Prototype

Visual, interaction, and information-architecture prototype. All values are synthetic and labeled `DATA DEMO`.

## Run

```bash
cd prototypes/financial-command-center
python -m http.server 4173 --bind 127.0.0.1
```

Open `http://127.0.0.1:4173/`.

## Review paths

- `/` — owner overview
- `/?view=transactions` — searchable ledger
- `/?view=wallets&wallet=TX+SBY%28216%29` — wallet-focused data
- `/?stale=1` — visible stale-data behavior

## Boundaries

- No production API or credentials.
- No Google Sheets/PostgreSQL access.
- No write controls.
- No real company transaction values.
- Metrics called `kontribusi tercatat`, never accounting profit.
