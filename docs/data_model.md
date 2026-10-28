# Data model

## Core grains

- `FACT_ORDERS`: one row per order item; revenue is quantity × unit price. The fact stores the product surrogate key for historical product attribution.
- `FACT_INVENTORY_SNAPSHOT`: one row per inventory observation, keyed by source inventory ID and associated with a product and warehouse.
- `FACT_SHIPMENTS`: one row per shipment; on-time and transit-day metrics are null when actual delivery is not yet known.
- `FACT_PURCHASE_ORDERS`: one row per simulated purchase-order item; actual lead time is null until a receipt date exists.

## Dimensions

`DIM_PRODUCT` is SCD Type 2 and tracks product name, category, price, and supplier assignment. A changed product expires its current version and gets a new surrogate key. `PRODUCT_SK` identifies the dimension version; `PRODUCT_ID` is the business key. Effective timestamps and `IS_CURRENT` retain history.

`DIM_CUSTOMER`, `DIM_WAREHOUSE`, and `DIM_SUPPLIER` are current-state dimensions maintained with repeat-safe `MERGE` statements. Analytics views expose dashboard-ready names and metrics while keeping the core fact grains explicit.

The local CSV pipeline models the same business metrics with Pandas but writes flat analytics datasets rather than warehouse surrogate keys.
