from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import pandas as pd

from category_rules import CategoryRule, infer_similar_category
from csv_loader import variant_mask


DISCOUNT_RATES = (0.12, 0.15, 0.18)
DISCOUNT_COVERAGE = 1 / 3


@dataclass(frozen=True)
class PricingResult:
    frame: pd.DataFrame
    product_summary: pd.DataFrame
    unresolved_handles: tuple[str, ...]


def parse_number(value: object) -> float | None:
    text = str(value).strip().replace(",", "")
    for symbol in ("$", "￥", "¥", "£", "€"):
        text = text.replace(symbol, "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _stable_number(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


def _price_points(rule: CategoryRule) -> tuple[float, ...]:
    points: list[float] = []
    for dollar in range(math.floor(rule.minimum), math.floor(rule.maximum) + 1):
        for cents in (0.90, 0.99):
            value = round(dollar + cents, 2)
            if rule.minimum - 0.001 <= value <= rule.maximum + 0.001:
                points.append(value)
    return tuple(sorted(set(points))) or (round(rule.minimum, 2), round(rule.maximum, 2))


def _valid_compare_prices(sale_price: float, rule: CategoryRule) -> tuple[float, ...]:
    return tuple(
        compare
        for compare in _price_points(rule)
        if compare > sale_price and 0.10 <= (compare - sale_price) / compare <= 0.20
    )


def _compare_price(sale_price: float, discount_rate: float, rule: CategoryRule) -> float:
    candidates = _valid_compare_prices(sale_price, rule)
    if not candidates:
        raise ValueError(f"{rule.name} 的区间无法同时满足售价、原价和 10%–20% 折扣规则。")
    target = sale_price / (1 - discount_rate)
    return min(candidates, key=lambda value: abs(value - target))


def _product_text(group: pd.DataFrame) -> str:
    fields = [field for field in ("Title", "category", "tags", "body_html") if field in group]
    return " ".join(
        value
        for field in fields
        for value in group[field].astype(str)
        if value.strip()
    )


def _product_group_keys(frame: pd.DataFrame) -> pd.Series:
    """Use Handle when present; otherwise group continuation rows under each Title row."""
    handles = frame["Handle"].astype(str).str.strip()
    titles = frame.get("Title", pd.Series("", index=frame.index)).astype(str).str.strip()
    title_anchor = pd.Series(
        [str(index) if title else pd.NA for index, title in zip(frame.index, titles)],
        index=frame.index,
        dtype="string",
    ).ffill()
    fallback = "title-row:" + title_anchor.fillna(pd.Series(frame.index.astype(str), index=frame.index))
    return handles.where(handles.ne(""), fallback)


def apply_fixed_pricing(frame: pd.DataFrame) -> PricingResult:
    output = frame.copy(deep=True)
    variants = variant_mask(output)
    if "Handle" not in output:
        raise ValueError("缺少 Handle 字段，无法按商品统一价格。")

    unresolved: list[str] = []
    classified: list[tuple[str, pd.Index, CategoryRule, str]] = []
    group_keys = _product_group_keys(output)
    for group_key, group in output.groupby(group_keys, sort=False, dropna=False):
        original_handles = group["Handle"].astype(str).str.strip()
        handle_text = next((value for value in original_handles if value), "")
        if not handle_text:
            titles = group.get("Title", pd.Series("", index=group.index)).astype(str).str.strip()
            handle_text = next((value for value in titles if value), str(group_key))
        indices = group.index[variants.loc[group.index]]
        if len(indices) == 0:
            continue
        rule, match_method = infer_similar_category(_product_text(group))
        if rule is None:
            unresolved.append(handle_text)
        else:
            classified.append((handle_text, indices, rule, match_method or "直接匹配"))

    by_category: dict[str, list[tuple[str, pd.Index, CategoryRule, str]]] = {}
    for item in classified:
        by_category.setdefault(item[2].name, []).append(item)

    discount_count = math.ceil(len(classified) * DISCOUNT_COVERAGE)
    discounted_handles = {
        handle
        for handle, _, _, _ in sorted(classified, key=lambda item: _stable_number(item[0] + "-discount"))[:discount_count]
    }

    assigned_prices: dict[str, float] = {}
    for items in by_category.values():
        items.sort(key=lambda item: _stable_number(item[0]))
        points = _price_points(items[0][2])
        usable_sales = tuple(point for point in points if _valid_compare_prices(point, items[0][2]))
        if len(usable_sales) < min(4, len(items)):
            raise ValueError(f"{items[0][2].name} 的价格区间不足以生成要求数量的不同售价。")
        offset = _stable_number(items[0][2].name) % len(usable_sales)
        for position, (handle, _, _, _) in enumerate(items):
            assigned_prices[handle] = usable_sales[(offset + position) % len(usable_sales)]

    product_records: list[dict[str, object]] = []
    for handle, indices, rule, match_method in classified:
        sale_price = assigned_prices[handle]
        rate = DISCOUNT_RATES[_stable_number(handle + "-rate") % len(DISCOUNT_RATES)] if handle in discounted_handles else 0.0
        compare_price = _compare_price(sale_price, rate, rule) if rate else 0.0

        output.loc[indices, "price"] = f"{sale_price:.2f}"
        output.loc[indices, "compare_at_price"] = f"{compare_price:.2f}" if compare_price else "0"
        product_records.append(
            {
                "Handle": handle,
                "识别品类": rule.name,
                "匹配方式": match_method,
                "价格区间": f"{rule.minimum:.2f}–{rule.maximum:.2f}",
                "区间下限": rule.minimum,
                "区间上限": rule.maximum,
                "新售价": sale_price,
                "新划线价": compare_price,
                "折扣率": round((1 - sale_price / compare_price) * 100, 1) if compare_price else 0.0,
                "SKU数量": len(indices),
            }
        )

    return PricingResult(output, pd.DataFrame(product_records), tuple(unresolved))


def validate_fixed_pricing(result: PricingResult) -> tuple[str, ...]:
    issues: list[str] = []
    summary = result.product_summary
    if result.unresolved_handles:
        issues.append("存在无法识别品类的商品")
    if summary.empty:
        return tuple(issues or ["没有可定价商品"])
    if not summary["新售价"].gt(0).all():
        issues.append("存在售价不大于 0 的商品")
    if not ((summary["新售价"] >= summary["区间下限"]) & (summary["新售价"] <= summary["区间上限"])).all():
        issues.append("存在售价超出品类区间")
    discounted = summary["新划线价"] > 0
    valid_compare = (
        (summary.loc[discounted, "新划线价"] > summary.loc[discounted, "新售价"])
        & (summary.loc[discounted, "新划线价"] >= summary.loc[discounted, "区间下限"])
        & (summary.loc[discounted, "新划线价"] <= summary.loc[discounted, "区间上限"])
    )
    if not valid_compare.all():
        issues.append("存在非零原价不大于售价或超出品类区间")
    if not summary.loc[discounted, "折扣率"].between(10, 20).all():
        issues.append("存在折扣率不在 10%–20% 的商品")
    if int(discounted.sum()) < math.ceil(len(summary) / 3):
        issues.append("打折商品不足产品包商品数的三分之一")
    for category, group in summary.groupby("识别品类"):
        expected = min(4, len(group))
        if group["新售价"].nunique() < expected:
            issues.append(f"{category} 售价种类不足 {expected} 个")
    return tuple(issues)


def build_change_preview(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    variants = variant_mask(before)
    columns = [column for column in ("Handle", "sku_code", "Option1 Value", "Option2 Value") if column in before]
    preview = before.loc[variants, columns].copy()
    preview["原售价"] = before.loc[variants, "price"].values
    preview["新售价"] = after.loc[variants, "price"].values
    preview["原划线价"] = before.loc[variants, "compare_at_price"].values
    preview["新划线价"] = after.loc[variants, "compare_at_price"].values
    preview["发生变化"] = (
        preview["原售价"].astype(str).ne(preview["新售价"].astype(str))
        | preview["原划线价"].astype(str).ne(preview["新划线价"].astype(str))
    )
    return preview
