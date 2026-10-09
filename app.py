from __future__ import annotations

import streamlit as st

from category_rules import CATEGORY_RULES
from csv_loader import display_titles, load_csv_bytes
from exporter import export_csv
from pricing import apply_fixed_pricing, build_change_preview, validate_fixed_pricing
from validator import validate_frame


st.set_page_config(page_title="产品自动定价工具", page_icon="💰", layout="wide")
st.title("产品自动定价工具")
st.caption("上传产品包后，程序按固定品类价格和折扣规则自动处理。源文件不会被覆盖。")

with st.expander("查看已内置的固定价格区间"):
    st.dataframe(
        [{"品类": rule.name, "最低售价": rule.minimum, "最高售价": rule.maximum} for rule in CATEGORY_RULES],
        use_container_width=True,
        hide_index=True,
    )

uploaded = st.file_uploader("上传产品 CSV", type=["csv"])
if uploaded is None:
    st.info("请先上传 CSV 文件。")
    st.stop()

try:
    loaded = load_csv_bytes(uploaded.getvalue())
    source = loaded.frame
except Exception as exc:
    st.error(f"文件读取失败：{exc}")
    st.stop()

before_summary = validate_frame(source)
if before_summary.missing_columns:
    st.error("缺少必要字段：" + ", ".join(before_summary.missing_columns))
    st.stop()

st.subheader("1. 文件结构")
metrics = st.columns(5)
metrics[0].metric("数据行", before_summary.rows)
metrics[1].metric("商品", before_summary.products)
metrics[2].metric("SKU/变体", before_summary.variants)
metrics[3].metric("附加图片行", before_summary.image_only_rows)
metrics[4].metric("字段", len(source.columns))

pricing_result = apply_fixed_pricing(source)
st.subheader("2. 品类识别与自动定价")
if pricing_result.unresolved_handles:
    st.error(
        "以下商品无法匹配价格规则，因此已停止导出。请先补充对应品类的价格区间：\n\n"
        + "\n".join(f"- {handle}" for handle in pricing_result.unresolved_handles)
    )
else:
    st.success("所有商品均已匹配固定价格规则。")

if not pricing_result.product_summary.empty:
    visible_summary = pricing_result.product_summary.drop(columns=["区间下限", "区间上限"])
    st.dataframe(visible_summary, use_container_width=True, hide_index=True)

if "匹配方式" in pricing_result.product_summary.columns:
    similar_matches = pricing_result.product_summary[
        pricing_result.product_summary["匹配方式"].astype(str).str.startswith("相似品类")
    ]
else:
    similar_matches = pricing_result.product_summary.copy()
similar_confirmed = True
if not similar_matches.empty:
    st.warning("检测到价格表以外的商品。请确认下面的相似品类映射后再导出。")
    st.dataframe(
        similar_matches[["Handle", "匹配方式", "识别品类", "价格区间"]],
        use_container_width=True,
        hide_index=True,
    )
    similar_confirmed = st.checkbox("我确认以上相似品类定价关系", value=False)

preview = build_change_preview(source, pricing_result.frame)
preview.insert(1, "商品名称", display_titles(source).loc[preview.index])
st.subheader("3. SKU 修改预览")
only_changed = st.checkbox("只看发生变化的 SKU", value=True)
shown = preview[preview["发生变化"]] if only_changed else preview
st.dataframe(shown, use_container_width=True, hide_index=True)

after_summary = validate_frame(pricing_result.frame)
blocking_errors = (
    pricing_result.unresolved_handles
    or validate_fixed_pricing(pricing_result)
    or not similar_confirmed
    or after_summary.invalid_prices
    or after_summary.zero_prices
    or after_summary.duplicate_skus
)
if blocking_errors:
    st.warning("存在未解决问题，下载按钮已停用，避免生成错误产品包。")
else:
    st.success("最终校验通过：品类、价格、SKU、图片行和字段顺序均符合要求。")
    output_name = uploaded.name.rsplit(".", 1)[0] + "-正确价格.csv"
    st.download_button(
        "下载正确价格的产品包",
        data=export_csv(pricing_result.frame, loaded),
        file_name=output_name,
        mime="text/csv",
        type="primary",
    )
