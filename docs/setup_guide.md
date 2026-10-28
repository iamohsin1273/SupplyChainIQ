# Setup guide

## Local development

1. Use Python 3.11 or newer and create/activate a virtual environment.
2. Install with `python -m pip install -e ".[app,test]"`.
3. Run `python -m supplychainiq.pipeline` to generate, validate and transform sample data.
4. Run `streamlit run streamlit_app/app.py` to inspect the local analytics.
5. Run `pytest -q` and `ruff check src tests streamlit_app`.

## Optional Snowflake backend

Live Snowflake access is required for account validation. The loading and dashboard code is covered with mocked unit tests.

1. Install the optional dependencies with `python -m pip install -e ".[app,test,snowflake]"`.
2. Copy `.env.example` to `.env`, add Snowflake account information, and choose password or key-pair authentication. Do not commit credentials.
3. Using a role with the necessary account privileges, execute `sql/00_setup/001_create_environment.sql`, `sql/01_raw/001_raw_tables.sql`, and `sql/01_raw/002_stage_and_copy_into.sql`.
4. Keep the bootstrap database name `SUPPLYCHAIN_DB`, or edit the bootstrap SQL and `.env` database/stage/file-format values consistently.
5. Set `SUPPLYCHAINIQ_BACKEND=snowflake` and run `python -m supplychainiq.pipeline --backend snowflake`. The command uploads each source CSV, loads RAW with `COPY INTO`, refreshes staging/core/analytics models, and records the successful run.
6. Launch `streamlit run streamlit_app/app.py` to query the Snowflake-backed dashboard.
7. Review the optional task in `sql/06_tasks_streams/001_incremental_pattern.sql` before manually activating it.

The provisioning and warehouse SQL have not been run against an account in this development environment. Validate permissions, query results, and account costs before production use.
