"""Reusable structural and business data-quality checks."""
from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = {
    "orders": {"order_id", "customer_id", "order_date", "status"},
    "order_items": {"order_item_id", "order_id", "product_id", "quantity", "unit_price"},
    "products": {"product_id", "product_name", "category", "unit_price", "supplier_id", "reorder_level"},
    "customers": {"customer_id", "region", "customer_segment"},
    "warehouses": {"warehouse_id", "warehouse_name", "region"},
    "inventory": {
        "inventory_id", "product_id", "warehouse_id", "snapshot_date", "quantity_on_hand", "unit_cost"
    },
    "suppliers": {"supplier_id", "supplier_name", "country", "lead_time_days"},
    "purchase_orders": {
        "purchase_order_id", "supplier_id", "product_id", "order_date", "quantity", "received_date"
    },
    "shipments": {
        "shipment_id", "order_id", "warehouse_id", "ship_date",
        "promised_delivery_date", "actual_delivery_date"
    },
}

KEY_COLUMNS = {
    "orders": ("order_id", "customer_id"),
    "order_items": ("order_item_id", "order_id", "product_id"),
    "products": ("product_id", "product_name", "supplier_id"),
    "customers": ("customer_id",),
    "warehouses": ("warehouse_id",),
    "inventory": ("inventory_id", "product_id", "warehouse_id"),
    "suppliers": ("supplier_id",),
    "purchase_orders": ("purchase_order_id", "supplier_id", "product_id"),
    "shipments": ("shipment_id", "order_id", "warehouse_id"),
}


def validate_frame(name: str, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return accepted and rejected rows, retaining a reason for every rejection."""
    missing = REQUIRED_COLUMNS.get(name, set()) - set(df.columns)
    if missing:
        raise ValueError(f"{name}: missing required columns: {', '.join(sorted(missing))}")

    work = df.copy()
    reasons = pd.Series("", index=work.index, dtype="object")

    def reject(mask: pd.Series, reason: str) -> None:
        nonlocal reasons
        mask = mask.fillna(False)
        reasons.loc[mask] = reasons.loc[mask].map(
            lambda existing: f"{existing}; {reason}" if existing else reason
        )

    for column in KEY_COLUMNS.get(name, ()):
        reject(work[column].isna() | work[column].astype(str).str.strip().eq(""), f"{column} is required")

    numeric_rules = {
        "order_items": {
            "quantity": ("positive", lambda values: values <= 0),
            "unit_price": ("non-negative", lambda values: values < 0),
        },
        "products": {
            "unit_price": ("positive", lambda values: values <= 0),
            "reorder_level": ("non-negative", lambda values: values < 0),
        },
        "inventory": {
            "quantity_on_hand": ("non-negative", lambda values: values < 0),
            "unit_cost": ("non-negative", lambda values: values < 0),
        },
        "suppliers": {"lead_time_days": ("non-negative", lambda values: values < 0)},
        "purchase_orders": {"quantity": ("positive", lambda values: values <= 0)},
    }
    for column, (description, invalid_values) in numeric_rules.get(name, {}).items():
        values = pd.to_numeric(work[column], errors="coerce")
        reject(values.isna() | invalid_values(values), f"{column} must be {description}")

    date_columns = {
        "orders": ("order_date",),
        "inventory": ("snapshot_date",),
        "purchase_orders": ("order_date", "received_date"),
        "shipments": ("ship_date", "promised_delivery_date", "actual_delivery_date"),
    }.get(name, ())
    for column in date_columns:
        parsed = pd.to_datetime(work[column], errors="coerce")
        required = column not in {"received_date", "actual_delivery_date"}
        supplied = work[column].astype("string").fillna("").ne("")
        invalid = parsed.isna() & (required | supplied)
        reject(invalid, f"invalid date in {column}")

    if name == "shipments":
        ship_date = pd.to_datetime(work.ship_date, errors="coerce")
        promised_date = pd.to_datetime(work.promised_delivery_date, errors="coerce")
        actual_date = pd.to_datetime(work.actual_delivery_date, errors="coerce")
        reject(promised_date.lt(ship_date), "promised_delivery_date precedes ship_date")
        reject(actual_date.notna() & actual_date.lt(ship_date), "actual_delivery_date precedes ship_date")
    elif name == "purchase_orders":
        order_date = pd.to_datetime(work.order_date, errors="coerce")
        received_date = pd.to_datetime(work.received_date, errors="coerce")
        reject(received_date.notna() & received_date.lt(order_date), "received_date precedes order_date")

    rejected_mask = reasons.ne("")
    accepted = work.loc[~rejected_mask].copy()
    rejected = work.loc[rejected_mask].copy()
    rejected["_rejection_reason"] = reasons.loc[rejected_mask]
    rejected["source_table"] = name
    return accepted, rejected
