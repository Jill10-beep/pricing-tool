from __future__ import annotations

import hashlib
import json
from io import BytesIO
import time
import uuid
import zipfile

import pandas as pd
import streamlit as st

from category_rules import CategoryRule, CATEGORY_RULES, PRIMARY_CATEGORIES, infer_primary_category, rank_similar_categories, resolve_rule, rules_for_primary
from csv_loader import display_titles, load_csv_bytes
from exporter import export_csv
from format_adapter import SHOPIFY, SUPPLIER, output_suffix, prepare_frame
from pricing import apply_fixed_pricing, build_change_preview, validate_fixed_pricing
from validator import validate_frame


st.set_page_config(page_title="JILL10 PRICING", page_icon="➕", layout="wide")

WORKSPACE_TTL_SECONDS = 6 * 60 * 60
MAX_ACTIVE_WORKSPACES = 50


@st.cache_resource
def _workspace_store() -> dict[str, dict[str, object]]:
    """Temporary server storage, isolated by an unguessable workspace token."""
    return {}


def _valid_workspace_id(value: object) -> bool:
    text = str(value or "")
    return len(text) == 32 and all(character in "0123456789abcdef" for character in text)


def _prune_workspaces(store: dict[str, dict[str, object]]) -> None:
    now = time.time()
    expired = [
        key for key, value in store.items()
        if now - float(value.get("updated", 0)) > WORKSPACE_TTL_SECONDS
    ]
    for key in expired:
        store.pop(key, None)
    while len(store) > MAX_ACTIVE_WORKSPACES:
        oldest = min(store, key=lambda key: float(store[key].get("updated", 0)))
        store.pop(oldest, None)


def _upload_name(uploaded: object) -> str:
    return uploaded["name"] if isinstance(uploaded, dict) else uploaded.name


def _upload_bytes(uploaded: object) -> bytes:
    return uploaded["data"] if isinstance(uploaded, dict) else uploaded.getvalue()

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;600;700&display=swap');
    :root { --ink:#15151A; --muted:#6E6B78; --line:#DED9D0; --violet:#795CFF; --lime:#C9FF45; --coral:#FF6B55; --cyan:#47DCE0; --paper:#F6F3EC; --surface:#FFFFFF; }
    .stApp {
        background:
          radial-gradient(circle at 92% 4%, rgba(121,92,255,.13), transparent 23rem),
          radial-gradient(circle at 10% 95%, rgba(71,220,224,.10), transparent 28rem),
          var(--paper);
        color: var(--ink);
    }
    .block-container { max-width: 1480px; padding-top: 1.2rem; padding-bottom: 5rem; }
    html, body, [class*="css"] { font-family: "DM Sans", "Noto Sans SC", sans-serif; }
    #MainMenu, footer, header { visibility: hidden; }

    .hero {
        position: relative; overflow: hidden; padding: 38px 42px; border-radius: 24px;
        background: #15151A; box-shadow: 0 22px 65px rgba(21,21,26,.18); margin-bottom: 18px;
    }
    .hero:before { content:""; position:absolute; width:270px; height:270px; right:8%; top:-170px; background:var(--violet); border-radius:50%; filter:blur(3px); opacity:.65; }
    .hero:after { content:""; position:absolute; width:180px; height:180px; right:-45px; bottom:-105px; background:var(--lime); border-radius:48% 52% 58% 42%; transform:rotate(24deg); }
    .brandline { position:relative; z-index:1; display:flex; align-items:center; gap:10px; color:#FFF; font-weight:700; font-size:13px; letter-spacing:.08em; }
    .brandmark { display:inline-grid; place-items:center; width:34px; height:34px; border-radius:11px; background:var(--lime); color:#15151A; font-weight:700; transform:rotate(-7deg); letter-spacing:-.05em; }
    .eyebrow { position:relative; z-index:1; color:var(--cyan); font-size:11px; font-weight:700; letter-spacing:.18em; text-transform:uppercase; margin-top:30px; }
    .hero h1 { position:relative; z-index:1; color:#FFF; font-size:39px; line-height:1.08; margin:8px 0 11px; letter-spacing:-.045em; }
    .hero p { position:relative; z-index:1; color:#B9B7C4; max-width:760px; margin:0; font-size:15px; line-height:1.75; }
    .stepbar { display:grid; grid-template-columns:repeat(4,1fr); gap:11px; margin:16px 0 27px; }
    .step { position:relative; overflow:hidden; background:rgba(255,255,255,.82); border:1px solid var(--line); border-radius:16px; padding:17px 18px; color:var(--muted); font-size:12px; transition:transform .2s ease,box-shadow .2s ease; }
    .step:hover { transform:translateY(-3px); box-shadow:0 14px 34px rgba(21,21,26,.08); }
    .step strong { display:block; color:var(--ink); font-size:15px; margin:8px 0 3px; }
    .step b { display:inline-grid; place-items:center; width:25px; height:25px; border-radius:8px; background:var(--step-color); color:#15151A; }
    .step:nth-child(1){--step-color:var(--cyan)} .step:nth-child(2){--step-color:#BBAEFF} .step:nth-child(3){--step-color:#FF9889} .step:nth-child(4){--step-color:var(--lime)}
    .section-kicker { color:var(--violet); font-weight:700; font-size:11px; letter-spacing:.15em; text-transform:uppercase; margin-top:8px; }
    .section-title { color:var(--ink); font-size:23px; font-weight:700; margin:2px 0 14px; }
    .empty-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-top:18px; }
    .empty-card { background:rgba(255,255,255,.82); border:1px solid var(--line); padding:22px; border-radius:17px; transition:.2s; }
    .empty-card:hover { transform:translateY(-3px); box-shadow:0 14px 34px rgba(21,21,26,.07); }
    .empty-card strong { display:block; color:var(--ink); margin-bottom:7px; }
    .empty-card span { color:var(--muted); font-size:13px; line-height:1.6; }
    .download-panel { background:linear-gradient(120deg,rgba(201,255,69,.34),rgba(255,255,255,.88)); border:1px solid #B6D85D; border-radius:18px; padding:22px 24px; margin-top:18px; }
    .download-panel h3 { color:var(--ink); margin:0 0 5px; font-size:20px; }
    .download-panel p { color:var(--muted); margin:0; font-size:13px; }
    .page-head { display:flex; align-items:end; justify-content:space-between; gap:18px; margin:8px 0 18px; }
    .page-head h2 { margin:3px 0 0; color:var(--ink); font-size:26px; }
    .page-head p { margin:0; color:var(--muted); font-size:14px; }
    .format-note { background:rgba(255,255,255,.82); border:1px solid var(--line); border-left:4px solid var(--cyan); border-radius:14px; padding:16px 18px; margin:8px 0 14px; color:var(--muted); }
    .status-strip { background:rgba(201,255,69,.20); border:1px solid #B9D96B; border-radius:14px; padding:14px 17px; color:#34500A; font-weight:600; margin:12px 0; }

    div[data-testid="stFileUploader"] { background:rgba(255,255,255,.88); border:1px solid var(--line); border-radius:18px; padding:13px 18px 5px; }
    div[data-testid="stFileUploaderDropzone"] { border:1px dashed var(--violet); background:rgba(121,92,255,.035); border-radius:14px; }
    div[data-testid="stMetric"] { background:rgba(255,255,255,.85); border:1px solid var(--line); border-radius:16px; padding:17px 18px; box-shadow:0 8px 22px rgba(21,21,26,.04); }
    div[data-testid="stMetricLabel"] { color:var(--muted); }
    div[data-testid="stMetricValue"] { color:var(--ink); font-size:27px; }
    div[data-testid="stProgress"] > div > div > div { background:linear-gradient(90deg,var(--violet),var(--cyan),var(--lime)); }
    div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:15px; overflow:hidden; background:#FFF; }
    div[data-testid="stAlert"] { border-radius:12px; border-width:1px; }
    div[data-testid="stExpander"] { background:rgba(255,255,255,.82); border:1px solid var(--line); border-radius:15px; }
    div[data-testid="stTabs"] button { font-weight:600; }
    section[data-testid="stSidebar"] { background:#15151A; border-right:0; }
    section[data-testid="stSidebar"] * { color:#F7F5FF; }
    section[data-testid="stSidebar"] div[role="radiogroup"] label { background:rgba(255,255,255,.055); border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:11px 12px; margin-bottom:7px; transition:.2s; }
    section[data-testid="stSidebar"] div[role="radiogroup"] label:hover { background:rgba(201,255,69,.12); transform:translateX(3px); }
    section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) { background:var(--lime); border-color:var(--lime); }
    section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) * { color:#15151A; }
    div[data-testid="stRadio"] > div[role="radiogroup"] { gap:12px; }
    main div[data-testid="stRadio"]:has(input[value="定价处理中心"]) { margin:-4px 0 25px; }
    main div[data-testid="stRadio"]:has(input[value="定价处理中心"]) > div[role="radiogroup"] { background:rgba(255,255,255,.72); border:1px solid var(--line); border-radius:16px; padding:5px; gap:5px; width:fit-content; box-shadow:0 8px 22px rgba(21,21,26,.035); }
    main div[data-testid="stRadio"]:has(input[value="定价处理中心"]) label { min-width:190px; justify-content:center; border:0; border-radius:11px; padding:11px 18px; box-shadow:none; background:transparent; }
    main div[data-testid="stRadio"]:has(input[value="定价处理中心"]) label:has(input:checked) { background:#15151A; }
    main div[data-testid="stRadio"]:has(input[value="定价处理中心"]) label:has(input:checked) * { color:#FFF; }
    .st-key-workflow_cards div[role="radiogroup"] { display:grid !important; grid-template-columns:repeat(4,1fr); gap:10px !important; margin:4px 0 22px; }
    .st-key-workflow_cards label[data-baseweb="radio"] { min-width:0 !important; min-height:86px; display:flex !important; align-items:center; justify-content:center; text-align:center; border:1px solid var(--line); border-radius:16px; padding:14px !important; background:rgba(255,255,255,.88); box-shadow:0 7px 20px rgba(21,21,26,.04); transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease; }
    .st-key-workflow_cards label[data-baseweb="radio"]:hover { transform:translateY(-3px); border-color:var(--violet); box-shadow:0 14px 32px rgba(21,21,26,.09); }
    .st-key-workflow_cards label[data-baseweb="radio"] > div:first-child { display:none !important; }
    .st-key-workflow_cards label[data-baseweb="radio"]:has(input:checked) { background:#15151A !important; border-color:#15151A; box-shadow:0 14px 34px rgba(21,21,26,.16); }
    .st-key-workflow_cards label[data-baseweb="radio"]:has(input:checked) * { color:#FFF !important; }
    .st-key-workflow_cards label[data-baseweb="radio"] p { font-size:14px; font-weight:700; }
    main div[data-testid="stRadio"] > div[role="radiogroup"] label { background:rgba(255,255,255,.88); border:1px solid var(--line); border-radius:16px; padding:16px 20px; min-width:260px; box-shadow:0 8px 22px rgba(21,21,26,.035); transition:.2s; }
    main div[data-testid="stRadio"] > div[role="radiogroup"] label:hover { transform:translateY(-2px); border-color:var(--violet); }
    .stButton>button, .stDownloadButton>button { border-radius:12px; min-height:46px; font-weight:700; transition:transform .18s ease,box-shadow .18s ease; }
    .stButton>button:hover, .stDownloadButton>button:hover { transform:translateY(-2px); box-shadow:0 10px 25px rgba(21,21,26,.12); }
    .stButton>button[kind="primary"], .stDownloadButton>button { background:#15151A; color:#FFF; border:1px solid #15151A; }
    .stButton>button[kind="primary"]:hover, .stDownloadButton>button:hover { background:var(--violet); color:#FFF; border-color:var(--violet); }
    @media(max-width:800px){ .hero{padding:30px 25px}.hero h1{font-size:31px}.stepbar{grid-template-columns:1fr 1fr}.empty-grid{grid-template-columns:1fr}.page-head{align-items:flex-start;flex-direction:column} .st-key-workflow_cards div[role="radiogroup"]{grid-template-columns:1fr 1fr !important} }
    </style>
    <div class="hero">
      <div class="brandline"><span class="brandmark">+10</span>JILL10 PRICING</div>
      <div class="eyebrow">Pricing Workspace</div>
      <h1>产品包批量定价与结果校验</h1>
      <p>系统自动完成品类识别、价格计算和异常检查，并在不改变原始文件结构的前提下生成可直接使用的新产品包。</p>
    </div>
    <div class="stepbar">
      <div class="step"><b>01</b><strong>上传产品包</strong>选择普通或 Shopify 格式</div>
      <div class="step"><b>02</b><strong>识别商品品类</strong>自动匹配相似品类与价格</div>
      <div class="step"><b>03</b><strong>复核异常商品</strong>批量校正低置信度结果</div>
      <div class="step"><b>04</b><strong>导出处理结果</strong>保留结构并更新价格字段</div>
    </div>
    """,
    unsafe_allow_html=True,
)

store = _workspace_store()
_prune_workspaces(store)
workspace_id = st.query_params.get("workspace")
if not _valid_workspace_id(workspace_id):
    workspace_id = uuid.uuid4().hex
    st.query_params["workspace"] = workspace_id
workspace = store.setdefault(
    workspace_id,
    {
        "files": {SUPPLIER: [], SHOPIFY: []},
        "mappings": {},
        "product_mappings": {},
        "price_ranges": {},
        "custom_categories": {},
        "manual_review_files": [],
        "history": [],
        "updated": time.time(),
    },
)
workspace["updated"] = time.time()

if "price_range_overrides" not in st.session_state:
    st.session_state.price_range_overrides = dict(workspace.get("price_ranges", {}))
if "price_editor_version" not in st.session_state:
    st.session_state.price_editor_version = 0
if "learned_category_mappings" not in st.session_state:
    st.session_state.learned_category_mappings = dict(workspace.get("mappings", {}))
if "product_category_mappings" not in st.session_state:
    st.session_state.product_category_mappings = dict(workspace.get("product_mappings", {}))
if "custom_category_rules" not in st.session_state:
    st.session_state.custom_category_rules = dict(workspace.get("custom_categories", {}))
if "manual_review_files" not in st.session_state:
    st.session_state.manual_review_files = set(workspace.get("manual_review_files", []))


def _custom_rule_objects() -> tuple[CategoryRule, ...]:
    rules = []
    for rule_id, values in st.session_state.custom_category_rules.items():
        primary, _, fallback_name = str(rule_id).partition("::")
        name = str(values.get("name", fallback_name)).strip()
        keywords = tuple(
            value.strip() for value in values.get("keywords", []) if str(value).strip()
        )
        rules.append(CategoryRule(
            primary=str(values.get("primary", primary)).strip(),
            name=name,
            minimum=float(values["minimum"]),
            maximum=float(values["maximum"]),
            keywords=keywords or (name.lower(),),
        ))
    return tuple(rules)


def _all_rules() -> tuple[CategoryRule, ...]:
    return tuple(CATEGORY_RULES) + _custom_rule_objects()


def _rules_for_available_primary(primary: str) -> tuple[CategoryRule, ...]:
    return tuple(rule for rule in _all_rules() if rule.primary == primary)


def _resolve_available_rule(value: str) -> CategoryRule | None:
    matches = [rule for rule in _all_rules() if rule.rule_id == value]
    if matches:
        return matches[0]
    named = [rule for rule in _all_rules() if rule.name == value]
    return named[0] if len(named) == 1 else resolve_rule(value)


def _record_change(label: str) -> None:
    """Save one reversible snapshot before changing pricing configuration."""
    history = workspace.setdefault("history", [])
    history.append({
        "label": label,
        "time": time.strftime("%H:%M:%S"),
        "mappings": dict(st.session_state.learned_category_mappings),
        "product_mappings": dict(st.session_state.product_category_mappings),
        "price_ranges": dict(st.session_state.price_range_overrides),
        "custom_categories": dict(st.session_state.custom_category_rules),
    })
    del history[:-20]


def _undo_last_change() -> str | None:
    history = workspace.setdefault("history", [])
    if not history:
        return None
    snapshot = history.pop()
    st.session_state.learned_category_mappings = dict(snapshot["mappings"])
    st.session_state.product_category_mappings = dict(snapshot["product_mappings"])
    st.session_state.price_range_overrides = dict(snapshot["price_ranges"])
    st.session_state.custom_category_rules = dict(snapshot.get("custom_categories", {}))
    st.session_state.price_editor_version += 1
    workspace["mappings"] = dict(snapshot["mappings"])
    workspace["product_mappings"] = dict(snapshot["product_mappings"])
    workspace["price_ranges"] = dict(snapshot["price_ranges"])
    workspace["custom_categories"] = dict(snapshot.get("custom_categories", {}))
    workspace["updated"] = time.time()
    return str(snapshot["label"])

with st.sidebar:
    st.markdown("## +10 · JILL10 PRICING")
    st.caption("智能产品定价工作台")
    st.markdown("---")
    st.caption("独立工作区")
    st.code(workspace_id[:8].upper(), language=None)
    st.caption("文件闲置6小时后自动清理")
    history = workspace.setdefault("history", [])
    with st.expander(f"修改记录 · {len(history)}"):
        if history:
            for item in reversed(history[-6:]):
                st.caption(f"{item['time']} · {item['label']}")
            if st.button("撤销上一次修改", use_container_width=True):
                undone = _undo_last_change()
                if undone:
                    st.toast(f"已撤销：{undone}")
                    st.rerun()
        else:
            st.caption("尚无可撤销的修改")
    if st.button("新建空白工作区", use_container_width=True):
        store.pop(workspace_id, None)
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.query_params.clear()
        st.rerun()
    st.caption("分享时只发送不带 ?workspace= 的应用主网址")

navigation = st.radio(
    "功能导航",
    ["定价处理中心", "品类与价格规则", "使用说明"],
    horizontal=True,
    label_visibility="collapsed",
    key="main_navigation",
)

if navigation == "使用说明":
    st.markdown('<div class="page-head"><div><div class="section-kicker">Guide</div><h2>使用说明</h2></div><p>三个步骤完成产品包改价</p></div>', unsafe_allow_html=True)
    guide_cols = st.columns(3)
    guide_cols[0].info("**1. 选择格式并上传**\n\n供应商文件选择供应商入口，Shopify导出文件选择Shopify入口。支持一次上传多个CSV。")
    guide_cols[1].info("**2. 检查结果**\n\n确认识别品类。无法识别的商品保持原价，也可以手动指定正确品类后重新处理。")
    guide_cols[2].info("**3. 下载文件**\n\n单独下载CSV，或下载批量ZIP。ZIP必须先解压，再把CSV上传到店铺后台。")
    st.warning("分享给别人时，只发送不带 ?workspace= 参数的应用主网址。")
    st.stop()

if navigation == "品类与价格规则":
    st.markdown('<div class="page-head"><div><div class="section-kicker">Category & Pricing Rules</div><h2>品类与价格规则</h2></div><p>维护品类关系和价格范围，修改后同时应用于两种产品包格式</p></div>', unsafe_allow_html=True)
    rule_overview = st.columns(3)
    rule_overview[0].metric("一级品类", len(PRIMARY_CATEGORIES))
    rule_overview[1].metric("具体品类规则", len(_all_rules()))
    rule_overview[2].metric("自定义价格范围", len(st.session_state.price_range_overrides))
    relationship_primary = st.selectbox(
        "查看品类关系",
        list(PRIMARY_CATEGORIES),
        key="relationship_primary",
    )
    relationship_rules = _rules_for_available_primary(relationship_primary)
    st.caption(
        f"{relationship_primary} 下包含 {len(relationship_rules)} 个具体品类："
        + "、".join(rule.name for rule in relationship_rules)
    )
    with st.expander("新增二级品类", expanded=False):
        st.caption("新增后会立即出现在人工品类选择中；填写识别关键词后，也可以参与自动识别。")
        with st.form("add_custom_category_form", clear_on_submit=True):
            add_columns = st.columns(2)
            new_primary = add_columns[0].selectbox("所属一级品类", list(PRIMARY_CATEGORIES))
            new_name = add_columns[1].text_input("二级品类名称", placeholder="例如 Vests")
            price_columns = st.columns(2)
            new_minimum = price_columns[0].number_input("最低价（USD）", min_value=0.01, value=19.99, step=1.0)
            new_maximum = price_columns[1].number_input("最高价（USD）", min_value=0.01, value=29.99, step=1.0)
            new_keywords = st.text_input(
                "识别关键词（可选，用英文逗号分隔）",
                placeholder="vest, waistcoat, sleeveless jacket",
            )
            add_category = st.form_submit_button("保存并启用二级品类", use_container_width=True)
        if add_category:
            clean_name = new_name.strip()
            rule_id = f"{new_primary}::{clean_name}"
            existing_ids = {rule.rule_id.casefold() for rule in _all_rules()}
            if not clean_name:
                st.error("请填写二级品类名称。")
            elif "::" in clean_name:
                st.error("二级品类名称不能包含 ::。")
            elif rule_id.casefold() in existing_ids:
                st.error("这个一级品类下已经存在同名二级品类。")
            elif new_maximum < new_minimum:
                st.error("最高价必须大于或等于最低价。")
            else:
                keywords = [value.strip() for value in new_keywords.split(",") if value.strip()]
                _record_change(f"新增二级品类 · {clean_name}")
                st.session_state.custom_category_rules[rule_id] = {
                    "primary": new_primary,
                    "name": clean_name,
                    "minimum": round(float(new_minimum), 2),
                    "maximum": round(float(new_maximum), 2),
                    "keywords": keywords or [clean_name.lower()],
                }
                workspace["custom_categories"] = dict(st.session_state.custom_category_rules)
                workspace["updated"] = time.time()
                st.toast(f"已新增二级品类：{clean_name}")
                st.rerun()
        custom_rule_objects = _custom_rule_objects()
        if custom_rule_objects:
            st.markdown("#### 已添加的二级品类")
            custom_labels = {
                f"{rule.primary} → {rule.name}（${rule.minimum:.2f}–${rule.maximum:.2f}）": rule.rule_id
                for rule in custom_rule_objects
            }
            remove_label = st.selectbox("选择要删除的自定义品类", list(custom_labels))
            if st.button("删除所选自定义品类", type="secondary"):
                removed_rule_id = custom_labels[remove_label]
                removed_name = st.session_state.custom_category_rules[removed_rule_id]["name"]
                _record_change(f"删除二级品类 · {removed_name}")
                st.session_state.custom_category_rules.pop(removed_rule_id, None)
                st.session_state.price_range_overrides.pop(removed_rule_id, None)
                st.session_state.learned_category_mappings = {
                    key: value for key, value in st.session_state.learned_category_mappings.items()
                    if value != removed_rule_id
                }
                st.session_state.product_category_mappings = {
                    key: value for key, value in st.session_state.product_category_mappings.items()
                    if value != removed_rule_id
                }
                workspace["custom_categories"] = dict(st.session_state.custom_category_rules)
                workspace["price_ranges"] = dict(st.session_state.price_range_overrides)
                workspace["mappings"] = dict(st.session_state.learned_category_mappings)
                workspace["product_mappings"] = dict(st.session_state.product_category_mappings)
                workspace["updated"] = time.time()
                st.rerun()
        custom_tools = st.columns(2)
        custom_tools[0].download_button(
            "下载自定义品类",
            data=json.dumps(st.session_state.custom_category_rules, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="custom-categories.json",
            mime="application/json",
            use_container_width=True,
        )
        custom_import = custom_tools[1].file_uploader(
            "导入自定义品类",
            type=["json"],
            key="custom_category_import",
            label_visibility="collapsed",
        )
        if custom_import is not None:
            import_bytes = custom_import.getvalue()
            import_digest = hashlib.sha256(import_bytes).hexdigest()
            if st.session_state.get("last_custom_category_import") != import_digest:
                try:
                    imported_categories = json.loads(import_bytes.decode("utf-8"))
                    validated_categories = {}
                    for imported_id, values in imported_categories.items():
                        primary = str(values["primary"]).strip()
                        name = str(values["name"]).strip()
                        minimum = float(values["minimum"])
                        maximum = float(values["maximum"])
                        if (
                            primary not in PRIMARY_CATEGORIES
                            or not name
                            or minimum <= 0
                            or maximum < minimum
                            or str(imported_id) != f"{primary}::{name}"
                            or str(imported_id).casefold() in {rule.rule_id.casefold() for rule in CATEGORY_RULES}
                        ):
                            raise ValueError
                        validated_categories[str(imported_id)] = {
                            "primary": primary,
                            "name": name,
                            "minimum": round(minimum, 2),
                            "maximum": round(maximum, 2),
                            "keywords": [
                                str(value).strip() for value in values.get("keywords", [name.lower()])
                                if str(value).strip()
                            ],
                        }
                    _record_change(f"导入自定义品类 · {len(validated_categories)} 项")
                    st.session_state.custom_category_rules.update(validated_categories)
                    st.session_state.last_custom_category_import = import_digest
                    workspace["custom_categories"] = dict(st.session_state.custom_category_rules)
                    workspace["updated"] = time.time()
                    st.toast(f"已导入 {len(validated_categories)} 个二级品类")
                    st.rerun()
                except Exception:
                    st.error("自定义品类文件无法读取或内容不符合要求。")
    file_format = SUPPLIER
    new_uploads = None
    workflow_stage = None
else:
    st.markdown('<div class="page-head"><div><div class="section-kicker">Pricing Workspace</div><h2>定价处理中心</h2></div><p>上传、识别、校正和导出集中在同一处理流程</p></div>', unsafe_allow_html=True)
    with st.container(key="workflow_cards"):
        workflow_stage = st.radio(
            "处理步骤",
            ["① 上传产品包", "② 检查识别", "③ 纠正异常", "④ 下载结果"],
            horizontal=True,
            label_visibility="collapsed",
            key="workflow_stage",
        )
    format_label = st.radio(
        "产品包格式",
        ["供应商原格式", "Shopify 格式"],
        horizontal=True,
        label_visibility="collapsed",
    )
    file_format = SHOPIFY if "Shopify" in format_label else SUPPLIER
    format_help = (
        "Shopify CSV：保留 Shopify 原始列结构，只修改 Variant Price 与 Variant Compare At Price。"
        if file_format == SHOPIFY
        else "供应商 CSV：保留原始27列结构，只修改 price 与 compare_at_price。"
    )
    st.markdown(f'<div class="format-note">{format_help}</div>', unsafe_allow_html=True)
    if workflow_stage == "① 上传产品包":
        new_uploads = st.file_uploader(
            "上传 Shopify CSV" if file_format == SHOPIFY else "上传供应商产品 CSV",
            type=["csv"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            key=f"product_csv_uploader_{file_format}",
        )
    else:
        new_uploads = None

with st.expander(
    "编辑全部价格范围" if navigation == "品类与价格规则" else "快速修改价格范围",
    expanded=navigation == "品类与价格规则",
):
    st.caption("修改后点击保存。这里只改变价格区间，不改变品类名称；新范围会立即用于供应商和 Shopify 两个入口。")
    range_rows = []
    for rule in _all_rules():
        custom = st.session_state.price_range_overrides.get(rule.rule_id, {})
        range_rows.append({
            "规则ID": rule.rule_id,
            "一级品类": rule.primary,
            "具体品类": rule.name,
            "最低价": float(custom.get("minimum", rule.minimum)),
            "最高价": float(custom.get("maximum", rule.maximum)),
        })
    edited_ranges = st.data_editor(
        pd.DataFrame(range_rows),
        use_container_width=True,
        hide_index=True,
        disabled=["规则ID", "一级品类", "具体品类"],
        column_config={
            "最低价": st.column_config.NumberColumn("最低价（USD）", min_value=0.01, step=0.01, format="$%.2f"),
            "最高价": st.column_config.NumberColumn("最高价（USD）", min_value=0.01, step=0.01, format="$%.2f"),
        },
        key=f"price_range_editor_{st.session_state.price_editor_version}",
        height=420,
    )
    price_actions = st.columns(3)
    if price_actions[0].button("保存价格范围", use_container_width=True):
        invalid = edited_ranges[
            edited_ranges["最低价"].isna()
            | edited_ranges["最高价"].isna()
            | (edited_ranges["最低价"] <= 0)
            | (edited_ranges["最高价"] < edited_ranges["最低价"])
        ]
        if not invalid.empty:
            st.error("保存失败：最低价必须大于0，最高价必须大于或等于最低价。")
        else:
            defaults = {rule.rule_id: rule for rule in _all_rules()}
            saved_ranges = {}
            for record in edited_ranges.to_dict("records"):
                rule = defaults[str(record["规则ID"])]
                minimum = round(float(record["最低价"]), 2)
                maximum = round(float(record["最高价"]), 2)
                if minimum != rule.minimum or maximum != rule.maximum:
                    saved_ranges[rule.rule_id] = {"minimum": minimum, "maximum": maximum}
            _record_change("修改价格范围")
            st.session_state.price_range_overrides = saved_ranges
            st.session_state.price_editor_version += 1
            workspace["price_ranges"] = dict(saved_ranges)
            workspace["updated"] = time.time()
            st.success(f"价格表已保存，共有 {len(saved_ranges)} 个品类使用自定义范围。")
            st.rerun()
    if price_actions[1].button("恢复默认价格表", use_container_width=True):
        _record_change("恢复默认价格表")
        st.session_state.price_range_overrides = {}
        st.session_state.price_editor_version += 1
        st.session_state.pop("last_price_range_import", None)
        workspace["price_ranges"] = {}
        workspace["updated"] = time.time()
        st.rerun()
    price_actions[2].download_button(
        "下载自定义价格表",
        data=json.dumps(st.session_state.price_range_overrides, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="custom-price-ranges.json",
        mime="application/json",
        use_container_width=True,
    )
    range_import = st.file_uploader("导入以前保存的自定义价格表", type=["json"], key="price_range_json")
    if range_import is not None:
        import_bytes = range_import.getvalue()
        import_digest = hashlib.sha256(import_bytes).hexdigest()
        try:
            imported_ranges = json.loads(import_bytes.decode("utf-8"))
            known_ids = {rule.rule_id for rule in _all_rules()}
            valid_ranges = {}
            for rule_id, values in imported_ranges.items():
                minimum = float(values["minimum"])
                maximum = float(values["maximum"])
                if rule_id not in known_ids or minimum <= 0 or maximum < minimum:
                    raise ValueError
                valid_ranges[str(rule_id)] = {"minimum": round(minimum, 2), "maximum": round(maximum, 2)}
            if st.session_state.get("last_price_range_import") != import_digest:
                _record_change("导入自定义价格表")
                st.session_state.price_range_overrides = valid_ranges
                st.session_state.price_editor_version += 1
                st.session_state.last_price_range_import = import_digest
                workspace["price_ranges"] = dict(valid_ranges)
                workspace["updated"] = time.time()
                st.success(f"已导入 {len(valid_ranges)} 个自定义价格范围。")
        except Exception:
            st.error("自定义价格表无法读取，或存在无效价格范围。")

if navigation == "品类与价格规则":
    st.stop()

if new_uploads:
    workspace["files"][file_format] = [
        {"name": item.name, "data": item.getvalue()} for item in new_uploads
    ]
    workspace["updated"] = time.time()

uploaded_files = list(workspace["files"].get(file_format, []))

if uploaded_files:
    st.success(f"当前批次已保留 {len(uploaded_files)} 个产品包。普通页面刷新不会丢失；应用重启或重新部署后需重新上传。")

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
            [{"一级品类": rule.primary, "具体品类": rule.name, "最低售价": rule.minimum, "最高售价": rule.maximum} for rule in _all_rules()],
            use_container_width=True,
            hide_index=True,
        )
    st.stop()

if workflow_stage == "① 上传产品包":
    st.markdown('<div class="section-kicker">Uploaded Files</div><div class="section-title">已上传产品包</div>', unsafe_allow_html=True)
    upload_overview = []
    for uploaded in uploaded_files:
        try:
            loaded_overview = load_csv_bytes(_upload_bytes(uploaded))
            source_overview = prepare_frame(loaded_overview.frame, file_format)
            summary_overview = validate_frame(source_overview)
            upload_overview.append({
                "文件名": _upload_name(uploaded),
                "商品": summary_overview.products,
                "数据行": summary_overview.rows,
                "字段": len(source_overview.columns),
                "状态": "可以处理" if not summary_overview.missing_columns else "缺少必要字段",
            })
        except Exception:
            upload_overview.append({"文件名": _upload_name(uploaded), "商品": 0, "数据行": 0, "字段": 0, "状态": "读取失败"})
    st.dataframe(pd.DataFrame(upload_overview), use_container_width=True, hide_index=True)
    st.info("文件已保存在当前独立工作区。点击上方“② 检查识别”继续处理。")
    st.stop()

if workflow_stage == "③ 纠正异常":
    with st.expander("品类映射记忆（可选）"):
        mapping_file = st.file_uploader("导入以前保存的品类映射", type=["json"], key="mapping_json")
        if mapping_file is not None:
            try:
                mapping_bytes = mapping_file.getvalue()
                mapping_digest = hashlib.sha256(mapping_bytes).hexdigest()
                imported = json.loads(mapping_bytes.decode("utf-8"))
                valid = {str(key): str(value) for key, value in imported.items() if _resolve_available_rule(str(value)) is not None}
                if valid and st.session_state.get("last_mapping_import") != mapping_digest:
                    _record_change("导入品类映射")
                    st.session_state.learned_category_mappings.update(valid)
                    st.session_state.last_mapping_import = mapping_digest
                    workspace["mappings"] = dict(st.session_state.learned_category_mappings)
                    workspace["updated"] = time.time()
                    st.success(f"已导入 {len(valid)} 条品类映射。")
            except Exception:
                st.error("映射文件无法读取。")

review_file_indices: set[int] = set()
if workflow_stage == "③ 纠正异常":
    for review_index, review_upload in enumerate(uploaded_files):
        try:
            review_loaded = load_csv_bytes(_upload_bytes(review_upload))
            review_source = prepare_frame(review_loaded.frame, file_format)
            review_result = apply_fixed_pricing(
                review_source,
                st.session_state.learned_category_mappings,
                st.session_state.price_range_overrides,
                st.session_state.product_category_mappings,
                _custom_rule_objects(),
            )
            review_similar = (
                review_result.product_summary["匹配方式"].astype(str).str.contains("语义匹配", regex=False).any()
                if "匹配方式" in review_result.product_summary.columns else False
            )
            if (
                review_result.unresolved_handles
                or review_similar
                or _upload_name(review_upload) in st.session_state.manual_review_files
            ):
                review_file_indices.add(review_index)
        except Exception:
            continue
    if not review_file_indices:
        st.success("无需要纠正的产品。当前批次没有未识别、低置信度或人工标记的商品。")
        st.caption("如果你在“② 检查识别”中发现自动识别错误，可以点击“识别有误，加入纠正”。")
        st.stop()

stage_titles = {
    "② 检查识别": ("File Tasks", "产品包任务"),
    "③ 纠正异常": ("Exception Review", "集中处理异常商品"),
    "④ 下载结果": ("Export Results", "下载处理结果"),
}
stage_kicker, stage_title = stage_titles.get(workflow_stage, ("Batch Queue", "处理队列"))
st.markdown(f'<div class="section-kicker">{stage_kicker}</div><div class="section-title">{stage_title}</div>', unsafe_allow_html=True)
queue_cols = st.columns(3)
queue_cols[0].metric("已上传文件", len(uploaded_files))

completed_outputs: list[tuple[str, bytes]] = []
needs_attention = 0

for file_index, uploaded in enumerate(uploaded_files):
    if workflow_stage == "③ 纠正异常" and file_index not in review_file_indices:
        continue
    uploaded_name = _upload_name(uploaded)
    uploaded_data = _upload_bytes(uploaded)
    with st.expander(
        f"{file_index + 1:02d}  ·  {uploaded_name}",
        expanded=workflow_stage in {"② 检查识别", "③ 纠正异常"},
    ):
        try:
            loaded = load_csv_bytes(uploaded_data)
            source = prepare_frame(loaded.frame, file_format)
            before_summary = validate_frame(source)
            if before_summary.missing_columns:
                st.error("缺少必要字段：" + ", ".join(before_summary.missing_columns))
                needs_attention += 1
                continue

            metrics = st.columns(5)
            metrics[0].metric("数据行", f"{before_summary.rows:,}")
            metrics[1].metric("商品", f"{before_summary.products:,}")
            metrics[2].metric("有价格记录", f"{before_summary.variants:,}")
            metrics[3].metric("无价格图片行", f"{before_summary.image_only_rows:,}")
            metrics[4].metric("字段", f"{len(source.columns):,}")

            pricing_result = apply_fixed_pricing(
                source,
                st.session_state.learned_category_mappings,
                st.session_state.price_range_overrides,
                st.session_state.product_category_mappings,
                _custom_rule_objects(),
            )

            priced_count = len(pricing_result.product_summary)
            unchanged_count = len(pricing_result.unresolved_handles)
            discounted_count = (
                int((pricing_result.product_summary["新划线价"] > 0).sum())
                if not pricing_result.product_summary.empty else 0
            )
            outcome = st.columns(4)
            outcome[0].metric("已完成改价", priced_count)
            outcome[1].metric("保持原价", unchanged_count)
            outcome[2].metric("打折商品", discounted_count)
            outcome[3].metric("处理状态", "需要确认" if unchanged_count else "全部完成")
            recognition_rate = (
                priced_count / pricing_result.expected_products
                if pricing_result.expected_products else 1.0
            )
            st.progress(
                min(max(recognition_rate, 0.0), 1.0),
                text=f"自动识别完成度 {recognition_rate * 100:.1f}% · "
                f"{priced_count} 个已定价，{unchanged_count} 个等待确认",
            )
            if not unchanged_count:
                st.markdown(
                    f'<div class="status-strip">已完成：{priced_count} 个商品全部识别并完成定价。</div>',
                    unsafe_allow_html=True,
                )
            if workflow_stage == "③ 纠正异常" and uploaded_name in st.session_state.manual_review_files:
                if st.button(
                    "此文件已检查完成，从纠正列表移除",
                    key=f"finish_manual_review_{file_index}",
                    use_container_width=True,
                ):
                    st.session_state.manual_review_files.discard(uploaded_name)
                    workspace["manual_review_files"] = sorted(st.session_state.manual_review_files)
                    workspace["updated"] = time.time()
                    st.rerun()

            if workflow_stage == "② 检查识别":
                task_issues = validate_fixed_pricing(pricing_result)
                if task_issues:
                    needs_attention += 1
                    st.error("；".join(task_issues))
                elif unchanged_count:
                    needs_attention += 1
                    st.warning(f"需要确认 {unchanged_count} 个商品。点击上方“③ 纠正异常”集中处理。")
                else:
                    st.success("自动识别和价格校验均已完成，可以进入下载步骤。")
                if uploaded_name in st.session_state.manual_review_files:
                    st.info("此产品包已人工加入“③ 纠正异常”。")
                    if st.button(
                        "取消人工纠正标记",
                        key=f"remove_review_{file_index}",
                        use_container_width=True,
                    ):
                        st.session_state.manual_review_files.discard(uploaded_name)
                        workspace["manual_review_files"] = sorted(st.session_state.manual_review_files)
                        workspace["updated"] = time.time()
                        st.rerun()
                elif st.button(
                    "识别有误，加入纠正",
                    key=f"add_review_{file_index}",
                    use_container_width=True,
                ):
                    st.session_state.manual_review_files.add(uploaded_name)
                    workspace["manual_review_files"] = sorted(st.session_state.manual_review_files)
                    workspace["updated"] = time.time()
                    st.toast("已加入纠正步骤")
                    st.rerun()
                continue

            if workflow_stage == "④ 下载结果":
                if "匹配方式" in pricing_result.product_summary.columns:
                    download_similar = pricing_result.product_summary[
                        pricing_result.product_summary["匹配方式"].astype(str).str.contains("语义匹配", regex=False)
                    ]
                else:
                    download_similar = pricing_result.product_summary.copy()
                download_confirmed = download_similar.empty or bool(st.session_state.get(f"confirm_{file_index}", False))
                download_issues = validate_fixed_pricing(pricing_result)
                if download_issues or not download_confirmed:
                    needs_attention += 1
                    st.error("此文件暂不能下载，请返回“③ 纠正异常”完成确认。")
                    if download_issues:
                        st.caption("；".join(download_issues))
                else:
                    output_name = uploaded_name.rsplit(".", 1)[0] + output_suffix(file_format)
                    output_bytes = export_csv(pricing_result.frame, loaded, file_format)
                    completed_outputs.append((output_name, output_bytes))
                    if pricing_result.unresolved_handles:
                        st.warning(
                            f"部分完成：{len(pricing_result.product_summary)} 个商品已修改，"
                            f"{len(pricing_result.unresolved_handles)} 个未识别商品保持原价。"
                        )
                    else:
                        st.success("可以下载：全部商品已完成定价并通过校验。")
                    st.download_button(
                        f"下载 {output_name}",
                        data=output_bytes,
                        file_name=output_name,
                        mime="text/csv",
                        key=f"stage_download_{file_index}",
                        use_container_width=True,
                    )
                continue

            # Manual correction is always available, even when automatic
            # classification succeeded. Mappings are stored by supplier category.
            if not pricing_result.product_summary.empty:
                recognized = (
                    pricing_result.product_summary[["原始分类", "一级品类", "识别品类"]]
                    .drop_duplicates(subset=["原始分类"])
                )
                all_rule_labels = [
                    f"{rule.primary} → {rule.name}（${rule.minimum:.2f}–${rule.maximum:.2f}）"
                    for rule in _all_rules()
                ]
                manual_corrections: dict[str, str | None] = {}
                with st.expander("自动识别不正确？手动选择正确品类", expanded=False):
                    st.caption("选择后会重新计算整个原始分类的价格，并记住这次选择。没有错误时保持当前识别即可。")
                    for _, recognized_row in recognized.iterrows():
                        source_category = str(recognized_row["原始分类"])
                        current_label = f"{recognized_row['一级品类']} → {recognized_row['识别品类']}"
                        choices = ["保持当前识别"]
                        if source_category in st.session_state.learned_category_mappings:
                            choices.append("恢复程序自动识别")
                        choices.extend(all_rule_labels)
                        selection = st.selectbox(
                            f"原始分类：{source_category}｜当前：{current_label}",
                            choices,
                            key=f"manual_rule_{file_index}_{source_category}",
                        )
                        if selection == "恢复程序自动识别":
                            manual_corrections[source_category] = None
                        elif selection not in {"保持当前识别", "恢复程序自动识别"}:
                            manual_corrections[source_category] = _all_rules()[all_rule_labels.index(selection)].rule_id
                    if st.button(
                        "保存人工纠正并重新定价",
                        key=f"save_manual_{file_index}",
                        disabled=not manual_corrections,
                        use_container_width=True,
                    ):
                        _record_change(f"纠正原始品类 · {len(manual_corrections)} 项")
                        for source_category, rule_id in manual_corrections.items():
                            if rule_id is None:
                                st.session_state.learned_category_mappings.pop(source_category, None)
                            else:
                                st.session_state.learned_category_mappings[source_category] = rule_id
                        workspace["mappings"] = dict(st.session_state.learned_category_mappings)
                        workspace["updated"] = time.time()
                        st.rerun()

            if pricing_result.unresolved_handles:
                unresolved_rows = source[source["Handle"].astype(str).isin(pricing_result.unresolved_handles)]
                categories = sorted(value for value in unresolved_rows["category"].astype(str).str.strip().unique() if value)
                st.warning(
                    f"有 {len(pricing_result.unresolved_handles)} 个商品暂时无法识别。"
                    "这些商品会保持原价格不变，其余商品照常修改并允许下载。"
                    "你也可以在下面选择参考品类后重新处理。"
                )
                selected_mappings = {}
                for category in categories:
                    category_rows = unresolved_rows[unresolved_rows["category"].astype(str).str.strip() == category]
                    category_titles = display_titles(source).loc[category_rows.index]
                    product_details = category_rows.assign(商品名称=category_titles.values).groupby(
                        "Handle", sort=False, dropna=False
                    ).agg(
                        商品名称=("商品名称", "first"),
                        原始分类=("category", "first"),
                        原售价=("price", "first"),
                        SKU数量=("price", "size"),
                    ).reset_index()
                    with st.expander(
                        f"查看未识别商品 · {category}（{len(product_details)} 个）",
                        expanded=True,
                    ):
                        st.dataframe(
                            product_details[["商品名称", "Handle", "原始分类", "原售价", "SKU数量"]],
                            use_container_width=True,
                            hide_index=True,
                            height=min(420, 72 + len(product_details) * 35),
                        )
                        st.caption("下面选择的参考品类会应用到这张表中的所有商品。")
                    sample_titles = " ".join(product_details["商品名称"].astype(str).head(12))
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
                    # Explicit supplier-category evidence outranks fuzzy title
                    # similarity (for example, "Men's ... Vests" must not be
                    # preselected as bedding because a title says "quilted").
                    suggested_primary = infer_primary_category(category)
                    if not suggested_primary and candidates:
                        suggested_primary = candidates[0][0].primary
                    primary_options = ["请选择"] + list(PRIMARY_CATEGORIES)
                    primary_index = primary_options.index(suggested_primary) if suggested_primary in primary_options else 0
                    primary = st.selectbox(
                        f"{category}：先选择一级品类",
                        primary_options,
                        index=primary_index,
                        key=f"primary_{file_index}_{category}",
                    )
                    if primary != "请选择":
                        candidate_rules = _rules_for_available_primary(primary)
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
                    _record_change(f"确认未识别品类 · {len(selected_mappings)} 项")
                    st.session_state.learned_category_mappings.update(selected_mappings)
                    workspace["mappings"] = dict(st.session_state.learned_category_mappings)
                    workspace["updated"] = time.time()
                    st.rerun()

            if "匹配方式" in pricing_result.product_summary.columns:
                similar = pricing_result.product_summary[
                    pricing_result.product_summary["匹配方式"].astype(str).str.contains("语义匹配", regex=False)
                ]
            else:
                similar = pricing_result.product_summary.copy()

            similar_confirmed = True
            result_tab, changes_tab = st.tabs(["定价结果", "价格明细"])
            with result_tab:
                if not pricing_result.product_summary.empty:
                    visible = pricing_result.product_summary.drop(columns=["区间下限", "区间上限"]).reset_index(drop=True)
                    filter_cols = st.columns([2, 1, 1])
                    search_term = filter_cols[0].text_input(
                        "搜索商品",
                        placeholder="输入商品 Handle、原始分类或识别品类",
                        key=f"product_search_{file_index}",
                    ).strip().casefold()
                    primary_values = sorted(visible["一级品类"].dropna().astype(str).unique().tolist())
                    primary_filter = filter_cols[1].selectbox(
                        "一级品类",
                        ["全部"] + primary_values,
                        key=f"primary_filter_{file_index}",
                    )
                    price_filter = filter_cols[2].selectbox(
                        "价格状态",
                        ["全部", "有折扣", "无折扣"],
                        key=f"price_filter_{file_index}",
                    )
                    if search_term:
                        searchable_columns = [
                            column for column in ["Handle", "原始分类", "一级品类", "识别品类", "匹配方式"]
                            if column in visible.columns
                        ]
                        search_mask = pd.Series(False, index=visible.index)
                        for column in searchable_columns:
                            search_mask |= visible[column].fillna("").astype(str).str.casefold().str.contains(
                                search_term, regex=False
                            )
                        visible = visible[search_mask]
                    if primary_filter != "全部":
                        visible = visible[visible["一级品类"].astype(str) == primary_filter]
                    if price_filter == "有折扣":
                        visible = visible[visible["新划线价"] > 0]
                    elif price_filter == "无折扣":
                        visible = visible[visible["新划线价"] <= 0]
                    visible = visible.reset_index(drop=True)
                    st.caption(f"当前显示 {len(visible)} / {len(pricing_result.product_summary)} 个商品。可搜索并按一级品类或折扣状态筛选。")
                    st.caption("品类不对？直接点击表格中的一行或多行，再在表格下方批量纠正。按住 Ctrl 可连续选择多行。")
                    if visible.empty:
                        st.info("没有符合当前搜索或筛选条件的商品。")
                        selection_event = None
                    else:
                        selection_event = st.dataframe(
                            visible,
                            use_container_width=True,
                            hide_index=True,
                            height=330,
                            on_select="rerun",
                            selection_mode="multi-row",
                            key=f"pricing_table_{file_index}",
                        )
                    selected_rows = getattr(getattr(selection_event, "selection", None), "rows", [])
                    if selected_rows:
                        selected_items = visible.iloc[[int(index) for index in selected_rows]].copy()
                        selected_handles = selected_items["Handle"].astype(str).tolist()
                        selected_token = hashlib.sha256(
                            "|".join(sorted(selected_handles)).encode("utf-8")
                        ).hexdigest()[:10]
                        st.markdown(f"#### 批量纠正已选中的 {len(selected_handles)} 个商品")
                        st.dataframe(
                            selected_items[["Handle", "原始分类", "一级品类", "识别品类", "价格区间"]],
                            use_container_width=True,
                            hide_index=True,
                            height=min(250, 72 + len(selected_items) * 35),
                        )
                        selected_primaries = selected_items["一级品类"].astype(str).unique().tolist()
                        selected_categories = selected_items["识别品类"].astype(str).unique().tolist()
                        correction_info = st.columns(3)
                        correction_info[0].metric("已选择商品", len(selected_handles))
                        correction_info[1].metric("当前一级品类数", len(selected_primaries))
                        correction_info[2].metric("当前具体品类数", len(selected_categories))

                        primary_options = list(PRIMARY_CATEGORIES)
                        current_primary = selected_primaries[0]
                        primary_index = primary_options.index(current_primary) if current_primary in primary_options else 0
                        corrected_primary = st.selectbox(
                            "选择正确的一级品类",
                            primary_options,
                            index=primary_index,
                            key=f"single_primary_{file_index}_{selected_token}",
                        )
                        corrected_rules = _rules_for_available_primary(corrected_primary)
                        corrected_labels = []
                        for rule in corrected_rules:
                            custom_range = st.session_state.price_range_overrides.get(rule.rule_id, {})
                            minimum = float(custom_range.get("minimum", rule.minimum))
                            maximum = float(custom_range.get("maximum", rule.maximum))
                            corrected_labels.append(f"{rule.name}（${minimum:.2f}–${maximum:.2f}）")
                        current_rule_index = next(
                            (
                                index for index, rule in enumerate(corrected_rules)
                                if len(selected_categories) == 1 and rule.name == selected_categories[0]
                            ),
                            0,
                        )
                        corrected_label = st.selectbox(
                            "选择正确的具体品类",
                            corrected_labels,
                            index=current_rule_index,
                            key=f"single_rule_{file_index}_{selected_token}_{corrected_primary}",
                        )
                        correction_actions = st.columns(2)
                        if correction_actions[0].button(
                            f"保存并重新定价这 {len(selected_handles)} 个商品",
                            key=f"save_single_{file_index}_{selected_token}",
                            use_container_width=True,
                        ):
                            selected_rule = corrected_rules[corrected_labels.index(corrected_label)]
                            _record_change(f"批量纠正商品 · {len(selected_handles)} 个")
                            for selected_handle in selected_handles:
                                st.session_state.product_category_mappings[selected_handle] = selected_rule.rule_id
                            workspace["product_mappings"] = dict(st.session_state.product_category_mappings)
                            workspace["updated"] = time.time()
                            st.rerun()
                        if any(handle in st.session_state.product_category_mappings for handle in selected_handles):
                            if correction_actions[1].button(
                                "恢复所选商品的整组品类规则",
                                key=f"reset_single_{file_index}_{selected_token}",
                                use_container_width=True,
                            ):
                                _record_change(f"恢复商品品类 · {len(selected_handles)} 个")
                                for selected_handle in selected_handles:
                                    st.session_state.product_category_mappings.pop(selected_handle, None)
                                workspace["product_mappings"] = dict(st.session_state.product_category_mappings)
                                workspace["updated"] = time.time()
                                st.rerun()
                if not similar.empty:
                    st.warning("请确认相似品类映射。")
                    st.dataframe(similar[["Handle", "匹配方式", "一级品类", "识别品类", "价格区间"]], use_container_width=True, hide_index=True, height=210)
                    similar_confirmed = st.checkbox("确认此文件的相似品类关系", key=f"confirm_{file_index}")
                    if similar_confirmed and "原始分类" in similar:
                        mapped_ids = [f"{primary}::{name}" for primary, name in zip(similar["一级品类"], similar["识别品类"])]
                        confirmed_mappings = dict(zip(similar["原始分类"], mapped_ids))
                        changed_mappings = {
                            key: value for key, value in confirmed_mappings.items()
                            if st.session_state.learned_category_mappings.get(key) != value
                        }
                        if changed_mappings:
                            _record_change(f"确认相似品类 · {len(changed_mappings)} 项")
                            st.session_state.learned_category_mappings.update(changed_mappings)
                            workspace["mappings"] = dict(st.session_state.learned_category_mappings)
                            workspace["updated"] = time.time()

            with changes_tab:
                preview = build_change_preview(source, pricing_result.frame)
                preview.insert(1, "商品名称", display_titles(source).loc[preview.index])
                changed_only = st.toggle("只看发生变化的记录", value=True, key=f"changed_{file_index}")
                shown = preview[preview["发生变化"]] if changed_only else preview
                st.dataframe(shown, use_container_width=True, hide_index=True, height=380)

            rule_issues = validate_fixed_pricing(pricing_result)
            st.caption(
                f"完整性检查：发现 {pricing_result.expected_products} 个可定价商品，"
                f"已生成 {len(pricing_result.product_summary)} 个定价结果。"
            )
            if before_summary.duplicate_skus:
                st.warning(
                    f"原始产品包中有 {before_summary.duplicate_skus} 行使用重复 SKU。"
                    "程序不会修改 SKU；该问题只作提醒，不再阻止价格文件下载。"
                )
            blocked = bool(
                rule_issues
                or not similar_confirmed
            )
            if blocked:
                needs_attention += 1
                if rule_issues:
                    st.error("；".join(rule_issues))
                elif not similar_confirmed:
                    st.info("确认相似品类后即可下载此文件。")
            else:
                output_name = uploaded_name.rsplit(".", 1)[0] + output_suffix(file_format)
                output_bytes = export_csv(pricing_result.frame, loaded, file_format)
                completed_outputs.append((output_name, output_bytes))
                if pricing_result.unresolved_handles:
                    st.warning(
                        f"已完成部分定价：{len(pricing_result.product_summary)} 个商品已修改，"
                        f"{len(pricing_result.unresolved_handles)} 个无法识别的商品保持原价。"
                    )
                else:
                    st.success("此产品包已完成并通过校验。")
                st.markdown(
                    '<div class="download-panel"><h3>此产品包已准备完成</h3>'
                    '<p>如无其他异常需要处理，请点击上方“④ 下载结果”获取文件。</p></div>',
                    unsafe_allow_html=True,
                )
        except Exception as exc:
            needs_attention += 1
            st.error(f"处理失败：{exc}")

if workflow_stage == "② 检查识别":
    queue_cols[1].metric("识别完成", max(0, len(uploaded_files) - needs_attention))
    queue_cols[2].metric("需要确认", needs_attention)
else:
    queue_cols[1].metric("已准备", len(completed_outputs))
    queue_cols[2].metric("待处理", needs_attention)

if workflow_stage == "④ 下载结果":
    st.markdown('<div class="section-kicker">Batch Export</div><div class="section-title">批量导出</div>', unsafe_allow_html=True)
    if completed_outputs:
        st.warning("批量下载得到的是 ZIP 压缩包，仅用于一次保存多个文件。上传店铺后台前必须先解压，并逐个上传里面的 CSV；不要把 ZIP 直接上传到店铺后台。")
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in completed_outputs:
                archive.writestr(name, data)
        st.download_button(
            f"下载全部已完成产品包（ZIP，上传后台前需解压）· {len(completed_outputs)} 个",
            data=zip_buffer.getvalue(),
            file_name="正确价格产品包.zip",
            mime="application/zip",
            use_container_width=True,
        )
    else:
        st.info("目前没有可以下载的文件，请返回“③ 纠正异常”完成确认。")
elif workflow_stage == "③ 纠正异常":
    st.info("完成异常确认后，点击上方“④ 下载结果”获取单个 CSV 或批量 ZIP。")

if workflow_stage == "③ 纠正异常" and st.session_state.learned_category_mappings:
    st.download_button(
        "保存品类映射文件",
        data=json.dumps(st.session_state.learned_category_mappings, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="category-mappings.json",
        mime="application/json",
    )
