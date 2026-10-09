from __future__ import annotations

import streamlit as st

from category_rules import CATEGORY_RULES
from csv_loader import display_titles, load_csv_bytes
from exporter import export_csv
from pricing import apply_fixed_pricing, build_change_preview, validate_fixed_pricing
from validator import validate_frame


st.set_page_config(page_title="产品自动定价工具", page_icon="◆", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;600;700&display=swap');
    :root { --ink:#152238; --muted:#64748B; --line:#E7EAF0; --gold:#B58A4B; --paper:#F7F8FA; }
    .stApp { background: #F7F8FA; color: var(--ink); }
    .block-container { max-width: 1480px; padding-top: 2.2rem; padding-bottom: 5rem; }
    html, body, [class*="css"] { font-family: "DM Sans", "Noto Sans SC", sans-serif; }
    #MainMenu, footer, header { visibility: hidden; }

    .hero {
        position: relative; overflow: hidden; padding: 42px 46px; border-radius: 22px;
        background: linear-gradient(125deg, #101B2D 0%, #1A2941 68%, #263B5B 100%);
        box-shadow: 0 18px 55px rgba(15, 29, 50, .16); margin-bottom: 22px;
    }
    .hero:after { content:""; position:absolute; width:320px; height:320px; right:-90px; top:-160px;
        border:1px solid rgba(201,166,109,.35); border-radius:50%; box-shadow:0 0 0 55px rgba(201,166,109,.06); }
    .eyebrow { color:#D8B77E; font-size:12px; font-weight:700; letter-spacing:.18em; text-transform:uppercase; }
    .hero h1 { color:#FFF; font-size:38px; line-height:1.15; margin:10px 0 12px; letter-spacing:-.02em; }
    .hero p { color:#BFC9D8; max-width:720px; margin:0; font-size:15px; line-height:1.8; }
    .stepbar { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:16px 0 26px; }
    .step { background:#FFF; border:1px solid var(--line); border-radius:12px; padding:13px 16px; color:#697386; font-size:13px; }
    .step b { color:var(--gold); margin-right:8px; }
    .section-kicker { color:var(--gold); font-weight:700; font-size:12px; letter-spacing:.12em; text-transform:uppercase; margin-top:8px; }
    .section-title { color:var(--ink); font-size:23px; font-weight:700; margin:2px 0 14px; }
    .empty-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-top:18px; }
    .empty-card { background:#FFF; border:1px solid var(--line); padding:22px; border-radius:15px; }
    .empty-card strong { display:block; color:var(--ink); margin-bottom:7px; }
    .empty-card span { color:var(--muted); font-size:13px; line-height:1.6; }
    .download-panel { background:linear-gradient(120deg,#F1E8D9,#FAF7F1); border:1px solid #E4D2B5; border-radius:16px; padding:22px 24px; margin-top:18px; }
    .download-panel h3 { color:#4B3820; margin:0 0 5px; font-size:20px; }
    .download-panel p { color:#806A4C; margin:0; font-size:13px; }

    div[data-testid="stFileUploader"] { background:#FFF; border:1px solid var(--line); border-radius:16px; padding:13px 18px 5px; }
    div[data-testid="stFileUploaderDropzone"] { border:1px dashed #BAC3D1; background:#FAFBFC; border-radius:12px; }
    div[data-testid="stMetric"] { background:#FFF; border:1px solid var(--line); border-radius:14px; padding:17px 18px; box-shadow:0 5px 16px rgba(23,34,56,.035); }
    div[data-testid="stMetricLabel"] { color:var(--muted); }
    div[data-testid="stMetricValue"] { color:var(--ink); font-size:27px; }
    div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:13px; overflow:hidden; background:#FFF; }
    div[data-testid="stAlert"] { border-radius:12px; border-width:1px; }
    div[data-testid="stExpander"] { background:#FFF; border:1px solid var(--line); border-radius:13px; }
    div[data-testid="stTabs"] button { font-weight:600; }
    .stButton>button, .stDownloadButton>button { border-radius:10px; min-height:46px; font-weight:700; }
    .stDownloadButton>button { background:#17253B; color:#FFF; border:1px solid #17253B; }
    .stDownloadButton>button:hover { background:#223653; color:#FFF; border-color:#223653; }
    @media(max-width:800px){ .hero{padding:30px 25px}.hero h1{font-size:30px}.stepbar,.empty-grid{grid-template-columns:1fr 1fr} }
    </style>
    <div class="hero">
      <div class="eyebrow">Pricing Operations Workspace</div>
      <h1>产品自动定价工具</h1>
      <p>上传产品包，系统自动识别商品结构与相似品类，执行固定价格及折扣规则，并生成可直接使用的新产品包。</p>
    </div>
    <div class="stepbar">
      <div class="step"><b>01</b>上传产品包</div>
      <div class="step"><b>02</b>识别品类</div>
      <div class="step"><b>03</b>检查价格</div>
      <div class="step"><b>04</b>下载结果</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="section-kicker">Product Import</div><div class="section-title">上传产品包</div>', unsafe_allow_html=True)
uploaded = st.file_uploader("上传产品 CSV", type=["csv"], label_visibility="collapsed")

if uploaded is None:
    st.markdown(
        """
        <div class="empty-grid">
          <div class="empty-card"><strong>只修改价格字段</strong><span>保留原始列结构、顺序、引号、编码、图片和商品信息。</span></div>
          <div class="empty-card"><strong>固定规则自动校验</strong><span>售价、原价、折扣比例、价格多样性和变体一致性逐项检查。</span></div>
          <div class="empty-card"><strong>相似品类识别</strong><span>价格表外商品将匹配相近的定价基准，并在下载前等待确认。</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("查看已内置的固定价格区间"):
        st.dataframe(
            [{"品类": rule.name, "最低售价": rule.minimum, "最高售价": rule.maximum} for rule in CATEGORY_RULES],
            use_container_width=True,
            hide_index=True,
        )
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

st.markdown('<div class="section-kicker">File Overview</div><div class="section-title">文件概览</div>', unsafe_allow_html=True)
metrics = st.columns(5)
metrics[0].metric("数据行", f"{before_summary.rows:,}")
metrics[1].metric("商品", f"{before_summary.products:,}")
metrics[2].metric("SKU / 变体", f"{before_summary.variants:,}")
metrics[3].metric("附加图片行", f"{before_summary.image_only_rows:,}")
metrics[4].metric("字段", f"{len(source.columns):,}")

try:
    pricing_result = apply_fixed_pricing(source)
except Exception as exc:
    st.error(f"自动定价失败：{exc}")
    st.stop()

preview = build_change_preview(source, pricing_result.frame)
preview.insert(1, "商品名称", display_titles(source).loc[preview.index])

if "匹配方式" in pricing_result.product_summary.columns:
    similar_matches = pricing_result.product_summary[
        pricing_result.product_summary["匹配方式"].astype(str).str.startswith("相似品类")
    ]
else:
    similar_matches = pricing_result.product_summary.copy()

similar_confirmed = True
result_tab, changes_tab, rules_tab = st.tabs(["定价结果", "SKU 变更", "价格规则"])

with result_tab:
    if pricing_result.unresolved_handles:
        st.error(
            "以下商品无法匹配价格规则，已停止导出：\n\n"
            + "\n".join(f"- {handle}" for handle in pricing_result.unresolved_handles)
        )
    else:
        st.success("所有商品均已完成品类识别与价格计算。")

    if not pricing_result.product_summary.empty:
        visible_summary = pricing_result.product_summary.drop(columns=["区间下限", "区间上限"])
        st.dataframe(visible_summary, use_container_width=True, hide_index=True, height=420)

    if not similar_matches.empty:
        st.warning("检测到价格表外商品。请核对相似品类映射。")
        st.dataframe(
            similar_matches[["Handle", "匹配方式", "识别品类", "价格区间"]],
            use_container_width=True,
            hide_index=True,
            height=240,
        )
        similar_confirmed = st.checkbox("我确认以上相似品类定价关系", value=False)

with changes_tab:
    only_changed = st.toggle("只看发生变化的 SKU", value=True)
    shown = preview[preview["发生变化"]] if only_changed else preview
    st.caption(f"当前显示 {len(shown):,} 条，共 {len(preview):,} 条 SKU 记录")
    st.dataframe(shown, use_container_width=True, hide_index=True, height=540)

with rules_tab:
    st.dataframe(
        [{"品类": rule.name, "最低售价": rule.minimum, "最高售价": rule.maximum} for rule in CATEGORY_RULES],
        use_container_width=True,
        hide_index=True,
        height=520,
    )

after_summary = validate_frame(pricing_result.frame)
rule_issues = validate_fixed_pricing(pricing_result)
blocking_errors = (
    pricing_result.unresolved_handles
    or rule_issues
    or not similar_confirmed
    or after_summary.invalid_prices
    or after_summary.zero_prices
    or after_summary.duplicate_skus
)

st.markdown('<div class="section-kicker">Final Check</div><div class="section-title">最终校验与导出</div>', unsafe_allow_html=True)
if blocking_errors:
    if rule_issues:
        st.error("；".join(rule_issues))
    elif not similar_confirmed:
        st.warning("请先在“定价结果”中确认相似品类关系，随后即可下载。")
    else:
        st.warning("存在未解决问题，下载暂不可用。")
else:
    st.markdown(
        """
        <div class="download-panel">
          <h3>文件已准备完成</h3>
          <p>价格规则校验通过。商品结构、SKU、图片和原始 CSV 格式均已保留。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    output_name = uploaded.name.rsplit(".", 1)[0] + "-正确价格.csv"
    st.download_button(
        "下载正确价格的产品包",
        data=export_csv(pricing_result.frame, loaded),
        file_name=output_name,
        mime="text/csv",
        use_container_width=True,
    )
