from __future__ import annotations

import base64
import hashlib
from html import escape
import json
from io import BytesIO
from pathlib import Path
import time
import uuid
import zipfile

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
try:
    from streamlit_local_storage import LocalStorage
except ImportError:  # The pricing tool still starts if an optional UI add-on fails to install.
    LocalStorage = None

from category_rules import CategoryRule, CATEGORY_RULES, PRIMARY_CATEGORIES, infer_primary_category, rank_similar_categories, resolve_rule, rules_for_primary
from csv_loader import display_titles, load_csv_bytes
from exporter import export_csv, merge_exported_csv_files, verify_export
from format_adapter import SHOPIFY, SUPPLIER, output_suffix, prepare_frame
from pricing import apply_fixed_pricing, build_change_preview, validate_fixed_pricing
from validator import validate_frame


st.set_page_config(page_title="JILL10 PRICING", page_icon="➕", layout="wide", initial_sidebar_state="expanded")

WORKSPACE_TTL_SECONDS = 6 * 60 * 60
MAX_ACTIVE_WORKSPACES = 50
BROWSER_CUSTOM_CATEGORIES_KEY = "jill10-custom-categories-v1"
CATBOT_ASSET = Path(__file__).resolve().parent / "assets" / "j10-catbot.png"
CATBOT_DATA_URL = "data:image/png;base64," + base64.b64encode(CATBOT_ASSET.read_bytes()).decode("ascii")


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
        # Evict empty workspaces (visitors who never uploaded anything, health
        # checks, bots) before touching one that actually holds a batch.
        empty = [key for key, value in store.items() if not any(value.get("files", {}).values())]
        pool = empty or list(store)
        oldest = min(pool, key=lambda key: float(store[key].get("updated", 0)))
        store.pop(oldest, None)


def _upload_name(uploaded: object) -> str:
    return uploaded["name"] if isinstance(uploaded, dict) else uploaded.name


def _upload_bytes(uploaded: object) -> bytes:
    return uploaded["data"] if isinstance(uploaded, dict) else uploaded.getvalue()


@st.cache_data(show_spinner=False, max_entries=32)
def _cached_load_csv_bytes(data: bytes):
    """Parse identical uploaded bytes once across Streamlit page reruns."""
    return load_csv_bytes(data)


def _validated_custom_categories(payload: object) -> dict[str, dict[str, object]]:
    """Validate browser/imported custom categories before trusting them."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("custom categories must be an object")
    validated: dict[str, dict[str, object]] = {}
    built_in_ids = {rule.rule_id.casefold() for rule in CATEGORY_RULES}
    for imported_id, values in payload.items():
        if not isinstance(values, dict):
            raise ValueError("invalid custom category")
        primary = str(values["primary"]).strip()
        name = str(values["name"]).strip()
        minimum = float(values["minimum"])
        maximum = float(values["maximum"])
        rule_id = str(imported_id)
        if (
            primary not in PRIMARY_CATEGORIES
            or not name
            or "::" in name
            or minimum <= 0
            or maximum < minimum
            or rule_id != f"{primary}::{name}"
            or rule_id.casefold() in built_in_ids
        ):
            raise ValueError("invalid custom category")
        keywords = [
            str(value).strip()
            for value in values.get("keywords", [name.lower()])
            if str(value).strip()
        ]
        validated[rule_id] = {
            "primary": primary,
            "name": name,
            "minimum": round(minimum, 2),
            "maximum": round(maximum, 2),
            "keywords": keywords or [name.lower()],
        }
    return validated

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
    .block-container { max-width: 1480px; padding-top: 3.4rem; padding-bottom: 5rem; }
    html, body, [class*="css"] { font-family: "DM Sans", "Noto Sans SC", sans-serif; }
    /* Hide Streamlit's menu/footer/toolbar but KEEP the header itself: the arrow
       that re-opens a collapsed sidebar lives inside it. */
    #MainMenu, footer { visibility: hidden; }
    header[data-testid="stHeader"] { background: transparent; }
    [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] { visibility: hidden; }
    [data-testid="stExpandSidebarButton"], [data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"] { visibility: visible; }

    .hero {
        position: relative; overflow: hidden; padding: 38px 42px; border-radius: 24px;
        background: #15151A; box-shadow: 0 22px 65px rgba(21,21,26,.18); margin-bottom: 18px;
        animation: heroIn .55s cubic-bezier(.2,.8,.2,1) both;
    }
    .hero:before { content:""; position:absolute; width:270px; height:270px; right:8%; top:-170px; background:var(--violet); border-radius:50%; filter:blur(3px); opacity:.65; animation:orbFloat 8s ease-in-out infinite; }
    .hero:after { content:""; position:absolute; width:180px; height:180px; right:-45px; bottom:-105px; background:var(--lime); border-radius:48% 52% 58% 42%; transform:rotate(24deg); animation:shapeTurn 12s ease-in-out infinite alternate; }
    .brandline { position:relative; z-index:1; display:flex; align-items:center; gap:10px; color:#FFF; font-weight:700; font-size:13px; letter-spacing:.08em; }
    .brandmark { display:inline-grid; place-items:center; width:34px; height:34px; border-radius:11px; background:var(--lime); color:#15151A; font-weight:700; transform:rotate(-7deg); letter-spacing:-.05em; transition:transform .25s ease, border-radius .25s ease; }
    .hero:hover .brandmark { transform:rotate(0deg) scale(1.08); border-radius:50%; }
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
    .stage-banner { display:flex; align-items:center; justify-content:space-between; gap:18px; padding:15px 18px; margin:-9px 0 18px; border:1px solid var(--line); border-radius:15px; background:rgba(255,255,255,.78); animation:softIn .35s ease both; }
    .stage-banner-main { display:flex; align-items:center; gap:11px; min-width:0; }
    .stage-pulse { width:10px; height:10px; flex:0 0 auto; border-radius:50%; background:var(--violet); box-shadow:0 0 0 0 rgba(121,92,255,.36); animation:pulse 2s infinite; }
    .stage-banner strong { display:block; color:var(--ink); font-size:14px; }
    .stage-banner span { display:block; color:var(--muted); font-size:12px; margin-top:2px; }
    .stage-count { flex:0 0 auto; padding:7px 11px; border-radius:999px; background:#15151A; color:#FFF !important; font-weight:700; font-size:11px !important; margin:0 !important; }
    .scroll-top { position:fixed; left:50%; bottom:72px; z-index:999; width:66px; height:66px; display:block; transform:translateX(-50%); text-decoration:none !important; filter:drop-shadow(0 12px 15px rgba(21,21,26,.22)); transition:transform .24s cubic-bezier(.2,.8,.2,1),filter .24s ease; cursor:grab; touch-action:none; user-select:none; -webkit-user-drag:none; }
    .scroll-top img { display:block; width:100%; height:100%; object-fit:contain; }
    .scroll-top:hover { transform:translateX(-50%) translateY(-8px) rotate(-2deg) scale(1.06); filter:drop-shadow(0 18px 19px rgba(21,21,26,.29)); }
    .scroll-top:active { transform:translateX(-50%) translateY(-3px) scale(.96); }
    .scroll-top.is-dragging { cursor:grabbing; transform:none !important; transition:none !important; filter:drop-shadow(0 20px 22px rgba(21,21,26,.32)); }
    .j10-assistant-badge { position:absolute; right:-2px; top:-1px; min-width:20px; height:20px; display:grid; place-items:center; padding:0 5px; border:2px solid #FFF; border-radius:999px; background:var(--coral); color:#FFF; font:700 10px/1 "DM Sans",sans-serif; box-shadow:0 5px 12px rgba(255,107,85,.3); }
    .j10-assistant-badge.is-clear { background:#63C174; box-shadow:0 5px 12px rgba(99,193,116,.28); }
    .j10-assistant-panel { position:fixed; z-index:998; width:min(340px,calc(100vw - 24px)); padding:18px; border:1px solid rgba(121,92,255,.22); border-radius:20px; background:rgba(255,255,255,.97); box-shadow:0 22px 70px rgba(21,21,26,.22); opacity:0; visibility:hidden; transform:translateY(8px) scale(.97); transition:opacity .18s ease,transform .18s ease,visibility .18s; backdrop-filter:blur(18px); }
    .j10-assistant-panel.is-open { opacity:1; visibility:visible; transform:none; }
    .j10-assistant-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:13px; }
    .j10-assistant-head strong { display:block; color:var(--ink); font-size:15px; }
    .j10-assistant-head span { display:block; margin-top:3px; color:var(--muted); font-size:11px; line-height:1.5; }
    .j10-assistant-close { width:29px; height:29px; flex:0 0 auto; border:0; border-radius:9px; background:#F1EEF8; color:var(--ink); cursor:pointer; font-size:17px; }
    .j10-assistant-status { display:flex; align-items:center; gap:9px; padding:11px 12px; margin-bottom:12px; border-radius:12px; background:#F6F3FC; color:var(--ink); font-size:12px; font-weight:600; }
    .j10-assistant-status i { width:9px; height:9px; border-radius:50%; background:var(--assistant-color,var(--violet)); box-shadow:0 0 0 5px color-mix(in srgb,var(--assistant-color,var(--violet)) 16%,transparent); }
    .j10-assistant-next { width:100%; min-height:42px; margin-bottom:11px; border:0; border-radius:12px; background:#15151A; color:#FFF; font-weight:700; cursor:pointer; transition:.18s; }
    .j10-assistant-next:hover { background:var(--violet); transform:translateY(-1px); }
    .j10-assistant-nav { display:grid; grid-template-columns:1fr 1fr; gap:7px; margin-bottom:11px; }
    .j10-assistant-nav button,.j10-assistant-undo { min-height:37px; border:1px solid var(--line); border-radius:10px; background:#FFF; color:var(--ink); font-size:12px; font-weight:600; cursor:pointer; transition:.16s; }
    .j10-assistant-nav button:hover,.j10-assistant-undo:not(:disabled):hover { border-color:var(--violet); background:#F6F3FC; }
    .j10-assistant-search { display:grid; grid-template-columns:1fr auto; gap:7px; margin-bottom:9px; }
    .j10-assistant-search input { min-width:0; height:39px; padding:0 11px; border:1px solid var(--line); border-radius:10px; outline:none; color:var(--ink); background:#FFF; }
    .j10-assistant-search input:focus { border-color:var(--violet); box-shadow:0 0 0 3px rgba(121,92,255,.12); }
    .j10-assistant-search button { min-width:58px; border:0; border-radius:10px; background:var(--lime); color:var(--ink); font-weight:700; cursor:pointer; }
    .j10-assistant-search-note { min-height:16px; color:var(--muted); font-size:10px; line-height:1.45; }
    .j10-assistant-footer { display:flex; align-items:center; gap:8px; margin-top:11px; padding-top:11px; border-top:1px solid #EEEAF2; }
    .j10-assistant-undo { width:100%; }
    .j10-assistant-undo:disabled { cursor:not-allowed; opacity:.45; }

    div[data-testid="stFileUploader"] { background:rgba(255,255,255,.88); border:1px solid var(--line); border-radius:18px; padding:13px 18px 5px; }
    div[data-testid="stFileUploaderDropzone"] { border:1px dashed var(--violet); background:rgba(121,92,255,.035); border-radius:14px; }
    div[data-testid="stMetric"] { background:rgba(255,255,255,.85); border:1px solid var(--line); border-radius:16px; padding:17px 18px; box-shadow:0 8px 22px rgba(21,21,26,.04); transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease; }
    div[data-testid="stMetric"]:hover { transform:translateY(-3px); border-color:#BBAEFF; box-shadow:0 14px 30px rgba(21,21,26,.08); }
    div[data-testid="stMetricLabel"] { color:var(--muted); }
    div[data-testid="stMetricValue"] { color:var(--ink); font-size:27px; }
    div[data-testid="stProgress"] > div > div > div { background:linear-gradient(90deg,var(--violet),var(--cyan),var(--lime)); }
    div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:15px; overflow:hidden; background:#FFF; }
    div[data-testid="stAlert"] { border-radius:12px; border-width:1px; }
    div[data-testid="stExpander"] { background:rgba(255,255,255,.82); border:1px solid var(--line); border-radius:15px; transition:border-color .2s ease,box-shadow .2s ease; }
    div[data-testid="stExpander"]:hover { border-color:#C9C0F8; box-shadow:0 10px 28px rgba(21,21,26,.055); }
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
    .st-key-workflow_cards label[data-baseweb="radio"]:has(input:checked):after { content:"当前"; position:absolute; top:8px; right:9px; padding:3px 7px; border-radius:999px; background:var(--lime); color:#15151A; font-size:9px; font-weight:800; letter-spacing:.06em; }
    .st-key-workflow_cards label[data-baseweb="radio"]:has(input:checked) * { color:#FFF !important; }
    .st-key-workflow_cards label[data-baseweb="radio"] p { font-size:14px; font-weight:700; }
    main div[data-testid="stRadio"] > div[role="radiogroup"] label { background:rgba(255,255,255,.88); border:1px solid var(--line); border-radius:16px; padding:16px 20px; min-width:260px; box-shadow:0 8px 22px rgba(21,21,26,.035); transition:.2s; }
    main div[data-testid="stRadio"] > div[role="radiogroup"] label:hover { transform:translateY(-2px); border-color:var(--violet); }
    .stButton>button, .stDownloadButton>button { border-radius:12px; min-height:46px; font-weight:700; transition:transform .18s ease,box-shadow .18s ease; }
    .stButton>button:hover, .stDownloadButton>button:hover { transform:translateY(-2px); box-shadow:0 10px 25px rgba(21,21,26,.12); }
    .stButton>button[kind="primary"], .stDownloadButton>button { background:#15151A; color:#FFF; border:1px solid #15151A; }
    .stButton>button[kind="primary"]:hover, .stDownloadButton>button:hover { background:var(--violet); color:#FFF; border-color:var(--violet); }
    @keyframes heroIn { from{opacity:0;transform:translateY(12px) scale(.992)} to{opacity:1;transform:none} }
    @keyframes softIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:none} }
    @keyframes orbFloat { 0%,100%{transform:translate(0,0) scale(1)} 50%{transform:translate(-24px,18px) scale(1.08)} }
    @keyframes shapeTurn { from{transform:rotate(24deg) translate(0,0)} to{transform:rotate(42deg) translate(-14px,-8px)} }
    @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(121,92,255,.38)} 70%{box-shadow:0 0 0 9px rgba(121,92,255,0)} 100%{box-shadow:0 0 0 0 rgba(121,92,255,0)} }
    @media (prefers-reduced-motion:reduce) { *,*:before,*:after { animation-duration:.01ms !important; animation-iteration-count:1 !important; scroll-behavior:auto !important; } }
    @media(max-width:800px){ .hero{padding:30px 25px}.hero h1{font-size:31px}.stepbar{grid-template-columns:1fr 1fr}.empty-grid{grid-template-columns:1fr}.page-head{align-items:flex-start;flex-direction:column} .st-key-workflow_cards div[role="radiogroup"]{grid-template-columns:1fr 1fr !important} }
    </style>
    <div id="jill10-top"></div>
    <div class="hero">
      <div class="brandline"><span class="brandmark">+10</span>JILL10 PRICING</div>
      <div class="eyebrow">Pricing Workspace</div>
      <h1>产品包批量定价与结果校验</h1>
      <p>系统自动完成品类识别、价格计算和异常检查，并在不改变原始文件结构的前提下生成可直接使用的新产品包。</p>
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

# Custom categories are personal settings, not temporary uploaded-file state.
# Browser localStorage keeps them isolated per user and survives tab/browser
# closure. The existing JSON download remains the portable backup for another
# browser or computer.
try:
    browser_storage = LocalStorage(key="jill10_browser_storage_init") if LocalStorage else None
    browser_custom_categories = (
        browser_storage.getItem(BROWSER_CUSTOM_CATEGORIES_KEY)
        if browser_storage is not None
        else None
    )
except Exception:
    browser_storage = None
    browser_custom_categories = None

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
if not st.session_state.get("browser_custom_categories_loaded", False):
    try:
        persisted_categories = (
            _validated_custom_categories(browser_custom_categories)
            if browser_custom_categories
            else {}
        )
        if persisted_categories:
            # Browser settings win if an old temporary workspace contains an
            # earlier version of the same custom category.
            st.session_state.custom_category_rules.update(persisted_categories)
            workspace["custom_categories"] = dict(st.session_state.custom_category_rules)
            workspace["updated"] = time.time()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        st.session_state.browser_custom_category_warning = True
    st.session_state.browser_custom_categories_loaded = True
if "manual_review_files" not in st.session_state:
    st.session_state.manual_review_files = set(workspace.get("manual_review_files", []))


def _persist_custom_categories() -> None:
    """Save this user's custom categories in their current browser."""
    if browser_storage is None:
        return
    browser_storage.setItem(
        BROWSER_CUSTOM_CATEGORIES_KEY,
        dict(st.session_state.custom_category_rules),
        key="jill10_save_custom_categories",
    )
    # Give the browser component time to commit before an immediate st.rerun.
    time.sleep(0.35)


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
    _persist_custom_categories()
    return str(snapshot["label"])


def _go_to_workflow_stage(stage: str) -> None:
    st.session_state.workflow_stage = stage


def _assistant_batch_status(files: list[object], active_format: str) -> dict[str, object]:
    """Build a compact, read-only batch status for the floating assistant."""
    if not files:
        return {
            "attention": 0,
            "status": "等待上传产品包",
            "detail": "上传 CSV 后，我会提示识别结果和下一步操作。",
            "next_label": "前往上传产品包",
            "next_target": "jill10-upload",
            "color": "#795CFF",
        }

    attention_handles: set[str] = set()
    failed_files = 0
    priced_products = 0
    active_names = {_upload_name(item) for item in files}
    marked_files = active_names & st.session_state.manual_review_files
    for item in files:
        try:
            loaded = _cached_load_csv_bytes(_upload_bytes(item))
            source = prepare_frame(loaded.frame, active_format)
            result = apply_fixed_pricing(
                source,
                st.session_state.learned_category_mappings,
                st.session_state.price_range_overrides,
                st.session_state.product_category_mappings,
                _custom_rule_objects(),
            )
            priced_products += len(result.product_summary)
            attention_handles.update(str(value) for value in result.unresolved_handles)
            if "匹配方式" in result.product_summary.columns and "Handle" in result.product_summary.columns:
                semantic = result.product_summary[
                    result.product_summary["匹配方式"].astype(str).str.contains("语义匹配", regex=False)
                ]
                attention_handles.update(semantic["Handle"].astype(str).tolist())
        except Exception:
            failed_files += 1

    attention = len(attention_handles) + len(marked_files) + failed_files
    if attention:
        return {
            "attention": attention,
            "status": f"发现 {attention} 项需要确认",
            "detail": f"已检查 {len(files)} 个文件、{priced_products} 个商品；未确认项目不会阻止其他文件下载。",
            "next_label": "前往需要纠正的项目",
            "next_target": "jill10-corrections",
            "color": "#FF6B55",
        }
    return {
        "attention": 0,
        "status": "当前批次识别完成",
        "detail": f"{len(files)} 个文件、{priced_products} 个商品均已完成自动定价检查。",
        "next_label": "检查结果并下载",
        "next_target": "jill10-results",
        "color": "#63C174",
    }


def _render_pricing_assistant(status: dict[str, object], current_search: str) -> None:
    history = workspace.setdefault("history", [])
    attention = int(status["attention"])
    badge_text = str(attention) if attention else "✓"
    badge_class = "" if attention else " is-clear"
    undo_disabled = "" if history else " disabled"
    undo_label = f"撤销：{history[-1]['label']}" if history else "暂无可撤销的修改"
    panel_html = f"""
    <a class="scroll-top" href="#" title="拖动可移动；单击打开助手；双击复位" aria-label="可拖动的定价助手">
      <img src="{CATBOT_DATA_URL}" alt="可拖动的定价助手" draggable="false">
      <span class="j10-assistant-badge{badge_class}">{escape(badge_text)}</span>
    </a>
    <section class="j10-assistant-panel" aria-label="JILL10 定价助手">
      <div class="j10-assistant-head"><div><strong>JILL10 定价助手</strong><span>{escape(str(status['detail']))}</span></div><button class="j10-assistant-close" type="button" aria-label="关闭">×</button></div>
      <div class="j10-assistant-status" style="--assistant-color:{escape(str(status['color']))}"><i></i>{escape(str(status['status']))}</div>
      <button class="j10-assistant-next" type="button" data-target="{escape(str(status['next_target']))}">{escape(str(status['next_label']))}</button>
      <div class="j10-assistant-nav">
        <button type="button" data-target="jill10-top">返回顶部</button><button type="button" data-target="jill10-upload">上传区域</button>
        <button type="button" data-target="jill10-results">识别结果</button><button type="button" data-target="jill10-corrections">需要纠正</button>
        <button type="button" data-target="jill10-download">下载区域</button><button type="button" data-target="jill10-top">页面导航</button>
      </div>
      <form class="j10-assistant-search"><input value="{escape(current_search, quote=True)}" placeholder="搜索 Handle、商品或品类"><button type="submit">搜索</button></form>
      <div class="j10-assistant-search-note">搜索会筛选全部已上传产品包；清空内容再搜索即可恢复全部结果。</div>
      <div class="j10-assistant-footer"><button class="j10-assistant-undo" type="button"{undo_disabled}>{escape(undo_label)}</button></div>
    </section>
    """
    st.markdown(panel_html, unsafe_allow_html=True)

    components.html(
        """
        <script>
        (() => {
          const doc = window.parent.document;
          const win = window.parent;
          const bot = doc.querySelector('.scroll-top');
          const panel = doc.querySelector('.j10-assistant-panel');
          if (!bot || !panel || bot.dataset.dragReady === '1') return;
          bot.dataset.dragReady = '1';

          const storageKey = 'jill10-catbot-position-v1';
          const padding = 10;
          let drag = null;
          let suppressClick = false;
          let clickTimer = null;
          const clamp = (value, low, high) => Math.max(low, Math.min(value, high));

          const positionPanel = () => {
            if (!panel.classList.contains('is-open')) return;
            const botRect = bot.getBoundingClientRect();
            const panelRect = panel.getBoundingClientRect();
            let left = botRect.left + botRect.width / 2 - panelRect.width / 2;
            let top = botRect.top - panelRect.height - 12;
            left = clamp(left, 12, Math.max(12, win.innerWidth - panelRect.width - 12));
            if (top < 12) top = Math.min(win.innerHeight - panelRect.height - 12, botRect.bottom + 12);
            panel.style.left = `${left}px`;
            panel.style.top = `${Math.max(12, top)}px`;
          };
          const place = (left, top, save = false) => {
            const maxLeft = Math.max(padding, win.innerWidth - bot.offsetWidth - padding);
            const maxTop = Math.max(padding, win.innerHeight - bot.offsetHeight - padding);
            const x = clamp(left, padding, maxLeft);
            const y = clamp(top, padding, maxTop);
            bot.style.left = `${x}px`; bot.style.top = `${y}px`; bot.style.bottom = 'auto'; bot.style.transform = 'none';
            if (save) { try { win.localStorage.setItem(storageKey, JSON.stringify({left:x, top:y})); } catch (_) {} }
            positionPanel();
          };
          const togglePanel = (force) => {
            const open = typeof force === 'boolean' ? force : !panel.classList.contains('is-open');
            panel.classList.toggle('is-open', open);
            if (open) requestAnimationFrame(positionPanel);
          };

          try {
            const saved = JSON.parse(win.localStorage.getItem(storageKey) || 'null');
            if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) requestAnimationFrame(() => place(saved.left, saved.top));
          } catch (_) {}

          bot.addEventListener('pointerdown', (event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            const rect = bot.getBoundingClientRect();
            drag = {pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,left:rect.left,top:rect.top,moved:false};
            suppressClick = false; bot.classList.add('is-dragging'); bot.setPointerCapture(event.pointerId);
          });
          bot.addEventListener('pointermove', (event) => {
            if (!drag || event.pointerId !== drag.pointerId) return;
            const dx = event.clientX - drag.startX, dy = event.clientY - drag.startY;
            if (Math.hypot(dx,dy) > 4) drag.moved = true;
            place(drag.left + dx, drag.top + dy);
          });
          const finishDrag = (event) => {
            if (!drag || event.pointerId !== drag.pointerId) return;
            suppressClick = drag.moved;
            const rect = bot.getBoundingClientRect();
            bot.classList.remove('is-dragging'); place(rect.left,rect.top,true);
            try { bot.releasePointerCapture(event.pointerId); } catch (_) {}
            drag = null;
          };
          bot.addEventListener('pointerup', finishDrag);
          bot.addEventListener('pointercancel', finishDrag);
          bot.addEventListener('click', (event) => {
            event.preventDefault();
            if (suppressClick) { suppressClick = false; return; }
            clearTimeout(clickTimer);
            clickTimer = setTimeout(() => togglePanel(), 210);
          });
          bot.addEventListener('dblclick', (event) => {
            event.preventDefault(); clearTimeout(clickTimer); togglePanel(false);
            place((win.innerWidth - bot.offsetWidth) / 2, win.innerHeight - bot.offsetHeight - 72, true);
          });

          panel.querySelector('.j10-assistant-close').addEventListener('click', () => togglePanel(false));
          panel.querySelectorAll('[data-target]').forEach((button) => button.addEventListener('click', () => {
            const target = doc.getElementById(button.dataset.target) || doc.getElementById('jill10-results') || doc.getElementById('jill10-top');
            if (target) target.scrollIntoView({behavior:'smooth',block:'start'});
            togglePanel(false);
          }));
          panel.querySelector('.j10-assistant-search').addEventListener('submit', (event) => {
            event.preventDefault();
            const query = event.currentTarget.querySelector('input').value.trim();
            const url = new URL(win.location.href);
            if (query) url.searchParams.set('assistant_search',query); else url.searchParams.delete('assistant_search');
            win.location.href = url.toString();
          });
          const undo = panel.querySelector('.j10-assistant-undo');
          undo.addEventListener('click', () => {
            if (undo.disabled) return;
            const url = new URL(win.location.href); url.searchParams.set('assistant_action','undo'); win.location.href = url.toString();
          });
          doc.addEventListener('pointerdown', (event) => {
            if (panel.classList.contains('is-open') && !panel.contains(event.target) && !bot.contains(event.target)) togglePanel(false);
          });
          win.addEventListener('resize', () => { const rect=bot.getBoundingClientRect(); place(rect.left,rect.top,true); });
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def _render_batch_exports(
    outputs: list[tuple[str, bytes]],
    active_format: str,
    key_prefix: str,
) -> None:
    """Show separate-ZIP and single-merged-CSV downloads side by side."""
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in outputs:
            archive.writestr(name, data)

    merged_bytes, merge_issues = merge_exported_csv_files(outputs)
    download_columns = st.columns(2)
    download_columns[0].download_button(
        f"分别保存：下载 ZIP · {len(outputs)} 个文件",
        data=zip_buffer.getvalue(),
        file_name="正确价格产品包-分开保存.zip",
        mime="application/zip",
        key=f"{key_prefix}_zip_download",
        use_container_width=True,
    )
    merged_name = "全部正确价格产品-Shopify.csv" if active_format == SHOPIFY else "全部正确价格产品.csv"
    if merged_bytes is not None:
        download_columns[1].download_button(
            f"合并保存：下载一个 CSV · {len(outputs)} 个文件",
            data=merged_bytes,
            file_name=merged_name,
            mime="text/csv",
            key=f"{key_prefix}_merged_download",
            use_container_width=True,
        )
        st.caption("合并包只保留一行表头，并按原文件顺序合并所有商品数据；上传店铺后台时直接使用这个 CSV。")
    else:
        download_columns[1].button(
            "当前文件无法安全合并",
            disabled=True,
            key=f"{key_prefix}_merged_disabled",
            use_container_width=True,
        )
        st.warning("合并包未生成：" + "；".join(merge_issues))


assistant_action = str(st.query_params.get("assistant_action", ""))
if assistant_action == "undo":
    st.query_params.pop("assistant_action", None)
    undone = _undo_last_change()
    if undone:
        st.toast(f"已撤销：{undone}", icon="↩️")
    else:
        st.toast("目前没有可以撤销的修改")
    st.rerun()

assistant_search = str(st.query_params.get("assistant_search", "")).strip()

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
        st.caption("新增后会立即参与识别和定价，并自动保存在当前浏览器中；关闭网页后再次打开仍会保留。")
        if st.session_state.pop("browser_custom_category_warning", False):
            st.warning("浏览器里以前保存的自定义品类内容异常，已忽略；你可以重新导入 JSON 备份。")
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
                _persist_custom_categories()
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
                _persist_custom_categories()
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
                    validated_categories = _validated_custom_categories(imported_categories)
                    _record_change(f"导入自定义品类 · {len(validated_categories)} 项")
                    st.session_state.custom_category_rules.update(validated_categories)
                    st.session_state.last_custom_category_import = import_digest
                    workspace["custom_categories"] = dict(st.session_state.custom_category_rules)
                    workspace["updated"] = time.time()
                    _persist_custom_categories()
                    st.toast(f"已导入 {len(validated_categories)} 个二级品类")
                    st.rerun()
                except Exception:
                    st.error("自定义品类文件无法读取或内容不符合要求。")
    file_format = SUPPLIER
    new_uploads = None
    workflow_stage = None
else:
    st.markdown('<div id="jill10-upload"></div>', unsafe_allow_html=True)
    st.markdown('<div class="page-head"><div><div class="section-kicker">Pricing Workspace</div><h2>单页定价工作台</h2></div><p>上传、检查、纠正和下载都在当前页面完成</p></div>', unsafe_allow_html=True)
    workflow_stage = "单页工作台"
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
    new_uploads = st.file_uploader(
        "上传 Shopify CSV" if file_format == SHOPIFY else "上传供应商产品 CSV",
        type=["csv"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key=f"product_csv_uploader_{file_format}",
    )

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
    upload_fingerprint = hashlib.sha256(
        b"".join(item.getvalue() for item in new_uploads)
    ).hexdigest()
    if st.session_state.get("last_upload_feedback") != upload_fingerprint:
        st.session_state.last_upload_feedback = upload_fingerprint
        st.toast(f"已安全保存 {len(new_uploads)} 个产品包", icon="✅")

uploaded_files = list(workspace["files"].get(file_format, []))
assistant_status = _assistant_batch_status(uploaded_files, file_format)
_render_pricing_assistant(assistant_status, assistant_search)

if workflow_stage:
    stage_messages = {
        "① 上传产品包": ("建立本次处理批次", "支持一次上传多个 CSV，文件会保留在当前独立工作区。"),
        "② 检查识别": ("检查自动识别结果", "搜索、浏览商品并将可疑产品包加入纠正步骤。"),
        "③ 纠正异常": ("集中处理需要确认的商品", "未识别和人工标记的项目会集中显示，不影响其他商品。"),
        "④ 下载结果": ("导出已经完成的文件", "可单独下载 CSV，也可将多个结果一次打包下载。"),
        "单页工作台": ("当前批次自动处理", "向下展开产品包即可检查识别、纠正品类并下载结果。"),
    }
    stage_heading, stage_copy = stage_messages[workflow_stage]
    st.markdown(
        f'<div class="stage-banner"><div class="stage-banner-main"><i class="stage-pulse"></i>'
        f'<div><strong>{stage_heading}</strong><span>{stage_copy}</span></div></div>'
        f'<span class="stage-count">{len(uploaded_files)} 个文件</span></div>',
        unsafe_allow_html=True,
    )

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
            loaded_overview = _cached_load_csv_bytes(_upload_bytes(uploaded))
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

if workflow_stage == "单页工作台":
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
            review_loaded = _cached_load_csv_bytes(_upload_bytes(review_upload))
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
    "单页工作台": ("Batch Workspace", "产品包处理结果"),
}
stage_kicker, stage_title = stage_titles.get(workflow_stage, ("Batch Queue", "处理队列"))
st.markdown('<div id="jill10-results"></div><div id="jill10-corrections"></div>', unsafe_allow_html=True)
st.markdown(f'<div class="section-kicker">{stage_kicker}</div><div class="section-title">{stage_title}</div>', unsafe_allow_html=True)
if assistant_search:
    st.info(f'小助手正在全部产品包中搜索“{assistant_search}”。清空小助手搜索框并再次搜索即可恢复全部结果。')
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
        expanded=file_index == 0 or bool(assistant_search),
    ):
        try:
            loaded = _cached_load_csv_bytes(uploaded_data)
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
            if pricing_result.skipped_handles:
                skipped_preview = "、".join(pricing_result.skipped_handles[:5])
                st.warning(
                    f"有 {len(pricing_result.skipped_handles)} 个商品的所有行价格都为空，无法定价，"
                    f"已保持原样：{skipped_preview}"
                    + (" 等" if len(pricing_result.skipped_handles) > 5 else "")
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
                task_result_tab, task_changes_tab = st.tabs(["商品定价结果", "价格字段变化"])
                with task_result_tab:
                    if pricing_result.product_summary.empty:
                        st.info("此产品包没有生成可定价商品。")
                    else:
                        task_visible = pricing_result.product_summary.drop(
                            columns=["区间下限", "区间上限"],
                            errors="ignore",
                        ).reset_index(drop=True)
                        local_task_search = st.text_input(
                            "搜索定价结果",
                            placeholder="输入 Handle、原始分类或识别品类",
                            key=f"task_search_{file_index}",
                        ).strip().casefold()
                        task_search = (assistant_search or local_task_search).strip().casefold()
                        if task_search:
                            task_search_columns = [
                                column for column in ["Handle", "原始分类", "一级品类", "识别品类", "匹配方式"]
                                if column in task_visible.columns
                            ]
                            task_mask = pd.Series(False, index=task_visible.index)
                            for column in task_search_columns:
                                task_mask |= task_visible[column].fillna("").astype(str).str.casefold().str.contains(
                                    task_search, regex=False
                                )
                            task_visible = task_visible[task_mask]
                        st.caption(
                            f"显示 {len(task_visible)} / {len(pricing_result.product_summary)} 个商品。"
                            "重点检查原始分类、识别品类、新售价和新划线价。"
                        )
                        st.dataframe(
                            task_visible,
                            use_container_width=True,
                            hide_index=True,
                            height=min(460, 78 + max(1, len(task_visible)) * 35),
                        )
                with task_changes_tab:
                    task_preview = build_change_preview(source, pricing_result.frame)
                    task_preview.insert(1, "商品名称", display_titles(source).loc[task_preview.index])
                    task_changed_only = st.toggle(
                        "只看价格发生变化的记录",
                        value=True,
                        key=f"task_changed_only_{file_index}",
                    )
                    task_shown = task_preview[task_preview["发生变化"]] if task_changed_only else task_preview
                    st.dataframe(
                        task_shown,
                        use_container_width=True,
                        hide_index=True,
                        height=360,
                    )
                st.caption("如果表格中的品类识别不正确，将此产品包加入第三步后，即可多选错误商品并批量修改品类。")
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
                    export_issues = verify_export(
                        output_bytes,
                        uploaded_data,
                        loaded,
                        pricing_result.frame,
                        file_format,
                        tuple(pricing_result.product_summary["Handle"].astype(str)),
                    )
                    if export_issues:
                        needs_attention += 1
                        st.error("导出文件复核未通过，已阻止下载，避免把错误文件带入店铺。")
                        st.caption("；".join(export_issues))
                        continue
                    completed_outputs.append((output_name, output_bytes))
                    st.caption("✓ 导出复核通过：除价格列外的所有单元格与原文件完全一致，同一商品各变体价格一致。")
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
                    manual_category_search = st.text_input(
                        "搜索需要修改的品类",
                        placeholder="输入原始分类、当前一级品类或识别品类",
                        key=f"manual_category_search_{file_index}",
                    ).strip().casefold()
                    visible_recognized = recognized
                    if manual_category_search:
                        manual_mask = pd.Series(False, index=recognized.index)
                        for column in ("原始分类", "一级品类", "识别品类"):
                            manual_mask |= recognized[column].fillna("").astype(str).str.casefold().str.contains(
                                manual_category_search,
                                regex=False,
                            )
                        visible_recognized = recognized[manual_mask]
                    st.caption(f"当前显示 {len(visible_recognized)} / {len(recognized)} 个原始分类。")
                    if visible_recognized.empty:
                        st.info("没有符合搜索条件的品类。")
                    for _, recognized_row in visible_recognized.iterrows():
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
                details = pd.DataFrame(list(pricing_result.unresolved_details))
                if details.empty:
                    details = pd.DataFrame({
                        "Handle": list(pricing_result.unresolved_handles),
                        "商品名称": list(pricing_result.unresolved_handles),
                        "原始分类": "",
                        "原售价": "",
                        "SKU数量": "",
                    })
                st.warning(
                    f"有 {len(pricing_result.unresolved_handles)} 个商品暂时无法识别。"
                    "这些商品会保持原价格不变，其余商品照常修改并允许下载。"
                    "请在下面为它们选择参考品类，保存后会立即重新定价。"
                )
                # Products with a supplier category are fixed once per category.
                # Products WITHOUT one (empty category) cannot be grouped that
                # way, so they are fixed per product and remembered by Handle.
                unresolved_groups = list(details.groupby("原始分类", sort=True, dropna=False))
                group_rules: dict[str, str] = {}
                for category, product_details in unresolved_groups:
                    category = "" if pd.isna(category) else str(category)
                    by_product = category == ""
                    group_label = "（未提供原始分类）" if by_product else category
                    widget_key = "blank" if by_product else category
                    with st.expander(
                        f"未识别商品 · {group_label}（{len(product_details)} 个）",
                        expanded=True,
                    ):
                        st.dataframe(
                            product_details[["商品名称", "Handle", "原始分类", "原售价", "SKU数量"]],
                            use_container_width=True,
                            hide_index=True,
                            height=min(420, 72 + len(product_details) * 35),
                        )
                        st.caption(
                            "这些商品没有原始分类，下面选择的品类会应用到这张表中的每个商品，并按商品单独记住。"
                            if by_product
                            else "下面选择的参考品类会应用到这张表中的所有商品。"
                        )
                    sample_titles = " ".join(product_details["商品名称"].astype(str).head(12))
                    candidates = rank_similar_categories(f"{category} {sample_titles}".strip(), 3)
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
                    suggested_primary = infer_primary_category(category) if category else None
                    if not suggested_primary and candidates:
                        suggested_primary = candidates[0][0].primary
                    primary_options = ["请选择"] + list(PRIMARY_CATEGORIES)
                    primary_index = primary_options.index(suggested_primary) if suggested_primary in primary_options else 0
                    primary = st.selectbox(
                        f"{group_label}：先选择一级品类",
                        primary_options,
                        index=primary_index,
                        key=f"primary_{file_index}_{widget_key}",
                    )
                    if primary != "请选择":
                        candidate_rules = _rules_for_available_primary(primary)
                        labels = [f"{rule.name}（${rule.minimum:.2f}–${rule.maximum:.2f}）" for rule in candidate_rules]
                        selection = st.selectbox(
                            f"{group_label}：参考哪个具体品类？",
                            ["请选择"] + labels,
                            key=f"rule_{file_index}_{widget_key}",
                        )
                        if selection != "请选择":
                            group_rules[category] = candidate_rules[labels.index(selection)].rule_id
                if st.button(
                    "保存映射并重新处理",
                    key=f"save_map_{file_index}",
                    disabled=len(group_rules) != len(unresolved_groups),
                    use_container_width=True,
                ):
                    _record_change(f"确认未识别商品 · {len(pricing_result.unresolved_handles)} 个")
                    for category, product_details in unresolved_groups:
                        category = "" if pd.isna(category) else str(category)
                        rule_id = group_rules[category]
                        if category:
                            st.session_state.learned_category_mappings[category] = rule_id
                        else:
                            for handle in product_details["Handle"].astype(str):
                                st.session_state.product_category_mappings[handle] = rule_id
                    workspace["mappings"] = dict(st.session_state.learned_category_mappings)
                    workspace["product_mappings"] = dict(st.session_state.product_category_mappings)
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
                    category_group_columns = [
                        column for column in ["原始分类", "一级品类", "识别品类", "价格区间"]
                        if column in pricing_result.product_summary.columns
                    ]
                    category_overview = (
                        pricing_result.product_summary
                        .groupby(category_group_columns, dropna=False)
                        .size()
                        .reset_index(name="商品数量")
                        .sort_values(["一级品类", "识别品类"], kind="stable")
                        .reset_index(drop=True)
                    )
                    with st.expander(
                        f"按品类检查 · 共 {len(category_overview)} 个分类组",
                        expanded=len(category_overview) > 1,
                    ):
                        st.caption("先查看该产品包包含哪些品类及商品数量，再用下面的搜索和筛选快速定位错误品类。")
                        st.dataframe(
                            category_overview,
                            use_container_width=True,
                            hide_index=True,
                            height=min(360, 72 + len(category_overview) * 35),
                        )

                    filter_cols = st.columns([2, 1, 1, 1])
                    local_search_term = filter_cols[0].text_input(
                        "搜索商品或品类",
                        placeholder="输入原始分类、识别品类或 Handle",
                        key=f"product_search_{file_index}",
                    ).strip().casefold()
                    search_term = (assistant_search or local_search_term).strip().casefold()
                    primary_values = sorted(visible["一级品类"].dropna().astype(str).unique().tolist())
                    primary_filter = filter_cols[1].selectbox(
                        "一级品类",
                        ["全部"] + primary_values,
                        key=f"primary_filter_{file_index}",
                    )
                    category_values = sorted(visible["识别品类"].dropna().astype(str).unique().tolist())
                    category_filter = filter_cols[2].selectbox(
                        "识别品类",
                        ["全部"] + category_values,
                        key=f"category_filter_{file_index}",
                    )
                    price_filter = filter_cols[3].selectbox(
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
                    if category_filter != "全部":
                        visible = visible[visible["识别品类"].astype(str) == category_filter]
                    if price_filter == "有折扣":
                        visible = visible[visible["新划线价"] > 0]
                    elif price_filter == "无折扣":
                        visible = visible[visible["新划线价"] <= 0]
                    visible = visible.reset_index(drop=True)
                    st.caption(f"当前显示 {len(visible)} / {len(pricing_result.product_summary)} 个商品。可按品类定位后一次选择全部结果。")
                    if visible.empty:
                        st.info("没有符合当前搜索或筛选条件的商品。")
                        selection_event = None
                        select_all_visible = False
                    else:
                        select_all_visible = st.checkbox(
                            f"全选当前搜索和筛选出的 {len(visible)} 个商品，进行批量纠正",
                            key=f"select_all_visible_{file_index}",
                        )
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
                    if select_all_visible:
                        selected_items = visible.copy()
                    elif selected_rows:
                        selected_items = visible.iloc[[int(index) for index in selected_rows]].copy()
                    else:
                        selected_items = pd.DataFrame()
                    if not selected_items.empty:
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
                export_issues = verify_export(
                    output_bytes,
                    uploaded_data,
                    loaded,
                    pricing_result.frame,
                    file_format,
                    tuple(pricing_result.product_summary["Handle"].astype(str)),
                )
                if export_issues:
                    needs_attention += 1
                    st.error("导出文件复核未通过，已阻止下载，避免把错误文件带入店铺。")
                    st.caption("；".join(export_issues))
                    continue
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
                    '<p>导出复核已经通过，可以直接下载此产品包。</p></div>',
                    unsafe_allow_html=True,
                )
                st.download_button(
                    f"下载 {output_name}",
                    data=output_bytes,
                    file_name=output_name,
                    mime="text/csv",
                    key=f"single_page_download_{file_index}",
                    use_container_width=True,
                )
        except Exception as exc:
            needs_attention += 1
            st.error(f"处理失败：{exc}")

if workflow_stage == "② 检查识别":
    queue_cols[1].metric("识别完成", max(0, len(uploaded_files) - needs_attention))
    queue_cols[2].metric("需要确认", needs_attention)
    st.markdown("---")
    bottom_navigation = st.columns([1, 1])
    current_upload_names = {_upload_name(uploaded) for uploaded in uploaded_files}
    manually_marked_count = len(current_upload_names & st.session_state.manual_review_files)
    correction_count = max(needs_attention, manually_marked_count)
    if correction_count:
        bottom_navigation[0].button(
            f"前往 ③ 纠正异常 · {correction_count} 个产品包",
            type="primary",
            use_container_width=True,
            on_click=_go_to_workflow_stage,
            args=("③ 纠正异常",),
        )
        bottom_navigation[1].caption("已自动发现异常或存在你人工标记的产品包。")
    else:
        bottom_navigation[0].button(
            "无需纠正，前往 ④ 下载结果",
            type="primary",
            use_container_width=True,
            on_click=_go_to_workflow_stage,
            args=("④ 下载结果",),
        )
        bottom_navigation[1].caption("当前批次全部识别并通过价格校验。")
else:
    queue_cols[1].metric("已准备", len(completed_outputs))
    queue_cols[2].metric("待处理", needs_attention)

if workflow_stage == "单页工作台":
    st.markdown('<div id="jill10-download"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-kicker">Batch Export</div><div class="section-title">全部处理结果</div>', unsafe_allow_html=True)
    if completed_outputs:
        st.info("你可以选择保留多个独立产品包的 ZIP，也可以把全部正确结果合并为一个 CSV 产品包。ZIP 上传后台前必须先解压；合并 CSV 可以直接上传。")
        _render_batch_exports(completed_outputs, file_format, "single_page_batch")
    else:
        st.info("目前没有通过校验、可以下载的产品包。请展开上面的文件查看提示并完成确认。")

if workflow_stage == "④ 下载结果":
    st.markdown('<div id="jill10-download"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-kicker">Batch Export</div><div class="section-title">批量导出</div>', unsafe_allow_html=True)
    if completed_outputs:
        st.info("你可以选择保留多个独立产品包的 ZIP，也可以把全部正确结果合并为一个 CSV 产品包。ZIP 上传后台前必须先解压；合并 CSV 可以直接上传。")
        _render_batch_exports(completed_outputs, file_format, "stage_batch")
    else:
        st.info("目前没有可以下载的文件，请返回“③ 纠正异常”完成确认。")
elif workflow_stage == "③ 纠正异常":
    st.markdown("---")
    correction_navigation = st.columns([1, 1])
    correction_navigation[0].button(
        "返回 ② 检查识别",
        use_container_width=True,
        on_click=_go_to_workflow_stage,
        args=("② 检查识别",),
    )
    correction_navigation[1].button(
        "完成纠正，前往 ④ 下载结果",
        type="primary",
        use_container_width=True,
        on_click=_go_to_workflow_stage,
        args=("④ 下载结果",),
    )

if workflow_stage in {"③ 纠正异常", "单页工作台"} and st.session_state.learned_category_mappings:
    st.download_button(
        "保存品类映射文件",
        data=json.dumps(st.session_state.learned_category_mappings, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="category-mappings.json",
        mime="application/json",
    )
