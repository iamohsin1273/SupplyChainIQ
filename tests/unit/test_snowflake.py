from types import SimpleNamespace

import pytest

from supplychainiq.data_generator import generate_data
from supplychainiq.warehouse.snowflake import (
    SOURCE_COLUMNS,
    _copy_statement,
    execute_model_sql,
    fetch_dashboard_data,
    load_csvs,
    run_snowflake_batch,
)


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.last_statement = ""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))
        self.last_statement = statement
        self.description = [SimpleNamespace(name="DASHBOARD_COLUMN")]

    def fetchall(self):
        if self.last_statement.startswith("COPY INTO "):
            return [("batch-test/orders.csv.gz", "LOADED", 1, 1, 0, 0, None)]
        return []


class FakeConnection:
    def __init__(self):
        self.fake_cursor = FakeCursor()
        self.executed_scripts = []
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def execute_string(self, statement, remove_comments=False):
        self.executed_scripts.append(statement)

    def close(self):
        self.closed = True


def test_copy_statement_has_full_source_mapping_and_safe_batch():
    statement = _copy_statement(
        "SUPPLYCHAIN_DB.RAW.ORDERS",
        ("ORDER_ID", "CUSTOMER_ID", "ORDER_DATE", "STATUS"),
        "SUPPLYCHAIN_DB.RAW.SOURCE_STAGE",
        "SUPPLYCHAIN_DB.RAW.CSV_FORMAT",
        "batch-123",
    )

    assert "COPY INTO SUPPLYCHAIN_DB.RAW.ORDERS" in statement
    assert "S.$1, S.$2, S.$3, S.$4" in statement
    assert "METADATA$FILENAME, 'batch-123', CURRENT_TIMESTAMP()" in statement
    assert "ON_ERROR='ABORT_STATEMENT'" in statement

    with pytest.raises(ValueError, match="batch_id"):
        _copy_statement(
            "SUPPLYCHAIN_DB.RAW.ORDERS",
            ("ORDER_ID",),
            "SUPPLYCHAIN_DB.RAW.SOURCE_STAGE",
            "SUPPLYCHAIN_DB.RAW.CSV_FORMAT",
            "bad/batch",
        )


def test_load_csvs_uploads_and_copies_every_source(tmp_path, monkeypatch):
    generate_data(tmp_path, orders_count=12, seed=3)
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "SUPPLYCHAIN_DB")
    connection = FakeConnection()

    results = load_csvs(connection, tmp_path, "batch-test")

    assert set(results) == set(SOURCE_COLUMNS)
    statements = [statement for statement, _ in connection.fake_cursor.statements]
    put_statements = [statement for statement in statements if statement.startswith("PUT ")]
    copy_statements = [statement for statement in statements if statement.startswith("COPY INTO ")]
    assert len(put_statements) == len(SOURCE_COLUMNS)
    assert len(copy_statements) == len(SOURCE_COLUMNS)
    assert any("RAW.SHIPMENTS" in statement for statement in copy_statements)
    assert all("AUTO_COMPRESS=TRUE" in statement for statement in put_statements)


def test_load_csvs_reports_missing_source_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "SUPPLYCHAIN_DB")

    with pytest.raises(FileNotFoundError, match="orders.csv"):
        load_csvs(FakeConnection(), tmp_path, "batch-test")


def test_execute_model_sql_runs_assets_in_order(monkeypatch, tmp_path):
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "CUSTOM_DB")
    sql_root = tmp_path / "sql"
    for folder in ("02_staging", "03_core", "04_analytics", "05_monitoring"):
        directory = sql_root / folder
        directory.mkdir(parents=True)
        (directory / "001_test.sql").write_text(
            "SELECT * FROM SUPPLYCHAIN_DB.TEST_TABLE;", encoding="utf-8"
        )
    connection = FakeConnection()

    executed = execute_model_sql(connection, project_root=tmp_path)

    assert len(executed) == 4
    assert len(connection.executed_scripts) == 4
    assert all("CUSTOM_DB.TEST_TABLE" in sql for sql in connection.executed_scripts)


def test_dashboard_queries_use_metadata_names_and_configured_database(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "CUSTOM_DB")
    connection = FakeConnection()

    data = fetch_dashboard_data(connection)

    assert "fact_orders" in data
    assert data["pipeline_runs"].columns.tolist() == ["dashboard_column"]
    queries = [statement for statement, _ in connection.fake_cursor.statements]
    assert len(queries) == 8
    assert all("CUSTOM_DB." in query for query in queries)


def test_snowflake_batch_records_monitoring_and_closes_connection(monkeypatch, tmp_path):
    from supplychainiq.warehouse import snowflake

    connection = FakeConnection()
    monkeypatch.setattr(snowflake, "connect", lambda: connection)
    monkeypatch.setattr(snowflake, "load_csvs", lambda *_: {"orders": [("orders.csv.gz", "LOADED")]})
    monkeypatch.setattr(snowflake, "execute_model_sql", lambda *_: ["sql/03_core/test.sql"])
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "CUSTOM_DB")

    result = run_snowflake_batch(
        tmp_path,
        "batch-test",
        {"source_rows": 100, "accepted_records": 98, "rejected_records": 2, "quality_score_pct": 98.0},
    )

    assert result["status"] == "SUCCESS"
    assert result["loaded_files"] == 1
    assert connection.closed
    statements = [statement for statement, _ in connection.fake_cursor.statements]
    assert "INSERT INTO CUSTOM_DB.MONITORING.PIPELINE_RUNS" in statements[0]
    assert "STATUS = 'SUCCESS'" in statements[1]
    assert connection.fake_cursor.statements[0][1][2:] == (100, 98, 2, 98.0)
