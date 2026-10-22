from __future__ import annotations

import pandas as pd

from csv_loader import LoadedCsv, load_csv_bytes, replace_price_columns
from format_adapter import SHOPIFY

# In Shopify files "no compare-at price" is an empty cell. The supplier format
# uses "0" for that. When True, a "0" that this tool introduced into a Shopify
# file is written as an empty cell instead; a "0" already in the source stays.
SHOPIFY_EMPTY_COMPARE = True


def _source_columns(file_format: str) -> tuple[str, str]:
    return (
        ("Variant Price", "Variant Compare At Price")
        if file_format == SHOPIFY
        else ("price", "compare_at_price")
    )


def _export_frame(frame: pd.DataFrame, loaded: LoadedCsv, file_format: str) -> pd.DataFrame:
    """Return the frame whose price columns are exactly what gets written."""
    if file_format != SHOPIFY or not SHOPIFY_EMPTY_COMPARE:
        return frame
    source_compare = loaded.frame["Variant Compare At Price"].astype(str)
    introduced_zero = frame["compare_at_price"].astype(str).eq("0") & source_compare.ne("0")
    if not introduced_zero.any():
        return frame
    adjusted = frame.copy()
    adjusted.loc[introduced_zero, "compare_at_price"] = ""
    return adjusted


def export_csv(frame: pd.DataFrame, loaded: LoadedCsv, file_format: str = "supplier") -> bytes:
    """Replace only the two price columns while preserving all other raw CSV text."""
    return replace_price_columns(
        loaded, _export_frame(frame, loaded, file_format), _source_columns(file_format)
    )


def verify_export(
    output_bytes: bytes,
    original_bytes: bytes,
    loaded: LoadedCsv,
    frame: pd.DataFrame,
    file_format: str = "supplier",
    priced_handles: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Independently re-read the exported bytes and compare them with the source.

    This checks the real file the user will download, not the in-memory plan:
    1. encoding, BOM, delimiter, line endings and row count are unchanged;
    2. every cell outside the two price columns is identical to the original;
    3. the price columns equal the planned values;
    4. all variant rows of a priced product share one price.
    """
    issues: list[str] = []
    try:
        reloaded = load_csv_bytes(output_bytes)
    except Exception as exc:  # noqa: BLE001 - any parse failure means a bad export
        return (f"导出文件无法重新读取：{exc}",)

    if reloaded.encoding != loaded.encoding:
        issues.append(f"导出文件编码与原文件不一致（{loaded.encoding} → {reloaded.encoding}）")
    if output_bytes.startswith(b"\xef\xbb\xbf") != original_bytes.startswith(b"\xef\xbb\xbf"):
        issues.append("导出文件的 BOM 状态与原文件不一致")
    if reloaded.delimiter != loaded.delimiter:
        issues.append("导出文件的分隔符与原文件不一致")
    if reloaded.row_endings != loaded.row_endings:
        issues.append("导出文件的换行符与原文件不一致")
    if len(reloaded.raw_rows) != len(loaded.raw_rows):
        issues.append(f"导出行数不一致（原 {len(loaded.raw_rows)} 行，导出 {len(reloaded.raw_rows)} 行）")
        return tuple(issues)

    source_price_columns = _source_columns(file_format)
    original_columns = list(loaded.frame.columns)
    if list(reloaded.frame.columns) != original_columns:
        issues.append("导出文件的表头与原文件不一致")
        return tuple(issues)

    other_columns = [column for column in original_columns if column not in source_price_columns]
    # Compare raw rows (not parsed values) so quoting and spacing are covered too.
    price_indexes = {original_columns.index(column) for column in source_price_columns}
    changed_cells = 0
    for row_number, (before, after) in enumerate(zip(loaded.raw_rows, reloaded.raw_rows)):
        for column_index, (left, right) in enumerate(zip(before, after)):
            if column_index not in price_indexes and left != right:
                changed_cells += 1
    if changed_cells:
        issues.append(f"有 {changed_cells} 个非价格单元格与原文件不一致")

    expected = _export_frame(frame, loaded, file_format)
    price_column, compare_column = source_price_columns
    exported_price = reloaded.frame[price_column].astype(str).str.strip().reset_index(drop=True)
    exported_compare = reloaded.frame[compare_column].astype(str).str.strip().reset_index(drop=True)
    planned_price = expected["price"].astype(str).str.strip().reset_index(drop=True)
    planned_compare = expected["compare_at_price"].astype(str).str.strip().reset_index(drop=True)
    mismatched = int((exported_price.ne(planned_price) | exported_compare.ne(planned_compare)).sum())
    if mismatched:
        issues.append(f"有 {mismatched} 行价格与计划值不一致")

    if priced_handles and "Handle" in reloaded.frame.columns:
        handles = reloaded.frame["Handle"].astype(str).str.strip().reset_index(drop=True)
        wanted = set(priced_handles)
        has_price = exported_price.ne("")
        scoped = pd.DataFrame({"handle": handles, "price": exported_price})[has_price & handles.isin(wanted)]
        inconsistent = scoped.groupby("handle")["price"].nunique()
        bad = list(inconsistent[inconsistent > 1].index[:5])
        if bad:
            issues.append("同一商品的变体价格不一致：" + "、".join(bad))
    return tuple(issues)
