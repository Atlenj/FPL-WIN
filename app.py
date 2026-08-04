import streamlit as st
import pandas as pd
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import plotly.express as px
import plotly.graph_objects as go
import json
from typing import Optional, Dict, List, Any

# =============================================================================
# CONFIG & CONSTANTS
# =============================================================================
PAGE_TITLE = "PL-Kameratene"
FPL_BASE = "https://fantasy.premierleague.com/api"
DEFAULT_MANAGER_ID = "475093"
MAX_GW_HORIZON = 10
CACHE_TTL = 3600

XGI_WEIGHT = {"GKP": 0.0, "DEF": 0.85, "MID": 1.35, "FWD": 1.55}
FDR_WEIGHT = 0.07
FORM_WEIGHT = 0.18
MINUTES_THRESHOLD = 60.0
EP_BLEND = 0.55
TEAM_STRENGTH_WEIGHT = 0.04

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

FDR_COLORS = {
    1: ("#00FF7F", "#000000"),
    2: ("#00BFFF", "#000000"),
    3: ("#E0E0E0", "#000000"),
    4: ("#FF8C00", "#FFFFFF"),
    5: ("#FF4500", "#FFFFFF"),
}

LEGAL_FORMATIONS = [
    (3, 4, 3), (3, 5, 2), (4, 3, 3), (4, 4, 2), (4, 5, 1), (5, 3, 2), (5, 4, 1)
]

STATUS_MAP = {
    "a": ("✅", "Available"),
    "d": ("⚠️", "Doubtful"),
    "i": ("🚑", "Injured"),
    "s": ("🔴", "Suspended"),
    "u": ("❓", "Unavailable"),
    "n": ("❌", "Not available"),
}

# =============================================================================
# PAGE CONFIG & THEME
# =============================================================================
st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main { background-color: #0E1117; color: #FFFFFF; }
    .stMetric {
        background-color: #1E222D;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #2B313E;
    }
    div[data-testid="stSidebar"] {
        background-color: #161922;
        border-right: 1px solid #2B313E;
    }
    div[data-testid="stSidebar"] button[kind="tertiary"] {
        padding: 5px 0px !important;
        text-align: left !important;
        justify-content: flex-start !important;
    }
    div[data-testid="stSidebar"] button[kind="tertiary"] p {
        font-size: 28px !important;
        font-weight: 900 !important;
        color: #00FF7F !important;
        letter-spacing: -0.5px !important;
        line-height: 1.2 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# SESSION STATE
# =============================================================================
defaults = {
    "menu_selection": "📊 Dashboard Overview",
    "bank_balance": 0.0,
    "custom_squad_ids": None,
    "planned_transfers": [],
    "free_transfers": 1,
    "manager_meta": {},
    "use_official_squad": True,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =============================================================================
# HTTP HELPERS
# =============================================================================
def make_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update(HEADERS)
    return session

SESSION = make_session()

@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading FPL bootstrap…")
def load_fpl_bootstrap() -> Optional[dict]:
    try:
        r = SESSION.get(f"{FPL_BASE}/bootstrap-static/", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Bootstrap fetch failed: {e}")
        return None

@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading fixtures…")
def load_fpl_fixtures() -> list:
    try:
        r = SESSION.get(f"{FPL_BASE}/fixtures/", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

@st.cache_data(ttl=300)
def fetch_entry(manager_id: str) -> Optional[dict]:
    try:
        r = SESSION.get(f"{FPL_BASE}/entry/{manager_id}/", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

@st.cache_data(ttl=300)
def fetch_entry_history(manager_id: str) -> Optional[dict]:
    try:
        r = SESSION.get(f"{FPL_BASE}/entry/{manager_id}/history/", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

@st.cache_data(ttl=300)
def fetch_user_picks(manager_id: str, gw: int) -> Optional[dict]:
    for try_gw in (gw, max(1, gw - 1)):
        try:
            r = SESSION.get(f"{FPL_BASE}/entry/{manager_id}/event/{try_gw}/picks/", timeout=10)
            if r.status_code == 200:
                return r.json()
        except Exception:
            continue
    return None

# =============================================================================
# DATA LOADING & PROCESSING
# =============================================================================
raw_data = load_fpl_bootstrap()
fixtures_data = load_fpl_fixtures()

if not raw_data:
    st.error("⚠️ Failed to load data from official FPL API. Please refresh later.")
    st.stop()

players_df = pd.DataFrame(raw_data["elements"])
teams_df = pd.DataFrame(raw_data["teams"])
positions_df = pd.DataFrame(raw_data["element_types"])
events_df = pd.DataFrame(raw_data["events"])

current_gw = 1
next_gw = 1
for _, event in events_df.iterrows():
    if event.get("is_current"):
        current_gw = int(event["id"])
        next_gw = current_gw
        break
    if event.get("is_next"):
        next_gw = int(event["id"])
        current_gw = max(1, next_gw - 1)
        break

team_map = dict(zip(teams_df["id"], teams_df["name"]))
team_short_map = dict(zip(teams_df["id"], teams_df["short_name"]))
pos_map = dict(zip(positions_df["id"], positions_df["singular_name_short"]))

team_att_home = dict(zip(teams_df["id"], teams_df.get("strength_attack_home", 3)))
team_att_away = dict(zip(teams_df["id"], teams_df.get("strength_attack_away", 3)))
team_def_home = dict(zip(teams_df["id"], teams_df.get("strength_defence_home", 3)))
team_def_away = dict(zip(teams_df["id"], teams_df.get("strength_defence_away", 3)))

players_df["team_name"] = players_df["team"].map(team_map)
players_df["team_short"] = players_df["team"].map(team_short_map)
players_df["position"] = players_df["element_type"].map(pos_map)
players_df["now_cost"] = players_df["now_cost"] / 10.0
players_df["selected_by_percent"] = pd.to_numeric(players_df["selected_by_percent"], errors="coerce").fillna(0.0)

for col in [
    "expected_goals", "expected_assists", "expected_goal_involvements",
    "expected_goals_conceded", "minutes", "ep_next", "ep_this",
    "chance_of_playing_next_round", "form", "points_per_game",
    "cost_change_event", "cost_change_start",
]:
    players_df[col] = pd.to_numeric(players_df.get(col, 0), errors="coerce").fillna(0.0)

players_df["games_played"] = (players_df["minutes"] / 90.0).clip(lower=0.5)
players_df["avg_minutes"] = players_df["minutes"] / players_df["games_played"]
players_df["xgi_p90"] = players_df["expected_goal_involvements"] / players_df["games_played"]
players_df["status"] = players_df.get("status", "a").fillna("a")
players_df["news"] = players_df.get("news", "").fillna("")

def status_badge(row):
    code = row["status"]
    icon, label = STATUS_MAP.get(code, ("❓", code))
    chance = row["chance_of_playing_next_round"]
    if code == "a" and 0 < chance < 75:
        return f"⚠️ {int(chance)}%"
    return f"{icon} {label}" if code != "a" else "✅"

players_df["status_badge"] = players_df.apply(status_badge, axis=1)

def price_flag(val):
    if val > 0:
        return f"⬆️ +{val/10:.1f}"
    if val < 0:
        return f"⬇️ {val/10:.1f}"
    return "–"

players_df["price_change"] = players_df["cost_change_event"].apply(price_flag)

players_df["display_label"] = (
    players_df["web_name"] + " (" + players_df["team_short"] + ") – £" + players_df["now_cost"].astype(str) + "m"
)

def get_player_photo_url(photo_code: str) -> str:
    if not photo_code or not isinstance(photo_code, str):
        return "https://resources.premierleague.com/premierleague/photos/players/110x140/Photo-Missing.png"
    code = photo_code.replace(".jpg", "").replace(".png", "")
    return f"https://resources.premierleague.com/premierleague/photos/players/110x140/p{code}.png"

players_df["photo"] = players_df.get("photo", "")
players_df["photo_url"] = players_df["photo"].apply(get_player_photo_url)

team_fixtures: Dict[int, Dict[int, int]] = {}
team_fixture_details: Dict[int, Dict[int, dict]] = {}

for f in fixtures_data:
    gw = f.get("event")
    if not gw:
        continue
    h, a = f["team_h"], f["team_a"]
    team_fixtures.setdefault(h, {})[gw] = f["team_h_difficulty"]
    team_fixtures.setdefault(a, {})[gw] = f["team_a_difficulty"]
    team_fixture_details.setdefault(h, {})[gw] = {
        "opponent": team_short_map.get(a, "UNK"), "venue": "H",
        "fdr": f["team_h_difficulty"], "opp_id": a,
    }
    team_fixture_details.setdefault(a, {})[gw] = {
        "opponent": team_short_map.get(h, "UNK"), "venue": "A",
        "fdr": f["team_a_difficulty"], "opp_id": h,
    }

def get_next_fixture(team_id: int, from_gw: int) -> str:
    for gw in range(from_gw, 39):
        meta = team_fixture_details.get(team_id, {}).get(gw)
        if meta:
            return f"{meta['opponent']} ({meta['venue']})"
    return "–"

# =============================================================================
# IMPROVED xP MODEL
# =============================================================================
def compute_xp_matrix(df: pd.DataFrame, max_gw: int = MAX_GW_HORIZON) -> pd.DataFrame:
    out = df.copy()
    base_ep = out["ep_next"].fillna(0.0)
    xgi_bonus = out["position"].map(XGI_WEIGHT).fillna(0.0) * out["xgi_p90"]
    form_bonus = out["form"].fillna(0.0) * FORM_WEIGHT
    blended = EP_BLEND * base_ep + (1 - EP_BLEND) * (base_ep + xgi_bonus) + form_bonus

    mins_scale = (out["avg_minutes"] / MINUTES_THRESHOLD).clip(0.2, 1.0)
    chance = out["chance_of_playing_next_round"].replace(0, 100) / 100.0
    chance = chance.fillna(1.0).clip(0.15, 1.0)
    status_pen = out["status"].map({"a": 1.0, "d": 0.7, "i": 0.15, "s": 0.1, "u": 0.2, "n": 0.1}).fillna(1.0)
    scale = mins_scale * chance * status_pen
    unadj = blended * scale

    for gw in range(1, max_gw + 1):
        fdr_series = out["team"].map(lambda t: team_fixtures.get(t, {}).get(gw, 3))
        fdr_mod = 1.0 + (3 - fdr_series) * FDR_WEIGHT

        def strength_mod(row):
            tid = row["team"]
            meta = team_fixture_details.get(tid, {}).get(gw)
            if not meta:
                return 1.0
            opp = meta["opp_id"]
            venue = meta["venue"]
            if row["position"] in ["MID", "FWD"]:
                my_att = team_att_home.get(tid, 3) if venue == "H" else team_att_away.get(tid, 3)
                opp_def = team_def_away.get(opp, 3) if venue == "H" else team_def_home.get(opp, 3)
                return 1.0 + (my_att - opp_def) * TEAM_STRENGTH_WEIGHT * 0.15
            else:
                my_def = team_def_home.get(tid, 3) if venue == "H" else team_def_away.get(tid, 3)
                opp_att = team_att_away.get(opp, 3) if venue == "H" else team_att_home.get(opp, 3)
                return 1.0 + (my_def - opp_att) * TEAM_STRENGTH_WEIGHT * 0.12

        strength = out.apply(strength_mod, axis=1)
        out[f"GW{gw}_xP"] = (unadj * fdr_mod * strength).clip(lower=0).round(2)
    return out

players_df = compute_xp_matrix(players_df)

def ownership_risk(row):
    if row["selected_by_percent"] < 15:
        return ""
    fdrs = [team_fixtures.get(row["team"], {}).get(g, 3) for g in range(next_gw, next_gw + 3)]
    avg = np.mean(fdrs) if fdrs else 3
    return "⚠️ Rank risk" if avg >= 3.7 else ""

players_df["own_risk"] = players_df.apply(ownership_risk, axis=1)

# =============================================================================
# SIDEBAR
# =============================================================================
if st.sidebar.button("⚽ PL-Kameratene", type="tertiary", use_container_width=True):
    st.session_state.menu_selection = "📊 Dashboard Overview"
    st.rerun()

st.sidebar.markdown(f"**Current / Next GW:** {current_gw} → {next_gw}")

selected_gw_label = st.sidebar.selectbox(
    "🎯 Target Gameweek",
    options=[f"GW{i}" for i in range(1, MAX_GW_HORIZON + 1)],
    index=min(max(next_gw - 1, 0), MAX_GW_HORIZON - 1),
)
selected_gw_col = f"{selected_gw_label}_xP"
selected_gw_num = int(selected_gw_label.replace("GW", ""))
players_df["xP"] = players_df[selected_gw_col]

menu_options = [
    "📊 Dashboard Overview",
    "🛡️ My Squad & Pitch View",
    "🔄 Transfer Planner",
    "💡 Transfer Recommendations",
    "📅 Fixture Analyzer",
    "🔍 Player Explorer & Differentials",
    "🎰 Chip Simulator",
]
menu = st.sidebar.radio(
    "Navigation",
    options=menu_options,
    index=menu_options.index(st.session_state.menu_selection) if st.session_state.menu_selection in menu_options else 0,
    key="nav_radio",
)
st.session_state.menu_selection = menu

st.sidebar.markdown("---")
manager_id_input = st.sidebar.text_input("FPL Manager ID", value=DEFAULT_MANAGER_ID)
use_manual = st.sidebar.checkbox("🛠️ Manual / Pre-Season Builder", value=not st.session_state.use_official_squad)

if st.sidebar.button("🔄 Reset to Official Picks"):
    st.session_state.custom_squad_ids = None
    st.session_state.use_official_squad = True
    st.session_state.planned_transfers = []
    st.rerun()

# Save / Load
st.sidebar.markdown("### 💾 Squad Save / Load")
if st.session_state.custom_squad_ids:
    squad_json = json.dumps({"ids": st.session_state.custom_squad_ids, "bank": st.session_state.bank_balance})
    st.sidebar.download_button("⬇️ Download current squad", squad_json, file_name="plk_squad.json")

uploaded = st.sidebar.file_uploader("⬆️ Load squad JSON", type="json")
if uploaded:
    try:
        data = json.load(uploaded)
        st.session_state.custom_squad_ids = data.get("ids")
        st.session_state.bank_balance = float(data.get("bank", 0.0))
        st.sidebar.success("Squad loaded!")
        st.rerun()
    except Exception:
        st.sidebar.error("Invalid JSON")

entry = fetch_entry(manager_id_input) if manager_id_input else None
history = fetch_entry_history(manager_id_input) if manager_id_input else None
picks_data = fetch_user_picks(manager_id_input, current_gw) if manager_id_input else None

if entry:
    bank_raw = entry.get("last_deadline_bank") or 0
    value_raw = entry.get("last_deadline_value") or 0
    st.session_state.manager_meta = {
        "name": f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip(),
        "team_name": entry.get("name", ""),
        "overall_rank": entry.get("summary_overall_rank"),
        "overall_points": entry.get("summary_overall_points"),
        "last_deadline_bank": bank_raw / 10.0,
        "last_deadline_value": value_raw / 10.0,
    }
    if picks_data and "entry_history" in picks_data:
        eh = picks_data["entry_history"]
        bank = (eh.get("bank") or bank_raw) / 10.0
        st.session_state.bank_balance = bank
    else:
        st.session_state.bank_balance = st.session_state.manager_meta["last_deadline_bank"]

chips_used = []
if history and "chips" in history:
    chips_used = [c.get("name") for c in history["chips"]]

st.sidebar.markdown("---")
if entry:
    st.sidebar.caption(
        f"**{st.session_state.manager_meta.get('name', 'Manager')}**  \n"
        f"{st.session_state.manager_meta.get('team_name', '')}  \n"
        f"OR: {st.session_state.manager_meta.get('overall_rank', '–')}  \n"
        f"Pts: {st.session_state.manager_meta.get('overall_points', '–')}"
    )
    if chips_used:
        st.sidebar.caption("Chips used: " + ", ".join(chips_used))

# =============================================================================
# PITCH VISUALIZER
# =============================================================================
def generate_fpl_pitch(starting_11_df, bench_df, captain_id, vice_id=None, target_gw=1):
    fig = go.Figure()
    fig.add_shape(type="rect", x0=0, y0=0, x1=100, y1=130, fillcolor="#2d8a4e", line=dict(width=0), layer="below")
    fig.add_shape(type="rect", x0=2, y0=4, x1=98, y1=126, line=dict(color="white", width=2.5), fillcolor="rgba(0,0,0,0)")
    fig.add_shape(type="line", x0=2, y0=65, x1=98, y1=65, line=dict(color="white", width=2))
    fig.add_shape(type="circle", x0=42, y0=55, x1=58, y1=75, line=dict(color="white", width=2))
    fig.add_shape(type="circle", x0=49.2, y0=64.2, x1=50.8, y1=65.8, fillcolor="white", line=dict(width=0))
    fig.add_shape(type="rect", x0=22, y0=104, x1=78, y1=126, line=dict(color="white", width=2))
    fig.add_shape(type="rect", x0=36, y0=116, x1=64, y1=126, line=dict(color="white", width=2))
    fig.add_shape(type="rect", x0=22, y0=4, x1=78, y1=26, line=dict(color="white", width=2))
    fig.add_shape(type="rect", x0=36, y0=4, x1=64, y1=14, line=dict(color="white", width=2))
    fig.add_shape(type="rect", x0=42, y0=126, x1=58, y1=129, line=dict(color="white", width=2))
    fig.add_shape(type="rect", x0=42, y0=1, x1=58, y1=4, line=dict(color="white", width=2))

    pos_y = {"GKP": 18, "DEF": 42, "MID": 72, "FWD": 102}

    def add_player_card(x, y, player, is_bench=False, bench_label=None):
        pid = player["id"]
        is_c = pid == captain_id
        is_v = vice_id is not None and pid == vice_id
        photo = player.get("photo_url") or get_player_photo_url(player.get("photo", ""))
        fixture = get_next_fixture(player["team"], target_gw)
        size = 0.085 if not is_bench else 0.065
        fig.add_layout_image(dict(
            source=photo, x=x - size/2, y=y + size*0.55,
            sizex=size, sizey=size*1.25, xref="x", yref="y", sizing="contain", layer="above"
        ))
        if is_c or is_v:
            badge = "C" if is_c else "V"
            fig.add_annotation(
                x=x + size*0.38, y=y + size*0.9, text=f"<b>{badge}</b>",
                showarrow=False, font=dict(size=11, color="#000"),
                bgcolor="#FFD700" if is_c else "#00BFFF", borderpad=2, bordercolor="#000", borderwidth=1
            )
        fig.add_annotation(
            x=x, y=y - 0.04 if not is_bench else y - 0.035,
            text=f"<b>{player['web_name']}</b><br><span style='font-size:10px;color:#333'>{fixture}</span>",
            showarrow=False, font=dict(size=11, color="#111"), align="center",
            bgcolor="rgba(255,255,255,0.92)", bordercolor="#ccc", borderwidth=1, borderpad=3
        )
        if is_bench and bench_label:
            fig.add_annotation(x=x, y=y + 0.12, text=f"<span style='font-size:9px;color:#aaa'>{bench_label}</span>", showarrow=False)

    for pos, y_val in pos_y.items():
        pos_players = starting_11_df[starting_11_df["position"] == pos]
        n = len(pos_players)
        if n == 0:
            continue
        xs = np.linspace(12, 88, n) if n > 1 else [50]
        for i, (_, pl) in enumerate(pos_players.iterrows()):
            add_player_card(xs[i], y_val, pl)

    if not bench_df.empty:
        bench_ordered = bench_df.copy()
        if "squad_order" in bench_ordered.columns:
            bench_ordered = bench_ordered.sort_values("squad_order")
        else:
            bench_ordered["pos_rank"] = bench_ordered["position"].map({"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3})
            bench_ordered = bench_ordered.sort_values(["pos_rank", "xP"], ascending=[True, False])
        labels = ["GKP" if pl["position"] == "GKP" else f"{i}. {pl['position']}" for i, (_, pl) in enumerate(bench_ordered.iterrows())]
        xs_b = np.linspace(15, 85, len(bench_ordered))
        for i, (_, pl) in enumerate(bench_ordered.iterrows()):
            add_player_card(xs_b[i], -8, pl, is_bench=True, bench_label=labels[i])

    fig.update_layout(
        xaxis=dict(range=[-2, 102], showgrid=False, zeroline=False, showticklabels=False, fixedrange=True),
        yaxis=dict(range=[-18, 135], showgrid=False, zeroline=False, showticklabels=False, fixedrange=True, scaleanchor="x", scaleratio=1.15),
        height=780, margin=dict(l=10, r=10, t=20, b=10),
        plot_bgcolor="#1a0a2e", paper_bgcolor="#1a0a2e",
    )
    fig.add_annotation(x=50, y=132, text="<b>PL-Kameratene</b>  ·  Pitch View", showarrow=False, font=dict(size=14, color="#ccc"))
    return fig

def select_xi_with_formation(squad_df, xp_col="xP", formation=None):
    """Select starting XI. If formation is given as (DEF, MID, FWD) it forces that shape."""
    if squad_df.empty or len(squad_df) < 11:
        return squad_df, pd.DataFrame()

    gkp = squad_df[squad_df["position"] == "GKP"].sort_values(xp_col, ascending=False)
    defs = squad_df[squad_df["position"] == "DEF"].sort_values(xp_col, ascending=False)
    mids = squad_df[squad_df["position"] == "MID"].sort_values(xp_col, ascending=False)
    fwds = squad_df[squad_df["position"] == "FWD"].sort_values(xp_col, ascending=False)

    if formation is None:
        # Auto – best legal formation by xP
        best_score = -1
        best_xi = None
        for n_def, n_mid, n_fwd in LEGAL_FORMATIONS:
            if len(defs) < n_def or len(mids) < n_mid or len(fwds) < n_fwd or len(gkp) < 1:
                continue
            xi = pd.concat([gkp.head(1), defs.head(n_def), mids.head(n_mid), fwds.head(n_fwd)])
            score = xi[xp_col].sum()
            if score > best_score:
                best_score = score
                best_xi = xi
        if best_xi is None:
            best_xi = squad_df.sort_values(xp_col, ascending=False).head(11)
    else:
        n_def, n_mid, n_fwd = formation
        if (len(defs) < n_def or len(mids) < n_mid or len(fwds) < n_fwd or len(gkp) < 1):
            # Not enough players – fall back to auto
            return select_xi_with_formation(squad_df, xp_col, formation=None)
        best_xi = pd.concat([
            gkp.head(1),
            defs.head(n_def),
            mids.head(n_mid),
            fwds.head(n_fwd),
        ])

    bench = squad_df[~squad_df["id"].isin(best_xi["id"])]
    return best_xi, bench

# =============================================================================
# DASHBOARD
# =============================================================================
if menu == "📊 Dashboard Overview":
    st.title(f"📊 PL-Kameratene Dashboard ({selected_gw_label})")

    cols = st.columns(4)
    for pos, col, emoji in zip(["GKP", "DEF", "MID", "FWD"], cols, ["🧤", "🛡️", "⚙️", "🎯"]):
        top = players_df[players_df["position"] == pos].sort_values("xP", ascending=False).iloc[0]
        col.metric(f"{emoji} Top {pos}", top["web_name"], f"{top['xP']} pts")

    st.markdown("---")
    st.subheader(f"👑 Best Captains — {selected_gw_label}")
    captains = players_df.sort_values("xP", ascending=False).head(12)[
        ["web_name", "position", "team_short", "now_cost", "selected_by_percent", "xP", "status_badge", "own_risk"]
    ].copy()
    captains["Capt xP"] = (captains["xP"] * 2).round(1)
    captains = captains[["web_name", "position", "team_short", "now_cost", "selected_by_percent", "xP", "Capt xP", "status_badge", "own_risk"]]
    captains.columns = ["Player", "Pos", "Team", "Price", "Own%", "xP", "Capt xP", "Status", "Risk"]
    st.dataframe(captains, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader(f"🚀 Top 15 Projected Scorers — {selected_gw_label}")
    top_15 = players_df.sort_values("xP", ascending=False).head(15).copy()
    fig = px.bar(
        top_15, x="web_name", y="xP", color="position", text="xP", template="plotly_dark",
        color_discrete_map={"GKP": "#FFD700", "DEF": "#00BFFF", "MID": "#00FF7F", "FWD": "#FF4500"},
    )
    fig.update_traces(texttemplate="%{text}", textposition="outside")
    fig.update_layout(height=420)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("📈 Price Changes (this GW)")
    movers = players_df[players_df["cost_change_event"] != 0].sort_values("cost_change_event", ascending=False)
    if not movers.empty:
        show_m = movers[["web_name", "team_short", "now_cost", "price_change", "selected_by_percent"]].head(20)
        show_m.columns = ["Player", "Team", "Price", "Change", "Own%"]
        st.dataframe(show_m, use_container_width=True, hide_index=True)
    else:
        st.info("No price changes recorded yet this gameweek.")

# =============================================================================
# SQUAD & PITCH VIEW  (with Formation selector)
# =============================================================================
elif menu == "🛡️ My Squad & Pitch View":
    st.title("🛡️ My Squad, Bench & Pitch View")

    official_ids = [p["element"] for p in picks_data.get("picks", [])] if picks_data else []

    if use_manual or not official_ids:
        st.info("💡 Manual / Pre-Season mode — pick your 15-man squad.")
        gkps = players_df[players_df["position"] == "GKP"].sort_values("now_cost")
        defs = players_df[players_df["position"] == "DEF"].sort_values("now_cost")
        mids = players_df[players_df["position"] == "MID"].sort_values("now_cost")
        fwds = players_df[players_df["position"] == "FWD"].sort_values("now_cost")

        default_gkp = gkps.head(2)["id"].tolist()
        default_def = defs.head(5)["id"].tolist()
        default_mid = mids.head(5)["id"].tolist()
        default_fwd = fwds.head(3)["id"].tolist()

        if st.session_state.custom_squad_ids and len(st.session_state.custom_squad_ids) == 15:
            defaults_ids = st.session_state.custom_squad_ids
        else:
            defaults_ids = default_gkp + default_def + default_mid + default_fwd

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown("### 🧤 GKP (2)")
            sel_gkp = st.multiselect(
                "GKP", options=gkps["id"].tolist(),
                default=[i for i in defaults_ids if i in gkps["id"].values][:2],
                format_func=lambda x: gkps.loc[gkps["id"] == x, "display_label"].values[0],
                max_selections=2, key="ms_gkp",
            )
        with c2:
            st.markdown("### 🛡️ DEF (5)")
            sel_def = st.multiselect(
                "DEF", options=defs["id"].tolist(),
                default=[i for i in defaults_ids if i in defs["id"].values][:5],
                format_func=lambda x: defs.loc[defs["id"] == x, "display_label"].values[0],
                max_selections=5, key="ms_def",
            )
        with c3:
            st.markdown("### ⚙️ MID (5)")
            sel_mid = st.multiselect(
                "MID", options=mids["id"].tolist(),
                default=[i for i in defaults_ids if i in mids["id"].values][:5],
                format_func=lambda x: mids.loc[mids["id"] == x, "display_label"].values[0],
                max_selections=5, key="ms_mid",
            )
        with c4:
            st.markdown("### 🎯 FWD (3)")
            sel_fwd = st.multiselect(
                "FWD", options=fwds["id"].tolist(),
                default=[i for i in defaults_ids if i in fwds["id"].values][:3],
                format_func=lambda x: fwds.loc[fwds["id"] == x, "display_label"].values[0],
                max_selections=3, key="ms_fwd",
            )

        all_ids = sel_gkp + sel_def + sel_mid + sel_fwd
        if len(all_ids) == 15:
            st.session_state.custom_squad_ids = all_ids
        full_squad = players_df[players_df["id"].isin(all_ids)].copy()
    else:
        ids = st.session_state.custom_squad_ids or official_ids
        full_squad = players_df[players_df["id"].isin(ids)].copy()
        if picks_data and not st.session_state.custom_squad_ids:
            order = {p["element"]: p["position"] for p in picks_data["picks"]}
            full_squad["squad_order"] = full_squad["id"].map(order)
            full_squad = full_squad.sort_values("squad_order")

    if len(full_squad) >= 11:
        # ---------- Formation selector ----------
        formation_options = {
            "Auto (best xP)": None,
            "3-4-3": (3, 4, 3),
            "3-5-2": (3, 5, 2),
            "4-3-3": (4, 3, 3),
            "4-4-2": (4, 4, 2),
            "4-5-1": (4, 5, 1),
            "5-3-2": (5, 3, 2),
            "5-4-1": (5, 4, 1),
        }

        selected_formation_label = st.selectbox(
            "📐 Formation",
            options=list(formation_options.keys()),
            index=0,
            key="formation_selector",
        )
        forced_formation = formation_options[selected_formation_label]

        starting_11, bench_df = select_xi_with_formation(
            full_squad, "xP", formation=forced_formation
        )

        # Show actual formation on pitch
        def_count = len(starting_11[starting_11["position"] == "DEF"])
        mid_count = len(starting_11[starting_11["position"] == "MID"])
        fwd_count = len(starting_11[starting_11["position"] == "FWD"])
        st.caption(f"Current formation on pitch: **{def_count}-{mid_count}-{fwd_count}**")

        # Captain & vice
        captain_id = starting_11.sort_values("xP", ascending=False).iloc[0]["id"]
        vice_id = None
        if picks_data:
            for p in picks_data.get("picks", []):
                if p.get("is_captain"):
                    captain_id = p["element"]
                if p.get("is_vice_captain"):
                    vice_id = p["element"]
        if captain_id not in starting_11["id"].values:
            captain_id = starting_11.sort_values("xP", ascending=False).iloc[0]["id"]

        captain_row = starting_11[starting_11["id"] == captain_id].iloc[0]
        total_xp = (starting_11["xP"].sum() + captain_row["xP"]).round(2)
        total_cost = full_squad["now_cost"].sum().round(1)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Squad", f"{len(starting_11)} start / {len(bench_df)} bench")
        m2.metric("Squad Value", f"£{total_cost:.1f}m")
        m3.metric("Captain 👑", captain_row["web_name"], f"{captain_row['xP']*2:.1f} (x2)")
        m4.metric("Projected Points", f"{total_xp:.2f}")

        st.subheader(f"🏟️ Pitch — {selected_gw_label}")
        st.plotly_chart(
            generate_fpl_pitch(starting_11, bench_df, captain_id, vice_id, selected_gw_num),
            use_container_width=True,
        )

        risky = full_squad[full_squad["status"] != "a"]
        if not risky.empty:
            st.warning("Availability concerns in your squad:")
            st.dataframe(risky[["web_name", "status_badge", "news", "xP"]], hide_index=True)

        st.markdown("---")
        st.subheader(f"📅 Squad xP Breakdown (GW1–GW{MAX_GW_HORIZON})")
        gw_cols = [f"GW{i}_xP" for i in range(1, MAX_GW_HORIZON + 1)]
        breakdown = pd.concat([starting_11, bench_df])[
            ["web_name", "position", "team_short", "now_cost", "status_badge"] + gw_cols
        ].copy()
        breakdown.columns = ["Player", "Pos", "Team", "Cost", "Status"] + [f"GW{i}" for i in range(1, MAX_GW_HORIZON + 1)]
        st.dataframe(breakdown, use_container_width=True, hide_index=True)

# =============================================================================
# MANUAL TRANSFER PLANNER
# =============================================================================
elif menu == "🔄 Transfer Planner":
    st.title("🔄 Manual Transfer Planner")

    if st.session_state.custom_squad_ids and len(st.session_state.custom_squad_ids) >= 15:
        current_ids = st.session_state.custom_squad_ids
    elif picks_data:
        current_ids = [p["element"] for p in picks_data.get("picks", [])]
    else:
        current_ids = []

    if len(current_ids) < 15:
        st.warning("⚠️ Need a full 15-player squad first.")
        st.stop()

    active = players_df[players_df["id"].isin(current_ids)].copy()
    squad_val = round(active["now_cost"].sum(), 1)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Squad Value", f"£{squad_val:.1f}m")
    st.session_state.bank_balance = c2.number_input(
        "In The Bank (£m)", min_value=0.0, max_value=30.0,
        value=float(st.session_state.bank_balance), step=0.1,
    )
    free_transfers = c3.number_input("Free Transfers", min_value=0, max_value=5, value=1, step=1)
    total_budget = round(squad_val + st.session_state.bank_balance, 1)
    c4.metric("Total Budget", f"£{total_budget:.1f}m")

    st.markdown("---")
    st.subheader("🔁 Evaluate Transfer")

    left, right = st.columns(2)
    with left:
        st.markdown("#### ❌ Player Out")
        out_id = st.selectbox(
            "Sell",
            options=active["id"].tolist(),
            format_func=lambda x: active.loc[active["id"] == x, "display_label"].values[0],
        )
        p_out = active[active["id"] == out_id].iloc[0]

    with right:
        st.markdown("#### 🔄 Player In")
        max_afford = round(p_out["now_cost"] + st.session_state.bank_balance, 1)
        targets = players_df[
            (players_df["position"] == p_out["position"])
            & (~players_df["id"].isin(current_ids))
            & (players_df["now_cost"] <= max_afford)
        ].sort_values(selected_gw_col, ascending=False)

        if targets.empty:
            st.error("No affordable replacements.")
            p_in = None
        else:
            in_id = st.selectbox(
                "Buy",
                options=targets["id"].tolist(),
                format_func=lambda x: targets.loc[targets["id"] == x, "display_label"].values[0],
            )
            p_in = targets[targets["id"] == in_id].iloc[0]

    if p_in is not None:
        cost_diff = round(p_in["now_cost"] - p_out["now_cost"], 1)
        xp_diff = round(p_in[selected_gw_col] - p_out[selected_gw_col], 2)
        horizon = [f"GW{i}_xP" for i in range(selected_gw_num, min(MAX_GW_HORIZON + 1, selected_gw_num + 5))]
        cum_diff = round(sum(p_in[c] for c in horizon) - sum(p_out[c] for c in horizon), 2)
        hit_cost = 0 if free_transfers >= 1 else 4

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Cost Change", f"£{cost_diff:+.1f}m")
        m2.metric(f"{selected_gw_label} xP Δ", f"{xp_diff:+.2f}")
        m3.metric(f"{len(horizon)}-GW Cumul. Δ", f"{cum_diff:+.2f}")
        m4.metric("Bank After", f"£{st.session_state.bank_balance - cost_diff:.1f}m")

        if hit_cost:
            st.warning(f"This would be a **-4 hit**. Net gain: **{xp_diff - hit_cost:+.2f}**")

        if st.button("➕ Apply Transfer", type="primary"):
            new_ids = [i for i in current_ids if i != out_id] + [in_id]
            st.session_state.custom_squad_ids = new_ids
            st.session_state.bank_balance = round(st.session_state.bank_balance - cost_diff, 1)
            st.session_state.planned_transfers.append({
                "out": p_out["web_name"], "in": p_in["web_name"],
                "cost": cost_diff, "xp": xp_diff,
            })
            st.success(f"✅ {p_out['web_name']} → {p_in['web_name']}")
            st.rerun()

# =============================================================================
# TRANSFER RECOMMENDATIONS
# =============================================================================
elif menu == "💡 Transfer Recommendations":
    st.title("💡 Smart Transfer Recommendations")

    if st.session_state.custom_squad_ids and len(st.session_state.custom_squad_ids) >= 15:
        current_ids = st.session_state.custom_squad_ids
    elif picks_data:
        current_ids = [p["element"] for p in picks_data.get("picks", [])]
    else:
        current_ids = []

    if len(current_ids) < 15:
        st.warning("Need a full 15-player squad first.")
        st.stop()

    squad = players_df[players_df["id"].isin(current_ids)].copy()
    bank = float(st.session_state.bank_balance)
    horizon_gws = list(range(selected_gw_num, min(MAX_GW_HORIZON + 1, selected_gw_num + 5)))
    horizon_cols = [f"GW{g}_xP" for g in horizon_gws]
    players_df["horizon_xp"] = players_df[horizon_cols].mean(axis=1)
    squad["horizon_xp"] = squad[horizon_cols].mean(axis=1)

    st.subheader(f"Looking at GW{horizon_gws[0]}–GW{horizon_gws[-1]}")

    st.markdown("### ⭐ Best Single Transfers")
    recommendations = []
    for _, out_p in squad.iterrows():
        max_price = round(out_p["now_cost"] + bank, 1)
        targets = players_df[
            (players_df["position"] == out_p["position"])
            & (~players_df["id"].isin(current_ids))
            & (players_df["now_cost"] <= max_price)
            & (players_df["status"].isin(["a", "d"]))
        ]
        if targets.empty:
            continue
        best_in = targets.sort_values("horizon_xp", ascending=False).iloc[0]
        gain = round(best_in["horizon_xp"] - out_p["horizon_xp"], 2)
        if gain > 0.25:
            recommendations.append({
                "out_id": out_p["id"], "in_id": best_in["id"],
                "Out": out_p["web_name"], "In": best_in["web_name"],
                "In Team": best_in["team_short"],
                "Cost Δ": round(best_in["now_cost"] - out_p["now_cost"], 1),
                "Avg xP Gain": gain,
                "Out Status": out_p["status_badge"],
                "In Status": best_in["status_badge"],
            })

    if recommendations:
        rec_df = pd.DataFrame(recommendations).sort_values("Avg xP Gain", ascending=False).head(10)
        for idx, row in rec_df.iterrows():
            cols = st.columns([3, 2, 1.2, 1.5, 1.5, 1])
            cols[0].write(f"**{row['Out']}** → **{row['In']}** ({row['In Team']})")
            cols[1].write(f"+{row['Avg xP Gain']} xP")
            cols[2].write(f"£{row['Cost Δ']:+.1f}m")
            cols[3].write(row["Out Status"])
            cols[4].write(row["In Status"])
            if cols[5].button("Apply", key=f"rec_{row['out_id']}_{row['in_id']}"):
                new_ids = [i for i in current_ids if i != row["out_id"]] + [row["in_id"]]
                st.session_state.custom_squad_ids = new_ids
                st.session_state.bank_balance = round(bank - row["Cost Δ"], 1)
                st.success(f"Applied {row['Out']} → {row['In']}")
                st.rerun()
    else:
        st.info("No strong upgrades found with current bank.")

# =============================================================================
# FIXTURE ANALYZER
# =============================================================================
elif menu == "📅 Fixture Analyzer":
    st.title("📅 Fixture Analyzer")
    start_gw = st.slider("From GW", 1, MAX_GW_HORIZON, selected_gw_num)
    num_gws = st.slider("Number of GWs", 4, 10, 6)
    end_gw = min(start_gw + num_gws - 1, 38)

    rows = []
    for tid, tname in team_short_map.items():
        row = {"Team": tname}
        total = 0
        count = 0
        for gw in range(start_gw, end_gw + 1):
            meta = team_fixture_details.get(tid, {}).get(gw)
            if meta:
                row[f"GW{gw}"] = f"{meta['opponent']} ({meta['venue']}) [{meta['fdr']}]"
                total += meta["fdr"]
                count += 1
            else:
                row[f"GW{gw}"] = "–"
        row["Avg FDR"] = round(total / count, 2) if count else None
        rows.append(row)

    fdr_df = pd.DataFrame(rows).sort_values("Avg FDR")
    st.dataframe(fdr_df, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 🟢 Easiest runs")
        st.dataframe(fdr_df.nsmallest(8, "Avg FDR"), hide_index=True)
    with c2:
        st.markdown("### 🔴 Hardest runs")
        st.dataframe(fdr_df.nlargest(8, "Avg FDR"), hide_index=True)

# =============================================================================
# CHIP SIMULATOR
# =============================================================================
elif menu == "🎰 Chip Simulator":
    st.title("🎰 Chip Simulator")

    if st.session_state.custom_squad_ids and len(st.session_state.custom_squad_ids) >= 15:
        ids = st.session_state.custom_squad_ids
    elif picks_data:
        ids = [p["element"] for p in picks_data.get("picks", [])]
    else:
        st.warning("Load a squad first.")
        st.stop()

    squad = players_df[players_df["id"].isin(ids)].copy()
    xi, bench = select_xi_with_formation(squad, "xP")
    base = xi["xP"].sum()
    capt = xi["xP"].max()

    st.metric("Normal (with captain)", f"{base + capt:.1f} pts")
    st.write(f"**Triple Captain**: ~{base + capt * 2:.1f} pts")
    st.write(f"**Bench Boost**: ~{base + capt + bench['xP'].sum():.1f} pts")
    st.info("For Free Hit / Wildcard use the Recommendations + Explorer pages to build the optimal team.")

# =============================================================================
# PLAYER EXPLORER
# =============================================================================
elif menu == "🔍 Player Explorer & Differentials":
    st.title("🔍 Player Explorer & Differentials")

    f1, f2, f3, f4 = st.columns([2, 1.2, 1.2, 1.2])
    with f1:
        search_query = st.text_input("🔎 Search player", key="ex_search")
    with f2:
        pos_f = st.multiselect("Position", ["GKP", "DEF", "MID", "FWD"], default=["GKP", "DEF", "MID", "FWD"])
    with f3:
        max_price = st.slider("Max Price (£m)", 4.0, 15.0, 15.0, 0.5)
    with f4:
        differentials_mode = st.toggle("💎 Differentials only", False)

    max_own = 100.0
    if differentials_mode:
        max_own = st.slider("Max Ownership %", 1.0, 50.0, 12.0, 1.0)

    filtered = players_df.copy()
    if pos_f:
        filtered = filtered[filtered["position"].isin(pos_f)]
    filtered = filtered[filtered["now_cost"] <= max_price]
    if differentials_mode:
        filtered = filtered[filtered["selected_by_percent"] <= max_own]
    if search_query and search_query.strip():
        q = search_query.strip().lower()
        filtered = filtered[
            filtered["web_name"].str.lower().str.contains(q, na=False)
            | filtered["team_short"].str.lower().str.contains(q, na=False)
            | filtered["team_name"].str.lower().str.contains(q, na=False)
        ]
    filtered = filtered.sort_values(selected_gw_col, ascending=False)

    st.markdown(f"### {len(filtered)} players found")

    if filtered.empty:
        st.info("No players match.")
    else:
        gw_cols = [f"GW{i}_xP" for i in range(selected_gw_num, MAX_GW_HORIZON + 1)]
        gw_names = [f"GW{i}" for i in range(selected_gw_num, MAX_GW_HORIZON + 1)]

        show = filtered[
            ["web_name", "position", "team_short", "now_cost", "selected_by_percent",
             "status_badge", "price_change", "own_risk"] + gw_cols
        ].head(40).copy()
        show.columns = ["Player", "Pos", "Team", "Price", "Own%", "Status", "Δ Price", "Risk"] + gw_names
        show["Total"] = show[gw_names].sum(axis=1).round(1)
        st.dataframe(show, use_container_width=True, hide_index=True)
