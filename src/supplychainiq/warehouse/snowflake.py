"""Optional Snowflake loading and dashboard-query helpers."""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import ROOT

SOURCE_COLUMNS = {
    "customers": ("CUSTOMER_ID", "REGION", "CUSTOMER_SEGMENT"),
    "inventory": (
        "INVENTORY_ID", "PRODUCT_ID", "WAREHOUSE_ID", "SNAPSHOT_DATE", "QUANTITY_ON_HAND", "UNIT_COST"
    ),
    "order_items": ("ORDER_ITEM_ID", "ORDER_ID", "PRODUCT_ID", "QUANTITY", "UNIT_PRICE"),
    "orders": ("ORDER_ID", "CUSTOMER_ID", "ORDER_DATE", "STATUS"),
    "products": ("PRODUCT_ID", "PRODUCT_NAME", "CATEGORY", "UNIT_PRICE", "SUPPLIER_ID", "REORDER_LEVEL"),
    "purchase_orders": (
        "PURCHASE_ORDER_ID", "SUPPLIER_ID", "PRODUCT_ID", "ORDER_DATE", "QUANTITY", "RECEIVED_DATE"
    ),
    "shipments": (
        "ORDER_ID", "ORDER_DATE", "SHIPMENT_ID", "WAREHOUSE_ID", "SHIP_DATE",
        "PROMISED_DELIVERY_DATE", "ACTUAL_DELIVERY_DATE"
    ),
    "suppliers": ("SUPPLIER_ID", "SUPPLIER_NAME", "COUNTRY", "LEAD_TIME_DAYS"),
    "warehouses": ("WAREHOUSE_ID", "WAREHOUSE_NAME", "REGION"),
}
MODEL_DIRECTORIES = ("02_staging", "03_core", "04_analytics", "05_monitoring")


def _load_environment() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("Install the 'snowflake' optional dependencies to load .env configuration") from exc
    load_dotenv()


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing Snowflake environment variable: {name}")
    return value


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*){0,2}", value):
        raise ValueError(f"Invalid Snowflake identifier: {value!r}")
    return value


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _column_names(description) -> list[str]:
    return [
        (column.name if hasattr(column, "name") else column[0]).lower()
        for column in description
    ]


def _connector_error_types() -> tuple[type[BaseException], ...]:
    try:
        from snowflake.connector.errors import Error
    except ImportError:
        return ()
    return (Error,)


def _stage_names() -> tuple[str, str]:
    database = _identifier(os.getenv("SNOWFLAKE_DATABASE", "SUPPLYCHAIN_DB"))
    stage = _identifier(
        os.getenv("SNOWFLAKE_STAGE", f"{database}.RAW.SOURCE_STAGE")
    )
    file_format = _identifier(
        os.getenv("SNOWFLAKE_FILE_FORMAT", f"{database}.RAW.CSV_FORMAT")
    )
    return stage, file_format


def connect():
    """Create a connector using environment variables or a local .env file."""
    _load_environment()
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError("Install the 'snowflake' optional dependencies to use Snowflake mode") from exc

    required = (
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_SCHEMA",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing Snowflake environment variables: " + ", ".join(missing))

    kwargs: dict[str, Any] = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "warehouse": os.environ["SNOWFLAKE_WAREHOUSE"],
        "database": os.environ["SNOWFLAKE_DATABASE"],
        "schema": os.environ["SNOWFLAKE_SCHEMA"],
    }
    if os.getenv("SNOWFLAKE_ROLE"):
        kwargs["role"] = os.environ["SNOWFLAKE_ROLE"]
    if os.getenv("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    elif os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH"):
        kwargs["private_key_file"] = os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]
        if os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"):
            kwargs["private_key_file_pwd"] = os.environ["SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"]
    else:
        raise RuntimeError("Set SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY_PATH")
    try:
        return snowflake.connector.connect(**kwargs)
    except snowflake.connector.errors.Error as exc:
        raise RuntimeError(f"Unable to connect to Snowflake: {exc}") from exc


def _copy_statement(table: str, columns: tuple[str, ...], stage: str, file_format: str, batch_id: str) -> str:
    stage, file_format = _identifier(stage), _identifier(file_format)
    table = _identifier(table)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", batch_id):
        raise ValueError("batch_id may contain only letters, numbers, underscores, and hyphens")
    selected_columns = ", ".join(f"S.${index}" for index in range(1, len(columns) + 1))
    target_columns = ", ".join((*columns, "SOURCE_FILE", "BATCH_ID", "INGESTED_AT"))
    return (
        f"COPY INTO {table} ({target_columns}) "
        f"FROM (SELECT {selected_columns}, METADATA$FILENAME, {_sql_literal(batch_id)}, "
        f"CURRENT_TIMESTAMP() FROM @{stage}/{batch_id}/{table.rsplit('.', 1)[-1].lower()}.csv.gz S) "
        f"FILE_FORMAT=(FORMAT_NAME={file_format}) ON_ERROR='ABORT_STATEMENT' PURGE=FALSE"
    )


def load_csvs(connection, raw_dir: Path, batch_id: str) -> dict[str, list[Any]]:
    """Upload each expected CSV and copy it into its corresponding RAW table."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", batch_id):
        raise ValueError("batch_id may contain only letters, numbers, underscores, and hyphens")
    raw_dir = Path(raw_dir)
    missing = [name for name in SOURCE_COLUMNS if not (raw_dir / f"{name}.csv").is_file()]
    if missing:
        raise FileNotFoundError("Missing source CSV files: " + ", ".join(f"{name}.csv" for name in missing))
    stage, file_format = _stage_names()
    database = _identifier(_required_environment("SNOWFLAKE_DATABASE"))
    results = {}

    with connection.cursor() as cursor:
        for name, columns in SOURCE_COLUMNS.items():
            path = (raw_dir / f"{name}.csv").resolve()
            file_uri = f"file://{path.as_posix()}"
            cursor.execute(
                f"PUT {_sql_literal(file_uri)} @{stage}/{batch_id} "
                "AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
            )
            cursor.fetchall()
            statement = _copy_statement(
                f"{database}.RAW.{name.upper()}", columns, stage, file_format, batch_id
            )
            cursor.execute(statement)
            copy_results = cursor.fetchall()
            if not copy_results:
                raise RuntimeError(f"COPY INTO returned no load result for {name}.csv")
            failed = [
                row
                for row in copy_results
                if len(row) < 2
                or str(row[1]).upper() not in {"LOADED", "LOAD_SKIPPED"}
                or (len(row) > 5 and int(row[5] or 0) > 0)
            ]
            if failed:
                raise RuntimeError(f"COPY INTO did not load {name}.csv cleanly: {failed!r}")
            results[name] = copy_results
    return results


def execute_model_sql(connection, project_root: Path = ROOT) -> list[str]:
    """Execute the ordered staging, core, analytics, and monitoring SQL assets."""
    database = _identifier(_required_environment("SNOWFLAKE_DATABASE"))
    executed = []
    for directory in MODEL_DIRECTORIES:
        sql_dir = Path(project_root) / "sql" / directory
        if not sql_dir.is_dir():
            raise FileNotFoundError(f"Snowflake model SQL directory not found: {sql_dir}")
        scripts = sorted(sql_dir.glob("*.sql"))
        if not scripts:
            raise FileNotFoundError(f"No Snowflake SQL assets found in {sql_dir}")
        for script in scripts:
            sql = script.read_text(encoding="utf-8").strip()
            if not sql:
                raise ValueError(f"Snowflake SQL asset is empty: {script}")
            sql = sql.replace("SUPPLYCHAIN_DB.", f"{database}.")
            connection.execute_string(sql, remove_comments=False)
            executed.append(str(script.relative_to(project_root)))
    return executed


def run_snowflake_batch(raw_dir: Path, batch_id: str, local_summary: dict | None = None) -> dict[str, Any]:
    """Upload a source batch and refresh its warehouse models."""
    connection = connect()

    database = _identifier(os.getenv("SNOWFLAKE_DATABASE", "SUPPLYCHAIN_DB"))
    started_at = datetime.now(UTC).replace(tzinfo=None)
    summary = local_summary or {}
    monitoring_started = False

    def mark_failed(message: str) -> None:
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {database}.MONITORING.PIPELINE_RUNS "
                "SET FINISHED_AT = %s, STATUS = 'FAILED', ERROR_MESSAGE = %s "
                "WHERE BATCH_ID = %s",
                (finished_at, message[:16000], batch_id),
            )

    try:
        monitoring_sql = ROOT / "sql" / "05_monitoring"
        monitoring_scripts = sorted(monitoring_sql.glob("*.sql"))
        if not monitoring_scripts:
            raise FileNotFoundError(f"No Snowflake monitoring SQL assets found in {monitoring_sql}")
        for script in monitoring_scripts:
            sql = script.read_text(encoding="utf-8").strip()
            if not sql:
                raise ValueError(f"Snowflake SQL asset is empty: {script}")
            connection.execute_string(sql.replace("SUPPLYCHAIN_DB.", f"{database}."), remove_comments=False)
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {database}.MONITORING.PIPELINE_RUNS "
                "(BATCH_ID, STARTED_AT, STATUS, SOURCE_ROWS, ACCEPTED_ROWS, REJECTED_ROWS, "
                "QUALITY_SCORE_PCT) VALUES (%s, %s, 'RUNNING', %s, %s, %s, %s)",
                (
                    batch_id,
                    started_at,
                    summary.get("source_rows", 0),
                    summary.get("accepted_records", 0),
                    summary.get("rejected_records", 0),
                    summary.get("quality_score_pct"),
                ),
            )
        monitoring_started = True
        loaded_files = load_csvs(connection, raw_dir, batch_id)
        executed_models = execute_model_sql(connection)
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {database}.MONITORING.PIPELINE_RUNS "
                "SET FINISHED_AT = %s, STATUS = 'SUCCESS', ERROR_MESSAGE = NULL "
                "WHERE BATCH_ID = %s",
                (finished_at, batch_id),
            )
        return {
            "status": "SUCCESS",
            "batch_id": batch_id,
            "loaded_files": len(loaded_files),
            "copy_result_rows": {name: len(result) for name, result in loaded_files.items()},
            "executed_models": executed_models,
        }
    except _connector_error_types() as exc:
        if monitoring_started:
            mark_failed(str(exc))
        raise RuntimeError(f"Snowflake batch {batch_id} failed: {exc}") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        if monitoring_started:
            mark_failed(str(exc))
        raise
    finally:
        connection.close()


DASHBOARD_QUERIES = {
    "fact_orders": "SELECT * FROM {database}.ANALYTICS.FACT_ORDERS",
    "monthly_revenue": "SELECT * FROM {database}.ANALYTICS.MONTHLY_REVENUE ORDER BY MONTH",
    "top_products": "SELECT * FROM {database}.ANALYTICS.TOP_PRODUCTS ORDER BY REVENUE DESC",
    "inventory_analytics": "SELECT * FROM {database}.ANALYTICS.INVENTORY_ANALYTICS",
    "shipment_analytics": "SELECT * FROM {database}.ANALYTICS.SHIPMENT_ANALYTICS",
    "dim_supplier": "SELECT * FROM {database}.ANALYTICS.DIM_SUPPLIER",
    "pipeline_runs": (
        "SELECT BATCH_ID, STATUS, STARTED_AT, REJECTED_ROWS AS REJECTED_RECORDS, QUALITY_SCORE_PCT "
        "FROM (SELECT BATCH_ID, STATUS, STARTED_AT, REJECTED_ROWS, QUALITY_SCORE_PCT "
        "FROM {database}.MONITORING.PIPELINE_RUNS ORDER BY STARTED_AT DESC LIMIT 30) "
        "ORDER BY STARTED_AT ASC"
    ),
    "rejected_records": "SELECT * FROM {database}.ANALYTICS.REJECTED_RECORDS",
}


def fetch_dashboard_data(connection=None) -> dict[str, pd.DataFrame]:
    """Read the fixed dashboard datasets from the Snowflake analytics schema."""
    owns_connection = connection is None
    if owns_connection:
        connection = connect()
    try:
        database = _identifier(_required_environment("SNOWFLAKE_DATABASE"))
        data = {}
        with connection.cursor() as cursor:
            for name, query in DASHBOARD_QUERIES.items():
                cursor.execute(query.format(database=database))
                columns = _column_names(cursor.description)
                data[name] = pd.DataFrame(cursor.fetchall(), columns=columns)
        return data
    except _connector_error_types() as exc:
        raise RuntimeError(f"Snowflake dashboard query failed: {exc}") from exc
    finally:
        if owns_connection:
            connection.close()
