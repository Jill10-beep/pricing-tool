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


def merge_exported_csv_files(
    outputs: list[tuple[str, bytes]],
) -> tuple[bytes | None, tuple[str, ...]]:
    """Combine verified result CSVs into one import-safe product package.

    The first file defines the exact schema, column order, delimiter, encoding
    and line-ending style.  Data rows from subsequent files are appended as raw
    CSV cells, so HTML, quotes and other non-price content are not rewritten.
    Files with incompatible schemas or Handles repeated across different source
    files are rejected instead of creating a package that a store may merge or
    parse incorrectly.
    """
    if not outputs:
        return None, ("没有可以合并的产品包。",)

    loaded_outputs: list[tuple[str, LoadedCsv]] = []
    issues: list[str] = []
    for name, data in outputs:
        try:
            loaded_outputs.append((name, load_csv_bytes(data)))
        except Exception as exc:  # noqa: BLE001 - any unreadable result is unsafe to merge
            issues.append(f"{name} 无法重新读取：{exc}")
    if issues:
        return None, tuple(issues)

    first_name, first = loaded_outputs[0]
    columns = list(first.frame.columns)
    delimiter = first.delimiter
    for name, loaded in loaded_outputs[1:]:
        if list(loaded.frame.columns) != columns:
            issues.append(f"{name} 的字段或字段顺序与 {first_name} 不一致")
        if loaded.delimiter != delimiter:
            issues.append(f"{name} 的 CSV 分隔符与 {first_name} 不一致")

    # Repeated Handles inside one file are normal variant rows. A Handle found
    # in two different files would cause many store backends to merge products.
    handle_owner: dict[str, str] = {}
    duplicate_handles: set[str] = set()
    if "Handle" in columns:
        for name, loaded in loaded_outputs:
            file_handles = {
                value for value in loaded.frame["Handle"].astype(str).str.strip().tolist() if value
            }
            for handle in file_handles:
                owner = handle_owner.get(handle)
                if owner is not None and owner != name:
                    duplicate_handles.add(handle)
                else:
                    handle_owner[handle] = name
    if duplicate_handles:
        preview = "、".join(sorted(duplicate_handles)[:5])
        issues.append(
            f"不同文件中存在重复 Handle（{preview}"
            + (" 等" if len(duplicate_handles) > 5 else "")
            + "），为避免后台错误合并商品，已停止生成合并包"
        )
    if issues:
        return None, tuple(issues)

    line_ending = next((value for value in first.row_endings if value), "\n")
    merged_rows = [delimiter.join(first.raw_rows[0]) + line_ending]
    expected_data_rows = 0
    for _, loaded in loaded_outputs:
        for raw_row in loaded.raw_rows[1:]:
            merged_rows.append(delimiter.join(raw_row) + line_ending)
            expected_data_rows += 1
    merged = "".join(merged_rows).encode(first.encoding)
    try:
        reloaded = load_csv_bytes(merged)
    except Exception as exc:  # noqa: BLE001
        return None, (f"合并后的产品包无法重新读取：{exc}",)
    if list(reloaded.frame.columns) != columns or len(reloaded.frame) != expected_data_rows:
        return None, ("合并后的产品包字段或行数复核失败，已停止下载。",)
    return merged, ()


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
