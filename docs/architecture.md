# Architecture and execution modes

## Local mode

The default path is local and needs no warehouse credentials. Synthetic CSV files flow through schema/business validation, referential checks, accepted/rejected outputs, Pandas transformations, analytics CSVs, and the Streamlit dashboard. Pipeline run history records batch IDs, file hashes, counts, and quality status.

## Snowflake mode

The optional `--backend snowflake` path generates and validates the same source batch locally, then uploads all nine raw CSVs to an internal stage with `PUT`. It uses positional `COPY INTO` mappings to retain raw values and attaches source-file, batch, and ingestion-time metadata. SQL assets create/deduplicate staging views, maintain dimensions (including the product SCD Type 2 history), merge facts, expose dashboard analytics and rejected-record views, and create pipeline monitoring records. The dashboard reads Snowflake views when `SUPPLYCHAINIQ_BACKEND=snowflake`.

The account, warehouse, RAW tables, file format, and stage must be provisioned first. Streams/Tasks are a separate optional incremental example and are not activated by the pipeline. No live Snowflake account is available in this environment, so account-specific execution and cost/privilege checks remain outstanding.
