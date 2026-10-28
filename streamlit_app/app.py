"""SupplyChainIQ business dashboard for local CSV and Snowflake modes."""
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supplychainiq.config import BACKEND, PROCESSED_DIR, REPORTS_DIR
from supplychainiq.pipeline import run_pipeline

st.set_page_config(page_title="SupplyChainIQ | Supply Chain Intelligence", page_icon="📦", layout="wide")
st.title("📦 SupplyChainIQ | Supply Chain Intelligence")
st.caption("Synthetic supply-chain data for learning and demonstration. Not Logitech production data.")

if BACKEND not in {"local", "snowflake"}:
    st.error(f"Unsupported backend {BACKEND!r}. Set SUPPLYCHAINIQ_BACKEND to 'local' or 'snowflake'.")
    st.stop()

snowflake_data = {}
if BACKEND == "snowflake":
    from supplychainiq.warehouse.snowflake import fetch_dashboard_data

    try:
        snowflake_data = fetch_dashboard_data()
    except RuntimeError as exc:
        st.error(f"Snowflake dashboard is unavailable: {exc}")
        st.stop()

with st.sidebar:
    st.header("Controls")
    st.info(f"Backend: {BACKEND.title()}")
    if st.button("Run pipeline now", type="primary"):
        with st.spinner("Generating, validating and transforming source data…"):
            try:
                result = run_pipeline(generate=True, backend=BACKEND)
            except RuntimeError as exc:
                st.error(f"Pipeline failed: {exc}")
            else:
                if result["status"] == "SUCCESS":
                    st.success(f"Pipeline status: {result['status']}")
                else:
                    st.error(
                        f"Pipeline status: {result['status']}. "
                        "Check the pipeline monitoring report for details."
                    )
                if BACKEND == "snowflake":
                    snowflake_data = fetch_dashboard_data()


def read(name: str) -> pd.DataFrame:
    if BACKEND == "snowflake":
        return snowflake_data.get(name, pd.DataFrame())
    path = PROCESSED_DIR / f"{name}.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


inventory = read("inventory_analytics")
shipments = read("shipment_analytics")
if BACKEND == "local" and not (PROCESSED_DIR / "fact_orders.csv").exists():
    st.warning(
        "No pipeline output found yet. Click **Run pipeline now** "
        "or run `python -m supplychainiq.pipeline`."
    )
    st.stop()

fact = read("fact_orders")
if BACKEND == "snowflake" and fact.empty:
    st.info("No warehouse analytics found yet. Run the Snowflake pipeline after provisioning the database.")

if not fact.empty and "order_date" in fact:
    fact["order_date"] = pd.to_datetime(fact.order_date, errors="coerce")
    min_date = fact.order_date.min().date() if fact.order_date.notna().any() else None
    max_date = fact.order_date.max().date() if fact.order_date.notna().any() else None
    if min_date and max_date:
        selected = st.date_input(
            "Order date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        if isinstance(selected, tuple) and len(selected) == 2:
            fact = fact[fact.order_date.dt.date.between(selected[0], selected[1])]

revenue = pd.to_numeric(fact.get("revenue", pd.Series(dtype=float)), errors="coerce").sum()
order_count = fact.order_id.nunique() if "order_id" in fact else 0
on_time_values = (
    shipments.on_time.astype(str).str.lower().eq("true")
    if not shipments.empty and "on_time" in shipments
    else pd.Series(dtype=bool)
)
on_time_pct = on_time_values.mean() * 100 if not on_time_values.empty else 0
inventory_units = pd.to_numeric(
    inventory.get("quantity_on_hand", pd.Series(dtype=float)), errors="coerce"
).sum()
low_stock = (
    int(inventory.stock_risk.astype(str).str.lower().eq("true").sum())
    if not inventory.empty and "stock_risk" in inventory
    else 0
)
fulfillment = pd.to_numeric(
    shipments.get("transit_days", pd.Series(dtype=float)), errors="coerce"
).dropna().mean()

metrics = st.columns(6)
metrics[0].metric("Orders", f"{order_count:,}")
metrics[1].metric("Revenue", f"${revenue:,.0f}")
metrics[2].metric("On-time delivery", f"{on_time_pct:.1f}%")
metrics[3].metric("Units in inventory", f"{inventory_units:,.0f}")
metrics[4].metric("Low-stock rows", f"{low_stock:,}")
metrics[5].metric("Avg. transit days", f"{fulfillment:.1f}" if pd.notna(fulfillment) else "N/A")

tabs = st.tabs(
    [
        "Executive Overview",
        "Order Analytics",
        "Inventory Analytics",
        "Logistics Analytics",
        "Supplier Analytics",
        "Pipeline Monitoring",
    ]
)

with tabs[0]:
    chart_columns = st.columns(2)
    monthly = read("monthly_revenue")
    if not monthly.empty:
        chart_columns[0].plotly_chart(
            px.line(monthly, x="month", y="revenue", markers=True, title="Monthly revenue"),
            width="stretch",
        )
        chart_columns[1].plotly_chart(
            px.bar(monthly, x="month", y="orders", title="Orders by month"),
            width="stretch",
        )
    st.subheader("Highest revenue products")
    top_products = read("top_products")
    if not top_products.empty:
        st.dataframe(top_products.head(10), width="stretch", hide_index=True)

with tabs[1]:
    top_products = read("top_products")
    if not top_products.empty:
        st.plotly_chart(
            px.bar(
                top_products.head(20).sort_values("revenue"),
                x="revenue",
                y="product_name",
                color="category",
                orientation="h",
                title="Top products by revenue",
            ),
            width="stretch",
        )
    if not fact.empty:
        st.dataframe(fact.head(100), width="stretch", hide_index=True)

with tabs[2]:
    if not inventory.empty:
        inventory_by_warehouse = inventory.groupby("warehouse_id", as_index=False).quantity_on_hand.sum()
        st.plotly_chart(
            px.bar(
                inventory_by_warehouse,
                x="warehouse_id",
                y="quantity_on_hand",
                title="Units on hand by warehouse",
            ),
            width="stretch",
        )
        st.subheader("Stockout-risk inventory")
        risk = inventory.stock_risk.astype(str).str.lower().eq("true")
        st.dataframe(inventory[risk], width="stretch", hide_index=True)

with tabs[3]:
    if not shipments.empty:
        valid_shipments = shipments.dropna(subset=["actual_delivery_date"])
        st.plotly_chart(
            px.histogram(
                valid_shipments,
                x="transit_days",
                color="on_time",
                title="Transit duration distribution",
            ),
            width="stretch",
        )
        st.dataframe(shipments.head(100), width="stretch", hide_index=True)

with tabs[4]:
    suppliers = read("dim_supplier")
    if not suppliers.empty:
        st.dataframe(
            suppliers.sort_values("lead_time_days", ascending=False),
            width="stretch",
            hide_index=True,
        )
    st.caption(
        "Supplier actual lead-time metrics require populated purchase-order receipt dates."
    )

with tabs[5]:
    if BACKEND == "snowflake":
        pipeline_runs = read("pipeline_runs")
        if not pipeline_runs.empty:
            st.dataframe(pipeline_runs, width="stretch", hide_index=True)
            st.json(pipeline_runs.iloc[-1].to_dict())
        else:
            st.info("No Snowflake pipeline runs have been recorded.")
        rejected_records = read("rejected_records")
        if not rejected_records.empty:
            st.subheader("Rejected warehouse records")
            st.dataframe(rejected_records, width="stretch", hide_index=True)
    else:
        run_history = REPORTS_DIR / "pipeline_runs.jsonl"
        if run_history.exists():
            records = [
                json.loads(line)
                for line in run_history.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if records:
                history = pd.DataFrame(
                    [
                        {
                            "batch_id": run.get("batch_id"),
                            "status": run.get("status"),
                            "started_at": run.get("started_at"),
                            "rejected_records": run.get("rejected_records"),
                            "quality_score_pct": run.get("quality_score_pct"),
                        }
                        for run in records[-30:][::-1]
                    ]
                )
                st.dataframe(history, width="stretch", hide_index=True)
                st.json(records[-1])
        else:
            st.info("No pipeline run history found.")
        rejected_files = list(REPORTS_DIR.glob("rejected_records_*.csv"))
        if rejected_files:
            st.subheader("Latest rejected records")
            latest_rejected = max(rejected_files, key=lambda path: (path.stat().st_mtime, path.name))
            st.dataframe(pd.read_csv(latest_rejected), width="stretch", hide_index=True)

st.divider()
st.caption(
    f"{BACKEND.title()} mode. Local mode uses generated CSVs and Pandas; "
    "Snowflake mode requires a provisioned, separately configured warehouse."
)
