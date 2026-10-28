"""Local CSV ingestion with batch lineage and idempotent output replacement."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from ..validation.checks import validate_frame

LOG = logging.getLogger(__name__)

FOREIGN_KEYS = {
    "orders": (("customer_id", "customers"),),
    "products": (("supplier_id", "suppliers"),),
    "order_items": (("order_id", "orders"), ("product_id", "products")),
    "inventory": (("product_id", "products"), ("warehouse_id", "warehouses")),
    "shipments": (("order_id", "orders"), ("warehouse_id", "warehouses")),
    "purchase_orders": (("supplier_id", "suppliers"), ("product_id", "products")),
}
REFERENCE_KEYS = {
    "customers": "customer_id",
    "suppliers": "supplier_id",
    "warehouses": "warehouse_id",
    "products": "product_id",
    "orders": "order_id",
    "order_items": "order_id",
}
REFERENCE_ORDER = ("customers", "suppliers", "warehouses", "products", "orders", "order_items")
KEY_COLUMNS = {
    "orders": "order_id",
    "order_items": "order_item_id",
    "products": "product_id",
    "customers": "customer_id",
    "warehouses": "warehouse_id",
    "inventory": "inventory_id",
    "suppliers": "supplier_id",
    "purchase_orders": "purchase_order_id",
    "shipments": "shipment_id",
}


def ingest_csvs(
    raw_dir: Path,
    processed_dir: Path,
    reports_dir: Path,
    batch_id: str | None = None,
) -> dict:
    processed_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    batch_id = batch_id or datetime.now(UTC).strftime("batch-%Y%m%dT%H%M%S%fZ")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", batch_id):
        raise ValueError("batch_id may contain only letters, numbers, underscores, and hyphens")

    started_at = datetime.now(UTC).isoformat()
    run = {
        "batch_id": batch_id,
        "started_at": started_at,
        "status": "SUCCESS",
        "files": {},
        "rejected_records": 0,
    }
    rejected_all = []
    paths = sorted(raw_dir.glob("*.csv"))
    if not paths:
        run["status"] = "FAILED"
        run["error"] = f"No CSV source files found in {raw_dir}"

    source_frames = {}
    source_errors = {}
    for path in paths:
        try:
            source_frames[path.stem] = pd.read_csv(path, keep_default_na=True)
        except (OSError, pd.errors.ParserError, UnicodeDecodeError) as exc:
            source_errors[path.stem] = str(exc)
            run["status"] = "FAILED"
            run["files"][path.stem] = {"source_file": path.name, "error": str(exc)}
            LOG.exception("Failed to read source file %s", path)

    references = {}
    for name in REFERENCE_ORDER:
        frame = source_frames.get(name)
        key = REFERENCE_KEYS[name]
        if frame is None:
            continue
        try:
            accepted, _ = validate_frame(name, frame)
        except ValueError:
            continue
        for column, parent in FOREIGN_KEYS.get(name, ()):
            parent_keys = references.get(parent)
            if parent_keys is None:
                accepted = accepted.iloc[0:0]
            else:
                accepted = accepted.loc[accepted[column].astype(str).isin(parent_keys)]
        references[name] = set(accepted[key].dropna().astype(str))

    for path in paths:
        name = path.stem
        if name in source_errors:
            continue
        df = source_frames[name]
        try:
            accepted, rejected = validate_frame(name, df)
            for column, parent in FOREIGN_KEYS.get(name, ()):
                if parent not in source_frames:
                    raise ValueError(f"{name}: required reference file {parent}.csv is missing")
                if parent not in references:
                    raise ValueError(f"{name}: reference key {parent}.{column} is unavailable")
                invalid = ~accepted[column].astype(str).isin(references[parent])
                if invalid.any():
                    fk_rejected = accepted.loc[invalid].copy()
                    fk_rejected["_rejection_reason"] = f"{column} references unknown {parent} key"
                    fk_rejected["source_table"] = name
                    rejected = pd.concat([rejected, fk_rejected], ignore_index=True, sort=False)
                    accepted = accepted.loc[~invalid].copy()

            accepted["_source_file"] = path.name
            accepted["_batch_id"] = batch_id
            accepted["_ingested_at"] = started_at
            key = KEY_COLUMNS.get(name)
            duplicate_count = 0
            if key and key in accepted:
                duplicate_count = int(accepted.duplicated(subset=[key], keep="last").sum())
                accepted = accepted.drop_duplicates(subset=[key], keep="last")
            accepted.to_csv(processed_dir / f"{name}.csv", index=False)
            if not rejected.empty:
                rejected_all.append(rejected.assign(_source_file=path.name, _batch_id=batch_id))
            run["files"][name] = {
                "source_file": path.name,
                "source_rows": len(df),
                "accepted_rows": len(accepted),
                "rejected_rows": len(rejected),
                "duplicate_rows_deduplicated": duplicate_count,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            LOG.info(
                "Ingested %s: %s accepted, %s rejected",
                path.name,
                len(accepted),
                len(rejected),
            )
        except (OSError, ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
            run["status"] = "FAILED"
            run["files"][name] = {"source_file": path.name, "error": str(exc)}
            LOG.exception("Failed ingest for %s", path)

    rejected_path = reports_dir / f"rejected_records_{batch_id}.csv"
    if rejected_all:
        pd.concat(rejected_all, ignore_index=True).to_csv(rejected_path, index=False)
        run["rejected_records"] = sum(len(frame) for frame in rejected_all)
    else:
        pd.DataFrame(columns=["source_table", "_rejection_reason"]).to_csv(rejected_path, index=False)

    source_rows = sum(file.get("source_rows", 0) for file in run["files"].values())
    run["source_rows"] = source_rows
    run["accepted_records"] = sum(file.get("accepted_rows", 0) for file in run["files"].values())
    run["duplicate_rows_deduplicated"] = sum(
        file.get("duplicate_rows_deduplicated", 0) for file in run["files"].values()
    )
    run["finished_at"] = datetime.now(UTC).isoformat()
    run["quality_score_pct"] = (
        round(100 * (1 - run["rejected_records"] / max(1, source_rows)), 2)
        if run["status"] == "SUCCESS"
        else None
    )
    with (reports_dir / "pipeline_runs.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(run) + "\n")
    (reports_dir / f"run_{batch_id}.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    return run
