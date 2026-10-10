from __future__ import annotations

import json
from io import BytesIO
import zipfile

import streamlit as st

from category_rules import CATEGORY_RULES, PRIMARY_CATEGORIES, infer_primary_category, rank_similar_categories, resolve_rule, rules_for_primary
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
uploaded_files = st.file_uploader(
    "上传产品 CSV",
    type=["csv"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if not uploaded_files:
    st.markdown(
        """
        <div class="empty-grid">
          <div class="empty-card"><strong>只修改价格字段</strong><span>保留原始列结构、顺序、引号、编码、图片和商品信息。</span></div>
          <div class="empty-card"><strong>固定规则自动校验</strong><span>售价、原价、折扣比例、价格多样性和变体一致性逐项检查。</span></div>
          <div class="empty-card"><strong>两级品类识别</strong><span>先识别一级品类，再在该一级品类内匹配具体价格；表外商品等待你选择。</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("查看已内置的固定价格区间"):
        st.dataframe(
            [{"一级品类": rule.primary, "具体品类": rule.name, "最低售价": rule.minimum, "最高售价": rule.maximum} for rule in CATEGORY_RULES],
            use_container_width=True,
            hide_index=True,
        )
    st.stop()

if "learned_category_mappings" not in st.session_state:
    st.session_state.learned_category_mappings = {}

with st.expander("品类映射记忆（可选）"):
    mapping_file = st.file_uploader("导入以前保存的品类映射", type=["json"], key="mapping_json")
    if mapping_file is not None:
        try:
            imported = json.loads(mapping_file.getvalue().decode("utf-8"))
            valid = {str(key): str(value) for key, value in imported.items() if resolve_rule(str(value)) is not None}
            st.session_state.learned_category_mappings.update(valid)
            st.success(f"已导入 {len(valid)} 条品类映射。")
        except Exception:
            st.error("映射文件无法读取。")

st.markdown('<div class="section-kicker">Batch Queue</div><div class="section-title">处理队列</div>', unsafe_allow_html=True)
queue_cols = st.columns(3)
queue_cols[0].metric("已上传文件", len(uploaded_files))

completed_outputs: list[tuple[str, bytes]] = []
needs_attention = 0

for file_index, uploaded in enumerate(uploaded_files):
    with st.expander(f"{file_index + 1:02d}  ·  {uploaded.name}", expanded=True):
        try:
            loaded = load_csv_bytes(uploaded.getvalue())
            source = loaded.frame
            before_summary = validate_frame(source)
            if before_summary.missing_columns:
                st.error("缺少必要字段：" + ", ".join(before_summary.missing_columns))
                needs_attention += 1
                continue

            metrics = st.columns(5)
            metrics[0].metric("数据行", f"{before_summary.rows:,}")
            metrics[1].metric("商品", f"{before_summary.products:,}")
            metrics[2].metric("SKU / 变体", f"{before_summary.variants:,}")
            metrics[3].metric("附加图片行", f"{before_summary.image_only_rows:,}")
            metrics[4].metric("字段", f"{len(source.columns):,}")

            pricing_result = apply_fixed_pricing(source, st.session_state.learned_category_mappings)

            if pricing_result.unresolved_handles:
                unresolved_rows = source[source["Handle"].astype(str).isin(pricing_result.unresolved_handles)]
                categories = sorted(value for value in unresolved_rows["category"].astype(str).str.strip().unique() if value)
                st.warning("价格表中没有找到明确对应项。请选择一级品类，再选择要参考的具体品类；确认前不会修改和导出。")
                selected_mappings = {}
                for category in categories:
                    category_rows = unresolved_rows[unresolved_rows["category"].astype(str).str.strip() == category]
                    sample_titles = " ".join(category_rows["Title"].astype(str).drop_duplicates().head(12)) if "Title" in category_rows else ""
                    candidates = rank_similar_categories(f"{category} {sample_titles}", 3)
                    if candidates:
                        st.caption("智能候选（只供参考，确认后才定价）")
                        st.dataframe(
                            [{
                                "一级品类": rule.primary,
                                "具体品类": rule.name,
                                "价格区间": f"${rule.minimum:.2f}–${rule.maximum:.2f}",
                                "相似度": f"{score * 100:.1f}%",
                            } for rule, score in candidates],
                            use_container_width=True,
                            hide_index=True,
                        )
                    suggested_primary = candidates[0][0].primary if candidates else infer_primary_category(category)
                    primary_options = ["请选择"] + list(PRIMARY_CATEGORIES)
                    primary_index = primary_options.index(suggested_primary) if suggested_primary in primary_options else 0
                    primary = st.selectbox(
                        f"{category}：先选择一级品类",
                        primary_options,
                        index=primary_index,
                        key=f"primary_{file_index}_{category}",
                    )
                    if primary != "请选择":
                        candidate_rules = rules_for_primary(primary)
                        labels = [f"{rule.name}（${rule.minimum:.2f}–${rule.maximum:.2f}）" for rule in candidate_rules]
                        selection = st.selectbox(
                            f"{category}：参考哪个具体品类？",
                            ["请选择"] + labels,
                            key=f"rule_{file_index}_{category}",
                        )
                        if selection != "请选择":
                            selected_mappings[category] = candidate_rules[labels.index(selection)].rule_id
                if categories and st.button(
                    "保存映射并重新处理",
                    key=f"save_map_{file_index}",
                    disabled=len(selected_mappings) != len(categories),
                ):
                    st.session_state.learned_category_mappings.update(selected_mappings)
                    st.rerun()

            if "匹配方式" in pricing_result.product_summary.columns:
                similar = pricing_result.product_summary[
                    pricing_result.product_summary["匹配方式"].astype(str).str.contains("语义匹配", regex=False)
                ]
            else:
                similar = pricing_result.product_summary.copy()

            similar_confirmed = True
            result_tab, changes_tab = st.tabs(["定价结果", "SKU 变更"])
            with result_tab:
                if not pricing_result.product_summary.empty:
                    visible = pricing_result.product_summary.drop(columns=["区间下限", "区间上限"])
                    st.dataframe(visible, use_container_width=True, hide_index=True, height=330)
                if not similar.empty:
                    st.warning("请确认相似品类映射。")
                    st.dataframe(similar[["Handle", "匹配方式", "一级品类", "识别品类", "价格区间"]], use_container_width=True, hide_index=True, height=210)
                    similar_confirmed = st.checkbox("确认此文件的相似品类关系", key=f"confirm_{file_index}")
                    if similar_confirmed and "原始分类" in similar:
                        mapped_ids = [f"{primary}::{name}" for primary, name in zip(similar["一级品类"], similar["识别品类"])]
                        st.session_state.learned_category_mappings.update(dict(zip(similar["原始分类"], mapped_ids)))

            with changes_tab:
                preview = build_change_preview(source, pricing_result.frame)
                preview.insert(1, "商品名称", display_titles(source).loc[preview.index])
                changed_only = st.toggle("只看发生变化的记录", value=True, key=f"changed_{file_index}")
                shown = preview[preview["发生变化"]] if changed_only else preview
                st.dataframe(shown, use_container_width=True, hide_index=True, height=380)

            after_summary = validate_frame(pricing_result.frame)
            rule_issues = validate_fixed_pricing(pricing_result)
            blocked = bool(
                pricing_result.unresolved_handles
                or rule_issues
                or not similar_confirmed
                or after_summary.invalid_prices
                or after_summary.zero_prices
                or after_summary.duplicate_skus
            )
            if blocked:
                needs_attention += 1
                if rule_issues:
                    st.error("；".join(rule_issues))
                elif not similar_confirmed:
                    st.info("确认相似品类后即可下载此文件。")
            else:
                output_name = uploaded.name.rsplit(".", 1)[0] + "-正确价格.csv"
                output_bytes = export_csv(pricing_result.frame, loaded)
                completed_outputs.append((output_name, output_bytes))
                st.success("此产品包已完成并通过校验。")
                st.download_button(
                    f"下载 {output_name}",
                    data=output_bytes,
                    file_name=output_name,
                    mime="text/csv",
                    key=f"download_{file_index}",
                    use_container_width=True,
                )
        except Exception as exc:
            needs_attention += 1
            st.error(f"处理失败：{exc}")

queue_cols[1].metric("已完成", len(completed_outputs))
queue_cols[2].metric("待处理", needs_attention)

st.markdown('<div class="section-kicker">Batch Export</div><div class="section-title">批量导出</div>', unsafe_allow_html=True)
if completed_outputs:
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in completed_outputs:
            archive.writestr(name, data)
    st.download_button(
        f"下载全部已完成产品包（{len(completed_outputs)} 个）",
        data=zip_buffer.getvalue(),
        file_name="正确价格产品包.zip",
        mime="application/zip",
        use_container_width=True,
    )
else:
    st.info("完成品类确认和校验后，可在这里一次下载全部结果。")

if st.session_state.learned_category_mappings:
    st.download_button(
        "保存品类映射文件",
        data=json.dumps(st.session_state.learned_category_mappings, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="category-mappings.json",
        mime="application/json",
    )
