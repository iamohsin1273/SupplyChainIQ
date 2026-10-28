# Troubleshooting

- `ModuleNotFoundError: supplychainiq`: install the project (`pip install -e .`) or set `PYTHONPATH=src`.
- Dashboard says no outputs: run `python -m supplychainiq.pipeline` first.
- Streamlit missing: install optional app dependencies (`pip install -e '.[app]'`).
- Snowflake connection error: install `.[snowflake]`, verify `.env` values and authentication, and confirm account/role/warehouse/database/schema privileges. Provision the warehouse, RAW tables, CSV format, and stage with the setup SQL before running Snowflake mode. Never paste secrets into logs or commit `.env`.
- Snowflake dashboard reports missing views: run `python -m supplychainiq.pipeline --backend snowflake` after provisioning RAW objects; this refreshes staging, core, analytics, and monitoring SQL.
- Docker Compose cannot find `.env`: copy `.env.example` to `.env` before starting Compose; keep account secrets private.
- Invalid rows: inspect `data/reports/rejected_records_*.csv`; each rejected row includes a reason.
