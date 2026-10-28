# Data dictionary

| File | Grain | Main columns |
|---|---|---|
| orders.csv | one row per order (source can contain duplicate) | order_id, customer_id, order_date, status |
| order_items.csv | one row per order line | order_item_id, order_id, product_id, quantity, unit_price |
| products.csv | one row per product | product_id, category, unit_price, supplier_id, reorder_level |
| customers.csv | one row per customer | customer_id, region, customer_segment |
| warehouses.csv | one row per warehouse | warehouse_id, warehouse_name, region |
| inventory.csv | one product/warehouse inventory observation | inventory_id, product_id, warehouse_id, snapshot_date, quantity_on_hand, unit_cost |
| suppliers.csv | one row per supplier | supplier_id, country, lead_time_days |
| purchase_orders.csv | one row per purchase order item | purchase_order_id, supplier_id, product_id, order_date, quantity, received_date |
| shipments.csv | one row per order shipment | shipment_id, order_id, warehouse_id, ship_date, promised_delivery_date, actual_delivery_date |

Source files intentionally contain selected invalid values for data-quality demonstrations. Local ingestion appends `_source_file`, `_batch_id` and `_ingested_at` lineage columns to accepted files.
