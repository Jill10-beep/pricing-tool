from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass

import pandas as pd

from category_rules import CategoryRule, classify_product, has_category_conflict, infer_similar_category, resolve_rule
from csv_loader import variant_mask


DISCOUNT_RATES = (0.12, 0.15, 0.18)
DISCOUNT_COVERAGE = 1 / 3


@dataclass(frozen=True)
class PricingResult:
    frame: pd.DataFrame
    product_summary: pd.DataFrame
    unresolved_handles: tuple[str, ...]
    expected_products: int


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
    # Descriptions often contain styling suggestions such as "pair with boots".
    # They must never decide the product's category.
    fields = [field for field in ("category", "Title", "tags") if field in group]
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


def _resolve_available_rule(value: str, custom_rules: tuple[CategoryRule, ...]) -> CategoryRule | None:
    custom_by_id = {rule.rule_id: rule for rule in custom_rules}
    if value in custom_by_id:
        return custom_by_id[value]
    custom_matches = [rule for rule in custom_rules if rule.name == value]
    if len(custom_matches) == 1:
        return custom_matches[0]
    return resolve_rule(value)


def _classify_custom_rule(text: str, custom_rules: tuple[CategoryRule, ...]) -> CategoryRule | None:
    normalized = " ".join(str(text).lower().replace("_", " ").replace("-", " ").split())
    matches: list[tuple[int, CategoryRule]] = []
    for rule in custom_rules:
        terms = (rule.name, *rule.keywords)
        matched_lengths = []
        for term in terms:
            normalized_term = " ".join(str(term).lower().replace("_", " ").replace("-", " ").split())
            if not normalized_term:
                continue
            if re.search(r"[\u4e00-\u9fff]", normalized_term):
                matched = normalized_term in normalized
            else:
                matched = re.search(
                    rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])",
                    normalized,
                ) is not None
            if matched:
                matched_lengths.append(len(normalized_term))
        if matched_lengths:
            matches.append((max(matched_lengths), rule))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def _category_level_decisions(
    frame: pd.DataFrame,
    overrides: dict[str, str],
    custom_rules: tuple[CategoryRule, ...],
) -> dict[str, tuple[CategoryRule | None, str | None, bool]]:
    """Choose one rule per supplier category so sibling products cannot drift."""
    decisions: dict[str, tuple[CategoryRule | None, str | None, bool]] = {}
    categories = frame.get("category", pd.Series("", index=frame.index)).astype(str).str.strip()
    for source_category in (value for value in categories.unique() if value):
        override_rule = _resolve_available_rule(overrides.get(source_category, ""), custom_rules)
        if override_rule:
            decisions[source_category] = (
                override_rule,
                f"已确认映射：{source_category} → {override_rule.primary} → {override_rule.name}",
                True,
            )
            continue

        direct_rule = _classify_custom_rule(source_category, custom_rules) or classify_product(source_category)
        if direct_rule and not has_category_conflict(source_category, direct_rule):
            decisions[source_category] = (
                direct_rule,
                f"原始分类统一匹配：{direct_rule.primary} → {direct_rule.name}",
                False,
            )
            continue

        category_rows = frame[categories.eq(source_category)]
        titles = category_rows.get("Title", pd.Series("", index=category_rows.index)).astype(str).str.strip()
        unique_titles = tuple(dict.fromkeys(value for value in titles if value))
        title_rules = [
            rule for title in unique_titles
            if (rule := (_classify_custom_rule(title, custom_rules) or classify_product(title))) is not None
        ]
        counts = Counter(rule.rule_id for rule in title_rules)
        if counts and len(title_rules) >= max(2, math.ceil(len(unique_titles) * 0.60)):
            best_id, best_count = counts.most_common(1)[0]
            if best_count / len(title_rules) >= 0.80:
                majority_rule = next(rule for rule in title_rules if rule.rule_id == best_id)
                if not has_category_conflict(source_category, majority_rule):
                    decisions[source_category] = (
                        majority_rule,
                        f"同一原始分类多数一致：{majority_rule.primary} → {majority_rule.name}",
                        False,
                    )
                    continue

        combined_text = " ".join((source_category, *unique_titles[:20]))
        similar_rule, similar_method = infer_similar_category(combined_text)
        if similar_rule and not has_category_conflict(source_category, similar_rule):
            decisions[source_category] = (similar_rule, similar_method, False)
        else:
            decisions[source_category] = (None, None, False)
    return decisions


def _apply_price_range_override(
    rule: CategoryRule,
    range_overrides: dict[str, dict[str, float]],
) -> CategoryRule:
    custom = range_overrides.get(rule.rule_id)
    if not custom:
        return rule
    return CategoryRule(
        rule.primary,
        rule.name,
        float(custom["minimum"]),
        float(custom["maximum"]),
        rule.keywords,
    )


def apply_fixed_pricing(
    frame: pd.DataFrame,
    category_overrides: dict[str, str] | None = None,
    price_range_overrides: dict[str, dict[str, float]] | None = None,
    product_category_overrides: dict[str, str] | None = None,
    custom_category_rules: tuple[CategoryRule, ...] | None = None,
) -> PricingResult:
    output = frame.copy(deep=True)
    variants = variant_mask(output)
    if "Handle" not in output:
        raise ValueError("缺少 Handle 字段，无法按商品统一价格。")

    overrides = category_overrides or {}
    range_overrides = price_range_overrides or {}
    product_overrides = product_category_overrides or {}
    custom_rules = custom_category_rules or ()
    category_decisions = _category_level_decisions(output, overrides, custom_rules)
    unresolved: list[str] = []
    classified: list[tuple[str, pd.Index, CategoryRule, str, str]] = []
    expected_products = 0
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
        expected_products += 1
        source_categories = group.get("category", pd.Series("", index=group.index)).astype(str).str.strip()
        source_category = next((value for value in source_categories if value), "未提供分类")
        titles = group.get("Title", pd.Series("", index=group.index)).astype(str).str.strip()
        title = next((value for value in titles if value), "")
        structured_text = f"{source_category} {title}"
        category_decision = category_decisions.get(source_category)
        product_override_rule = _resolve_available_rule(product_overrides.get(handle_text, ""), custom_rules)
        override_rule = product_override_rule or (
            category_decision[0] if category_decision and category_decision[2] else None
        )
        if product_override_rule:
            rule = product_override_rule
            match_method = f"单个商品人工纠正：{product_override_rule.primary} → {product_override_rule.name}"
        elif category_decision:
            rule, match_method, _ = category_decision
        else:
            # Only products without a supplier category may fall back to their
            # own title. A populated supplier category is always decided once
            # for the whole category by _category_level_decisions above.
            rule = None
            match_method = None
            if rule is None:
                rule = _classify_custom_rule(title, custom_rules) or classify_product(title)
                match_method = f"商品标题匹配：{rule.primary} → {rule.name}" if rule else None
            if rule is None:
                rule, match_method = infer_similar_category(_product_text(group))
        if rule is not None:
            rule = _apply_price_range_override(rule, range_overrides)
        # A saved manual mapping is an explicit user decision and must outrank
        # automatic conflict heuristics. Otherwise a few titles inside the same
        # supplier category can be rejected even after the user confirms it.
        conflict_text = structured_text if category_decision is None else source_category
        if rule is None or (override_rule is None and has_category_conflict(conflict_text, rule)):
            unresolved.append(handle_text)
        else:
            classified.append((handle_text, indices, rule, match_method or "直接匹配", source_category))

    by_category: dict[str, list[tuple[str, pd.Index, CategoryRule, str, str]]] = {}
    for item in classified:
        by_category.setdefault(item[2].rule_id, []).append(item)

    discount_count = math.ceil(len(classified) * DISCOUNT_COVERAGE)
    discounted_handles = {
        handle
        for handle, _, _, _, _ in sorted(classified, key=lambda item: _stable_number(item[0] + "-discount"))[:discount_count]
    }

    assigned_prices: dict[str, float] = {}
    for items in by_category.values():
        items.sort(key=lambda item: _stable_number(item[0]))
        points = _price_points(items[0][2])
        usable_sales = tuple(point for point in points if _valid_compare_prices(point, items[0][2]))
        if len(usable_sales) < min(4, len(items)):
            raise ValueError(f"{items[0][2].name} 的价格区间不足以生成要求数量的不同售价。")
        offset = _stable_number(items[0][2].name) % len(usable_sales)
        for position, (handle, _, _, _, _) in enumerate(items):
            assigned_prices[handle] = usable_sales[(offset + position) % len(usable_sales)]

    product_records: list[dict[str, object]] = []
    for handle, indices, rule, match_method, source_category in classified:
        sale_price = assigned_prices[handle]
        rate = DISCOUNT_RATES[_stable_number(handle + "-rate") % len(DISCOUNT_RATES)] if handle in discounted_handles else 0.0
        compare_price = _compare_price(sale_price, rate, rule) if rate else 0.0

        output.loc[indices, "price"] = f"{sale_price:.2f}"
        output.loc[indices, "compare_at_price"] = f"{compare_price:.2f}" if compare_price else "0"
        product_records.append(
            {
                "Handle": handle,
                "原始分类": source_category,
                "一级品类": rule.primary,
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

    return PricingResult(output, pd.DataFrame(product_records), tuple(unresolved), expected_products)


def validate_fixed_pricing(result: PricingResult) -> tuple[str, ...]:
    issues: list[str] = []
    summary = result.product_summary
    handled_products = len(summary) + len(result.unresolved_handles)
    if handled_products != result.expected_products:
        issues.append(
            f"商品处理不完整：应处理 {result.expected_products} 个，实际仅处理 {handled_products} 个"
        )
    if len(summary) != result.expected_products and not result.unresolved_handles:
        issues.append(
            f"定价结果不完整：应生成 {result.expected_products} 个商品结果，实际仅生成 {len(summary)} 个"
        )
    # Unresolved products are intentionally kept unchanged and do not block a
    # partial export. They are counted above so a genuinely lost product still
    # fails completeness validation.
    if summary.empty:
        return tuple(issues)
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
