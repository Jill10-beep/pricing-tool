from __future__ import annotations

import csv
from dataclasses import dataclass
from io import BytesIO, StringIO

import pandas as pd


@dataclass(frozen=True)
class LoadedCsv:
    frame: pd.DataFrame
    encoding: str
    delimiter: str
    raw_rows: tuple[tuple[str, ...], ...]
    row_endings: tuple[str, ...]


SUPPORTED_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16")


def _split_raw_csv(text: str, delimiter: str) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    endings: list[str] = []
    fields: list[str] = []
    start = 0
    index = 0
    in_quotes = False
    while index < len(text):
        char = text[index]
        if char == '"':
            if in_quotes and index + 1 < len(text) and text[index + 1] == '"':
                index += 2
                continue
            in_quotes = not in_quotes
        elif not in_quotes and char == delimiter:
            fields.append(text[start:index])
            start = index + 1
        elif not in_quotes and char in "\r\n":
            fields.append(text[start:index])
            rows.append(tuple(fields))
            fields = []
            if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                endings.append("\r\n")
                index += 1
            else:
                endings.append(char)
            start = index + 1
        index += 1
    if start < len(text) or fields:
        fields.append(text[start:])
        rows.append(tuple(fields))
        endings.append("")
    return tuple(rows), tuple(endings)


def load_csv_bytes(data: bytes) -> LoadedCsv:
    text = None
    encoding = None
    for candidate in SUPPORTED_ENCODINGS:
        try:
            text = data.decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    if text is None or encoding is None:
        raise ValueError("无法识别文件编码，请另存为 UTF-8 CSV 后重试。")

    try:
        delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",\t;|").delimiter
    except csv.Error:
        delimiter = ","

    frame = pd.read_csv(
        StringIO(text),
        sep=delimiter,
        dtype=str,
        keep_default_na=False,
    )
    frame.columns = [str(column).strip() for column in frame.columns]
    raw_rows, row_endings = _split_raw_csv(text, delimiter)
    if len(raw_rows) != len(frame) + 1:
        raise ValueError("CSV 原始行结构无法安全解析，已停止处理以保护原文件格式。")
    return LoadedCsv(
        frame=frame,
        encoding=encoding,
        delimiter=delimiter,
        raw_rows=raw_rows,
        row_endings=row_endings,
    )


def replace_price_columns(loaded: LoadedCsv, frame: pd.DataFrame) -> bytes:
    if len(frame) + 1 != len(loaded.raw_rows):
        raise ValueError("导出行数与原文件不一致。")
    header = list(frame.columns)
    price_indexes = [header.index(name) for name in ("price", "compare_at_price")]
    output_rows: list[str] = []
    for row_number, raw_row in enumerate(loaded.raw_rows):
        cells = list(raw_row)
        if len(cells) != len(header):
            raise ValueError(f"第 {row_number + 1} 行字段数量异常，已停止导出。")
        if row_number > 0:
            for column_index in price_indexes:
                value = str(frame.iloc[row_number - 1, column_index])
                original = cells[column_index]
                stripped = original.strip()
                if len(stripped) >= 2 and stripped.startswith('"') and stripped.endswith('"'):
                    leading = original[: len(original) - len(original.lstrip())]
                    trailing = original[len(original.rstrip()) :]
                    cells[column_index] = leading + '"' + value.replace('"', '""') + '"' + trailing
                else:
                    cells[column_index] = value
        output_rows.append(loaded.delimiter.join(cells) + loaded.row_endings[row_number])
    text = "".join(output_rows)
    return text.encode(loaded.encoding)


def to_csv_bytes(frame: pd.DataFrame, delimiter: str = ",") -> bytes:
    buffer = BytesIO()
    text = frame.to_csv(index=False, sep=delimiter, lineterminator="\n")
    buffer.write(text.encode("utf-8-sig"))
    return buffer.getvalue()


def variant_mask(frame: pd.DataFrame) -> pd.Series:
    if "sku_code" not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame["sku_code"].astype(str).str.strip().ne("")


def product_mask(frame: pd.DataFrame) -> pd.Series:
    if "Title" not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame["Title"].astype(str).str.strip().ne("")


def display_titles(frame: pd.DataFrame) -> pd.Series:
    """Forward-fill titles for display only; never write them back to exports."""
    if "Title" not in frame.columns:
        return pd.Series("", index=frame.index)
    titles = frame["Title"].replace("", pd.NA)
    if "Handle" in frame.columns:
        return titles.groupby(frame["Handle"], sort=False).ffill().fillna("")
    return titles.ffill().fillna("")
