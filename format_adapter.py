from __future__ import annotations

import pandas as pd


SUPPLIER = "supplier"
SHOPIFY = "shopify"


def prepare_frame(frame: pd.DataFrame, file_format: str) -> pd.DataFrame:
    """Return a canonical pricing frame without changing the loaded source frame."""
    if file_format == SUPPLIER:
        required = {"Handle", "Title", "category", "price", "compare_at_price"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError("这不是可识别的供应商格式，缺少字段：" + ", ".join(missing))
        return frame.copy(deep=True)

    if file_format != SHOPIFY:
        raise ValueError("未知的产品包格式。")

    required = {"Handle", "Title", "Variant Price", "Variant Compare At Price"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("这不是可识别的 Shopify CSV，缺少字段：" + ", ".join(missing))

    output = frame.copy(deep=True)
    output["price"] = output["Variant Price"]
    output["compare_at_price"] = output["Variant Compare At Price"]
    output["sku_code"] = output.get("Variant SKU", pd.Series("", index=output.index))
    output["inventory_quantity"] = output.get("Variant Inventory Qty", pd.Series("", index=output.index))
    output["Image Src"] = output.get("Image Src", pd.Series("", index=output.index))

    product_category = output.get("Product Category", pd.Series("", index=output.index)).astype(str).str.strip()
    product_type = output.get("Type", pd.Series("", index=output.index)).astype(str).str.strip()
    output["category"] = product_category.where(product_category.ne(""), product_type)
    if not output["category"].astype(str).str.strip().ne("").any():
        raise ValueError("Shopify 文件的 Product Category 和 Type 都为空，无法识别商品品类。")
    return output


def output_suffix(file_format: str) -> str:
    return "-Shopify正确价格.csv" if file_format == SHOPIFY else "-正确价格.csv"
