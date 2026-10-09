from __future__ import annotations

import pandas as pd

from csv_loader import LoadedCsv, replace_price_columns


def export_csv(frame: pd.DataFrame, loaded: LoadedCsv) -> bytes:
    """Replace only the two price columns while preserving all other raw CSV text."""
    return replace_price_columns(loaded, frame)
