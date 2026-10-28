import pandas as pd
import pytest

from supplychainiq import pipeline
from supplychainiq.data_generator import generate_data
from supplychainiq.ingestion.local import ingest_csvs
from supplychainiq.transformations.local import transform
from supplychainiq.validation.checks import validate_frame


def test_generator_is_reproducible(tmp_path):
    a,b=tmp_path/"a",tmp_path/"b"; generate_data(a,20,7); generate_data(b,20,7)
    assert (a/"orders.csv").read_bytes()==(b/"orders.csv").read_bytes()

def test_generator_rejects_non_positive_order_count(tmp_path):
    with pytest.raises(ValueError,match="at least 1"):
        generate_data(tmp_path,orders_count=0)

def test_missing_columns_fail():
    with pytest.raises(ValueError,match="missing required columns"):
        validate_frame("orders",pd.DataFrame({"order_id":[]}))

def test_invalid_quantity_rejected():
    df=pd.DataFrame([{"order_item_id":"I1","order_id":"O1","product_id":"P1","quantity":-1,"unit_price":4}])
    accepted,rejected=validate_frame("order_items",df)
    assert len(accepted)==0 and "positive" in rejected.iloc[0]._rejection_reason

def test_shipment_dates_must_be_in_chronological_order():
    df=pd.DataFrame([{
        "shipment_id":"S1","order_id":"O1","warehouse_id":"W1",
        "ship_date":"2025-01-03","promised_delivery_date":"2025-01-02",
        "actual_delivery_date":"2025-01-01",
    }])
    accepted,rejected=validate_frame("shipments",df)
    assert accepted.empty
    assert "precedes ship_date" in rejected.iloc[0]._rejection_reason

def test_local_pipeline_outputs_and_dedupes(tmp_path):
    raw,processed,reports=tmp_path/"raw",tmp_path/"processed",tmp_path/"reports"
    generate_data(raw,30,4)
    result=ingest_csvs(raw,processed,reports,batch_id="test-batch")
    assert result["status"]=="SUCCESS" and result["rejected_records"]>0
    assert result["source_rows"] > result["accepted_records"]
    assert result["quality_score_pct"] < 100
    counts=transform(processed)
    assert "fact_orders" in counts and "monthly_revenue" in counts
    orders=pd.read_csv(processed/"orders.csv")
    assert not orders.order_id.duplicated().any()
    assert "O000006" not in set(orders.order_id)
    assert result["duplicate_rows_deduplicated"] == 1

def test_missing_source_directory_fails_explicitly(tmp_path):
    result=ingest_csvs(tmp_path/"missing",tmp_path/"processed",tmp_path/"reports",batch_id="missing-source")
    assert result["status"]=="FAILED"
    assert "No CSV source files" in result["error"]
    assert result["quality_score_pct"] is None

def test_batch_id_cannot_escape_report_directory(tmp_path):
    with pytest.raises(ValueError,match="batch_id"):
        ingest_csvs(tmp_path/"raw",tmp_path/"processed",tmp_path/"reports",batch_id="../unsafe")

def test_snowflake_pipeline_invokes_warehouse_adapter(tmp_path,monkeypatch):
    raw,processed,reports=tmp_path/"raw",tmp_path/"processed",tmp_path/"reports"
    monkeypatch.setattr(pipeline,"RAW_DIR",raw)
    monkeypatch.setattr(pipeline,"PROCESSED_DIR",processed)
    monkeypatch.setattr(pipeline,"REPORTS_DIR",reports)
    from supplychainiq.warehouse import snowflake
    calls=[]

    def fake_run_snowflake_batch(raw_dir,batch_id,local_summary=None):
        calls.append((raw_dir,batch_id,local_summary))
        return {"status":"SUCCESS"}

    monkeypatch.setattr(snowflake,"run_snowflake_batch",fake_run_snowflake_batch)
    result=pipeline.run_pipeline(generate=True,orders=20,seed=5,backend="snowflake")

    assert result["status"]=="SUCCESS"
    assert result["warehouse"]=={"status":"SUCCESS"}
    assert calls[0][0]==raw
    assert calls[0][1]==result["batch_id"]
    assert calls[0][2]["source_rows"]==result["source_rows"]
