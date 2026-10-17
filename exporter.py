from __future__ import annotations

import pandas as pd

from csv_loader import LoadedCsv, replace_price_columns
from format_adapter import SHOPIFY


def export_csv(frame: pd.DataFrame, loaded: LoadedCsv, file_format: str = "supplier") -> bytes:
    """Replace only the two price columns while preserving all other raw CSV text."""
    source_columns = (
        ("Variant Price", "Variant Compare At Price")
        if file_format == SHOPIFY
        else ("price", "compare_at_price")
    )
    return replace_price_columns(loaded, frame, source_columns)
