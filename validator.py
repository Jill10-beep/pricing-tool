from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import pandas as pd

from csv_loader import product_mask, variant_mask
from pricing import parse_number


REQUIRED_COLUMNS = {
    "Handle",
    "Title",
    "category",
    "price",
    "compare_at_price",
    "sku_code",
    "inventory_quantity",
    "Image Src",
}


@dataclass(frozen=True)
class ValidationSummary:
    rows: int
    products: int
    variants: int
    image_only_rows: int
    duplicate_skus: int
    missing_skus: int
    invalid_prices: int
    zero_prices: int
    invalid_image_urls: int
    discounted_variants: int
    excessive_discounts: int
    missing_columns: tuple[str, ...]


def _valid_url(value: object) -> bool:
    text = str(value).strip()
    if not text:
        return True
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_frame(frame: pd.DataFrame, max_discount: float = 0.20) -> ValidationSummary:
    missing_columns = tuple(sorted(REQUIRED_COLUMNS - set(frame.columns)))
    variants = variant_mask(frame)
    products = product_mask(frame)

    if "Image Src" in frame:
        has_image = frame["Image Src"].astype(str).str.strip().ne("")
        invalid_image_urls = int((~frame["Image Src"].map(_valid_url)).sum())
    else:
        has_image = pd.Series(False, index=frame.index)
        invalid_image_urls = 0

    if "sku_code" in frame:
        sku = frame.loc[variants, "sku_code"].astype(str).str.strip()
        duplicate_skus = int(sku.duplicated(keep=False).sum())
    else:
        duplicate_skus = 0

    prices = frame.get("price", pd.Series("", index=frame.index)).map(parse_number)
    compares = frame.get("compare_at_price", pd.Series("", index=frame.index)).map(parse_number)
    invalid_prices = int((variants & prices.isna()).sum())
    zero_prices = int((variants & prices.eq(0)).sum())

    rates = []
    for price, compare, is_variant in zip(prices, compares, variants):
        if is_variant and price and compare and compare > price:
            rates.append(1 - price / compare)

    return ValidationSummary(
        rows=len(frame),
        products=int(products.sum()),
        variants=int(variants.sum()),
        image_only_rows=int(((~variants) & has_image).sum()),
        duplicate_skus=duplicate_skus,
        missing_skus=int((products & ~variants).sum()),
        invalid_prices=invalid_prices,
        zero_prices=zero_prices,
        invalid_image_urls=invalid_image_urls,
        discounted_variants=len(rates),
        excessive_discounts=sum(rate > max_discount for rate in rates),
        missing_columns=missing_columns,
    )
