"""Local Pandas transformations that produce dashboard-ready analytics."""
from pathlib import Path

import pandas as pd


def transform(processed_dir: Path) -> dict[str,int]:
    def read(n):
        p=processed_dir/f"{n}.csv"; return pd.read_csv(p) if p.exists() else pd.DataFrame()
    orders,items,products,inventory,shipments,suppliers=map(read,["orders","order_items","products","inventory","shipments","suppliers"])
    if not orders.empty and not items.empty:
        detail=items.merge(orders,on="order_id",how="left",suffixes=("","_order")).merge(products,on="product_id",how="left",suffixes=("","_product"))
        detail["revenue"] = pd.to_numeric(detail.quantity,errors="coerce")*pd.to_numeric(detail.unit_price,errors="coerce")
        detail["order_date"]=pd.to_datetime(detail.order_date,errors="coerce")
        detail.to_csv(processed_dir/"fact_orders.csv",index=False)
        monthly=detail.dropna(subset=["order_date"]).assign(month=lambda d:d.order_date.dt.to_period("M").astype(str)).groupby("month",as_index=False).agg(orders=("order_id","nunique"),revenue=("revenue","sum"),units=("quantity","sum"))
        monthly.to_csv(processed_dir/"monthly_revenue.csv",index=False)
        top=detail.groupby(["product_id","product_name","category"],dropna=False,as_index=False).agg(units_sold=("quantity","sum"),revenue=("revenue","sum")).sort_values("revenue",ascending=False)
        top.to_csv(processed_dir/"top_products.csv",index=False)
    if not inventory.empty and not products.empty:
        inv=inventory.merge(products[["product_id","product_name","category","reorder_level"]],on="product_id",how="left")
        inv["quantity_on_hand"]=pd.to_numeric(inv.quantity_on_hand,errors="coerce")
        inv["stock_risk"]=inv.quantity_on_hand < pd.to_numeric(inv.reorder_level,errors="coerce")
        inv.to_csv(processed_dir/"inventory_analytics.csv",index=False)
    if not shipments.empty:
        shipments["promised_delivery_date"]=pd.to_datetime(shipments.promised_delivery_date,errors="coerce")
        shipments["actual_delivery_date"]=pd.to_datetime(shipments.actual_delivery_date,errors="coerce")
        shipments["on_time"]=(shipments.actual_delivery_date<=shipments.promised_delivery_date)
        shipments["transit_days"]=(shipments.actual_delivery_date-pd.to_datetime(shipments.ship_date,errors="coerce")).dt.days
        shipments.to_csv(processed_dir/"shipment_analytics.csv",index=False)
        if not suppliers.empty and "supplier_id" in suppliers:
            suppliers.to_csv(processed_dir/"dim_supplier.csv",index=False)
    return {p.stem:len(pd.read_csv(p)) for p in processed_dir.glob("*.csv")}
