"""Generate reproducible synthetic supply-chain source files, including bad records."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ORDERS_COUNT, RANDOM_SEED, RAW_DIR


def generate_data(output_dir: Path = RAW_DIR, orders_count: int = ORDERS_COUNT, seed: int = RANDOM_SEED) -> dict[str, int]:
    if orders_count < 1:
        raise ValueError("orders_count must be at least 1")
    rng = np.random.default_rng(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    n_products, n_customers, n_warehouses, n_suppliers = 80, 250, 6, 18
    products = pd.DataFrame({"product_id":[f"P{i:04d}" for i in range(1,n_products+1)], "product_name":[f"Device {i:03d}" for i in range(1,n_products+1)], "category":rng.choice(["Keyboards","Mice","Webcams","Headsets","Accessories"],n_products), "unit_price":np.round(rng.uniform(12,250,n_products),2), "supplier_id":rng.choice([f"S{i:03d}" for i in range(1,n_suppliers+1)],n_products), "reorder_level":rng.integers(10,50,n_products)})
    customers = pd.DataFrame({"customer_id":[f"C{i:05d}" for i in range(1,n_customers+1)],"region":rng.choice(["North America","Europe","APAC","LATAM"],n_customers),"customer_segment":rng.choice(["Consumer","SMB","Enterprise"],n_customers)})
    warehouses = pd.DataFrame({"warehouse_id":[f"W{i:02d}" for i in range(1,n_warehouses+1)],"warehouse_name":[f"Warehouse {i}" for i in range(1,n_warehouses+1)],"region":rng.choice(["North America","Europe","APAC"],n_warehouses)})
    suppliers = pd.DataFrame({"supplier_id":[f"S{i:03d}" for i in range(1,n_suppliers+1)],"supplier_name":[f"Supplier {i:02d}" for i in range(1,n_suppliers+1)],"country":rng.choice(["India","China","Vietnam","Mexico","Germany"],n_suppliers),"lead_time_days":rng.integers(2,31,n_suppliers)})
    order_ids=[f"O{i:06d}" for i in range(1,orders_count+1)]
    order_dates=pd.to_datetime("2025-01-01") + pd.to_timedelta(rng.integers(0,600,orders_count),unit="D")
    orders=pd.DataFrame({"order_id":order_ids,"customer_id":rng.choice(customers.customer_id,orders_count),"order_date":order_dates.strftime("%Y-%m-%d"),"status":rng.choice(["delivered","shipped","processing","cancelled"],orders_count,p=[.72,.12,.11,.05])})
    items=[]
    for oid in order_ids:
        for _ in range(int(rng.integers(1,4))):
            p=products.iloc[int(rng.integers(0,len(products)))]
            items.append({"order_item_id":f"I{len(items)+1:07d}","order_id":oid,"product_id":p.product_id,"quantity":int(rng.integers(1,6)),"unit_price":float(p.unit_price)})
    order_items=pd.DataFrame(items)
    inventory=pd.DataFrame([{"inventory_id":f"INV{i+1:06d}","product_id":p.product_id,"warehouse_id":w,"snapshot_date":pd.Timestamp("2026-10-01").strftime("%Y-%m-%d"),"quantity_on_hand":int(rng.integers(0,180)),"unit_cost":round(float(p.unit_price)*float(rng.uniform(.45,.75)),2)} for i,(p,w) in enumerate((products.iloc[j % n_products], f"W{int(rng.integers(1,n_warehouses+1)):02d}") for j in range(n_products*2))])
    purchase_orders=pd.DataFrame({"purchase_order_id":[f"PO{i:06d}" for i in range(1,orders_count//3+2)],"supplier_id":rng.choice(suppliers.supplier_id,orders_count//3+1),"product_id":rng.choice(products.product_id,orders_count//3+1),"order_date":(pd.Timestamp("2025-01-01")+pd.to_timedelta(rng.integers(0,600,orders_count//3+1),unit="D")).strftime("%Y-%m-%d"),"quantity":rng.integers(10,300,orders_count//3+1),"received_date":""})
    shipments=orders[["order_id","order_date"]].copy(); shipments["shipment_id"]=[f"SH{i:06d}" for i in range(1,len(shipments)+1)]; shipments["warehouse_id"]=rng.choice(warehouses.warehouse_id,len(shipments)); shipments["ship_date"]=(pd.to_datetime(shipments.order_date)+pd.to_timedelta(rng.integers(1,6,len(shipments)),unit="D")).dt.strftime("%Y-%m-%d"); shipments["promised_delivery_date"]=(pd.to_datetime(shipments.ship_date)+pd.to_timedelta(rng.integers(2,8,len(shipments)),unit="D")).dt.strftime("%Y-%m-%d"); shipments["actual_delivery_date"]=(pd.to_datetime(shipments.promised_delivery_date)+pd.to_timedelta(rng.integers(-2,6,len(shipments)),unit="D")).dt.strftime("%Y-%m-%d")
    # Preserve intentionally bad raw records for the quality framework to catch.
    if len(order_items): order_items.loc[0,"quantity"]=-2
    if len(orders)>5: orders.loc[5,"customer_id"]="C99999"
    if len(inventory)>4: inventory.loc[2,"quantity_on_hand"]=-7
    if len(shipments)>3: shipments.loc[3,"actual_delivery_date"]="not-a-date"
    if len(orders)>10: orders=pd.concat([orders,orders.iloc[[10]]],ignore_index=True)
    datasets={"orders":orders,"order_items":order_items,"products":products,"customers":customers,"warehouses":warehouses,"inventory":inventory,"suppliers":suppliers,"purchase_orders":purchase_orders,"shipments":shipments}
    for name,df in datasets.items(): df.to_csv(output_dir/f"{name}.csv",index=False)
    return {k:len(v) for k,v in datasets.items()}

if __name__ == "__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--output-dir",type=Path,default=RAW_DIR); parser.add_argument("--orders",type=int,default=ORDERS_COUNT); parser.add_argument("--seed",type=int,default=RANDOM_SEED); args=parser.parse_args()
    print(generate_data(args.output_dir,args.orders,args.seed))
