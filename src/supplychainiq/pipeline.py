"""Run the local pipeline and, optionally, publish a batch to Snowflake."""
from __future__ import annotations

import argparse
import logging
import uuid

from .config import BACKEND, ORDERS_COUNT, PROCESSED_DIR, RANDOM_SEED, RAW_DIR, REPORTS_DIR
from .data_generator import generate_data
from .ingestion.local import ingest_csvs
from .transformations.local import transform

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def run_pipeline(
    generate: bool = True,
    orders: int = ORDERS_COUNT,
    seed: int = RANDOM_SEED,
    backend: str = BACKEND,
) -> dict:
    if backend not in {"local", "snowflake"}:
        raise ValueError(f"Unsupported backend {backend!r}; choose 'local' or 'snowflake'")
    if generate:
        generate_data(RAW_DIR, orders, seed)

    batch_id = f"batch-{uuid.uuid4().hex}"
    result = ingest_csvs(RAW_DIR, PROCESSED_DIR, REPORTS_DIR, batch_id=batch_id)
    if result["status"] == "FAILED":
        return result
    result["transformed_outputs"] = transform(PROCESSED_DIR)

    if backend == "snowflake":
        from .warehouse.snowflake import run_snowflake_batch

        result["warehouse"] = run_snowflake_batch(RAW_DIR, batch_id, local_summary=result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-generate", action="store_true")
    parser.add_argument("--orders", type=int, default=ORDERS_COUNT)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--backend", choices=("local", "snowflake"), default=BACKEND)
    args = parser.parse_args()
    pipeline_result = run_pipeline(
        generate=not args.no_generate,
        orders=args.orders,
        seed=args.seed,
        backend=args.backend,
    )
    print(pipeline_result)
    raise SystemExit(1 if pipeline_result["status"] == "FAILED" else 0)
