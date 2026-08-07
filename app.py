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
import difflib

# Optional – install with: pip install understatapi
try:
    from understatapi import UnderstatClient
    UNDERSTAT_AVAILABLE = True
except ImportError:
    UNDERSTAT_AVAILABLE = False

# =============================================================================
# CONFIG
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
UNDERSTAT_BLEND = 0.55
UNDERSTAT_SEASON = "2026"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
LEGAL_FORMATIONS = [(3,4,3),(3,5,2),(4,3,3),(4,4,2),(4,5,1),(5,3,2),(5,4,1)]
STATUS_MAP = {
    "a": ("✅", "Available"), "d": ("⚠️", "Doubtful"), "i": ("🚑", "Injured"),
    "s": ("🔴", "Suspended"), "u": ("❓", "Unavailable"), "n": ("❌", "Not available"),
}

# Updated from FPL Assistant (5–7 Aug 2026) + official FPL expected list
SET_PIECE_DATA = {
    "Arsenal": {
        "Penalties": [("Saka", 60), ("Gyökeres", 25), ("Ødegaard", 15)],
        "Free Kicks": [("Rice", 50), ("Saka", 30), ("Eze", 20)],
        "Corners": [("Rice", 40), ("Saka", 30), ("Madueke", 20), ("Ødegaard", 10)],
    },
    "Aston Villa": {
        "Penalties": [("Buendía", 55), ("Watkins", 45)],
        "Free Kicks": [("Buendía", 70)],
        "Corners": [("Digne", 35), ("Cash", 35), ("McGinn", 30)],
    },
    "Bournemouth": {
        "Penalties": [("Kluivert", 35), ("Tavernier", 30), ("Kroupi", 35)],
        "Free Kicks": [("Tavernier", 30), ("Kluivert", 25), ("Ünal", 25), ("Brooks", 20)],
        "Corners": [("Tavernier", 35), ("Scott", 30), ("Cook", 20), ("Brooks", 15)],
    },
    "Brentford": {
        "Penalties": [("Thiago", 55), ("Schade", 25), ("Jensen", 20)],
        "Free Kicks": [("Lewis-Potter", 40), ("Jensen", 35), ("Damsgaard", 25)],
        "Corners": [("Jensen", 40), ("Damsgaard", 25), ("Janelt", 20), ("Ouattara", 15)],
    },
    "Brighton": {
        "Penalties": [("Groß", 40), ("Welbeck", 40), ("O'Riley", 20)],
        "Free Kicks": [("Ayari", 25), ("Dunk", 25), ("De Cuyper", 25), ("Gómez", 25)],
        "Corners": [("Groß", 40), ("Boscagli", 30), ("Minteh", 30)],
    },
    "Chelsea": {
        "Penalties": [("Palmer", 65), ("Fernández", 20), ("Estêvão", 15)],
        "Free Kicks": [("James", 35), ("Fernández", 25), ("Palmer", 25), ("Neto", 15)],
        "Corners": [("James", 35), ("Neto", 30), ("Fernández", 25), ("Estêvão", 10)],
    },
    "Crystal Palace": {
        "Penalties": [("Mateta", 65), ("Sarr", 25), ("Devenny", 10)],
        "Free Kicks": [("Pino", 40), ("Devenny", 30), ("Johnson", 30)],
        "Corners": [("Johnson", 35), ("Wharton", 30), ("Hughes", 20), ("Kamada", 15)],
    },
    "Everton": {
        "Penalties": [("Ndiaye", 50), ("Garner", 30), ("Beto", 20)],
        "Free Kicks": [("Garner", 60), ("McNeil", 40)],
        "Corners": [("Garner", 40), ("Dewsbury-Hall", 30), ("McNeil", 30)],
    },
    "Fulham": {
        "Penalties": [("Robinson", 50), ("Iwobi", 30), ("Lukić", 20)],
        "Free Kicks": [("Iwobi", 50), ("Lukić", 50)],
        "Corners": [("Iwobi", 45), ("Lukić", 40), ("Kevin", 15)],
    },
    "Leeds": {
        "Penalties": [("Calvert-Lewin", 60), ("Stach", 20), ("Longstaff", 20)],
        "Free Kicks": [("Stach", 50), ("Longstaff", 30), ("Aaronson", 20)],
        "Corners": [("Stach", 45), ("Longstaff", 35), ("Tanaka", 20)],
    },
    "Liverpool": {
        "Penalties": [("Szoboszlai", 35), ("Gakpo", 30), ("Mac Allister", 25), ("Isak", 10)],
        "Free Kicks": [("Szoboszlai", 55), ("Wirtz", 45)],
        "Corners": [("Szoboszlai", 40), ("Gakpo", 30), ("Wirtz", 30)],
    },
    "Man City": {
        "Penalties": [("Haaland", 75), ("Cherki", 10), ("Marmoush", 10), ("Foden", 5)],
        "Free Kicks": [("Cherki", 30), ("Marmoush", 30), ("Foden", 25), ("Reijnders", 15)],
        "Corners": [("Foden", 30), ("Cherki", 30), ("Reijnders", 25), ("Marmoush", 15)],
    },
    "Man Utd": {
        "Penalties": [("Fernandes", 85), ("Mbeumo", 10), ("Mount", 5)],
        "Free Kicks": [("Fernandes", 70), ("Mbeumo", 20), ("Mount", 10)],
        "Corners": [("Fernandes", 50), ("Mbeumo", 30), ("Amad", 20)],
    },
    "Newcastle": {
        "Penalties": [("Guimarães", 40), ("Woltemade", 35), ("Hall", 15), ("Schär", 10)],
        "Free Kicks": [("Hall", 40), ("Guimarães", 30), ("Schär", 30)],
        "Corners": [("Hall", 40), ("Guimarães", 30), ("Elanga", 20), ("Miley", 10)],
    },
    "Nott'm Forest": {
        "Penalties": [("Wood", 55), ("Gibbs-White", 45)],
        "Free Kicks": [("Gibbs-White", 60), ("Murillo", 20), ("Williams", 20)],
        "Corners": [("Hutchinson", 40), ("Williams", 35), ("Bakwa", 25)],
    },
    "Sunderland": {
        "Penalties": [("Diarra", 55), ("Le Fée", 45)],
        "Free Kicks": [("Xhaka", 50), ("Le Fée", 50)],
        "Corners": [("Xhaka", 40), ("Hume", 35), ("Le Fée", 25)],
    },
    "Spurs": {
        "Penalties": [("Solanke", 50), ("Kudus", 20), ("Simons", 15), ("Porro", 15)],
        "Free Kicks": [("Porro", 35), ("Kudus", 25), ("Simons", 20), ("Tel", 20)],
        "Corners": [("Porro", 30), ("Kudus", 25), ("Tel", 25), ("Simons", 20)],
    },
    "Coventry": {
        "Penalties": [("Wright", 60), ("Rudoni", 25), ("Torp", 15)],
        "Free Kicks": [("Rudoni", 40), ("Torp", 40), ("van Ewijk", 20)],
        "Corners": [("Grimes", 40), ("Rudoni", 30), ("Torp", 30)],
    },
    "Hull": {
        "Penalties": [("McBurnie", 40), ("Crooks", 30), ("Slater", 20), ("Giles", 10)],
        "Free Kicks": [("Giles", 40), ("Belloumi", 40), ("Slater", 20)],
        "Corners": [("Giles", 35), ("Belloumi", 35), ("Slater", 30)],
    },
    "Ipswich": {
        "Penalties": [("Clarke", 40), ("Philogene", 35), ("Hirst", 25)],
        "Free Kicks": [("Philogene", 30), ("Davis", 30), ("Núñez", 20), ("Clarke", 20)],
        "Corners": [("Philogene", 30), ("Davis", 30), ("Núñez", 20), ("Clarke", 20)],
    },
}

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(page_title=PAGE_TITLE, page_icon="⚽", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
.main { background-color: #0E1117; color: #FFFFFF; }
.stMetric { background-color: #1E222D; padding: 15px; border-radius: 10px; border: 1px solid #2B313E; }
div[data-testid="stSidebar"] { background-color: #161922; border-right: 1px solid #2B313E; }
div[data-testid="stSidebar"] button[kind="tertiary"] p {
    font-size: 28px !important; font-weight: 900 !important; color: #00FF7F !important;
}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# SESSION STATE
# =============================================================================
defaults = {
    "menu_selection": "📊 Dashboard Overview",
    "bank_balance": 0.0,
    "custom_squad_ids": None,
    "planned_transfers": [],
    "manager_meta": {},
    "use_official_squad": True,
    "multi_gw_plan": [],
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =============================================================================
# HTTP
# =============================================================================
def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update(HEADERS)
    return s

SESSION = make_session()

@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading FPL data…")
def load_bootstrap():
    try:
        r = SESSION.get(f"{FPL_BASE}/bootstrap-static/", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Bootstrap failed: {e}")
        return None

@st.cache_data(ttl=CACHE_TTL)
def load_fixtures():
    try:
        r = SESSION.get(f"{FPL_BASE}/fixtures/", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

@st.cache_data(ttl=300)
def fetch_entry(mid):
    try:
        r = SESSION.get(f"{FPL_BASE}/entry/{mid}/", timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None

@st.cache_data(ttl=300)
def fetch_picks(mid, gw):
    for g in (gw, max(1, gw-1)):
        try:
            r = SESSION.get(f"{FPL_BASE}/entry/{mid}/event/{g}/picks/", timeout=10)
            if r.status_code == 200:
                return r.json()
        except Exception:
            continue
    return None

# =============================================================================
# UNDERSTAT
# =============================================================================
@st.cache_data(ttl=CACHE_TTL, show_spinner="Fetching Understat xG/xA…")
def load_understat_players(season: str = UNDERSTAT_SEASON):
    if not UNDERSTAT_AVAILABLE:
        return pd.DataFrame()
    try:
        with UnderstatClient() as understat:
            data = understat.league(league="EPL").get_player_data(season=season)
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        keep = ["id", "player_name", "team_title", "games", "time", "goals", "assists",
                "xG", "xA", "npxG", "xGChain", "xGBuildup", "shots", "key_passes"]
        df = df[[c for c in keep if c in df.columns]].copy()
        for col in ["xG", "xA", "npxG", "xGChain", "time"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df["xGI"] = df.get("xG", 0) + df.get("xA", 0)
        df["xGI90"] = (df["xGI"] / df["time"].clip(lower=1)) * 90
        df["xG90"]  = (df.get("xG", 0) / df["time"].clip(lower=1)) * 90
        df["xA90"]  = (df.get("xA", 0) / df["time"].clip(lower=1)) * 90
        return df
    except Exception as e:
        st.warning(f"Understat fetch failed: {e}")
        return pd.DataFrame()

def _norm_name(s: str) -> str:
    return (str(s).lower()
            .replace("ö", "o").replace("ü", "u").replace("á", "a")
            .replace("é", "e").replace("í", "i").replace("ø", "o")
            .replace("ñ", "n").replace("-", " ").replace(".", "").strip())

def merge_understat(fpl_df: pd.DataFrame, under_df: pd.DataFrame) -> pd.DataFrame:
    fpl_df = fpl_df.copy()
    if under_df.empty:
        fpl_df["us_xGI90"] = np.nan
        fpl_df["us_xG90"] = np.nan
        fpl_df["us_xA90"] = np.nan
        return fpl_df

    under_df = under_df.copy()
    under_df["norm_name"] = under_df["player_name"].apply(_norm_name)
    fpl_df["norm_name"] = fpl_df["web_name"].apply(_norm_name)

    merged = fpl_df.merge(
        under_df[["norm_name", "xGI90", "xG90", "xA90"]],
        on="norm_name", how="left"
    )

    unmatched = merged["xGI90"].isna()
    if unmatched.any():
        under_names = under_df["norm_name"].tolist()
        for idx in merged[unmatched].index:
            name = merged.at[idx, "norm_name"]
            matches = difflib.get_close_matches(name, under_names, n=1, cutoff=0.72)
            if matches:
                row = under_df[under_df["norm_name"] == matches[0]].iloc[0]
                merged.at[idx, "xGI90"] = row["xGI90"]
                merged.at[idx, "xG90"] = row["xG90"]
                merged.at[idx, "xA90"] = row["xA90"]

    merged = merged.rename(columns={
        "xGI90": "us_xGI90", "xG90": "us_xG90", "xA90": "us_xA90"
    })
    return merged.drop(columns=["norm_name"], errors="ignore")

# =============================================================================
# DATA
# =============================================================================
raw = load_bootstrap()
fixtures_data = load_fixtures()
if not raw:
    st.error("Could not load FPL data.")
    st.stop()

players_df = pd.DataFrame(raw["elements"])
teams_df = pd.DataFrame(raw["teams"])
positions_df = pd.DataFrame(raw["element_types"])
events_df = pd.DataFrame(raw["events"])

current_gw, next_gw = 1, 1
for _, e in events_df.iterrows():
    if e.get("is_current"):
        current_gw = next_gw = int(e["id"])
        break
    if e.get("is_next"):
        next_gw = int(e["id"])
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
players_df["selected_by_percent"] = pd.to_numeric(players_df["selected_by_percent"], errors="coerce").fillna(0)

for col in ["expected_goals","expected_assists","expected_goal_involvements","minutes","ep_next",
            "chance_of_playing_next_round","form","cost_change_event"]:
    players_df[col] = pd.to_numeric(players_df.get(col, 0), errors="coerce").fillna(0)

players_df["games_played"] = (players_df["minutes"] / 90).clip(lower=0.5)
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
players_df["price_change"] = players_df["cost_change_event"].apply(
    lambda v: f"⬆️ +{v/10:.1f}" if v > 0 else (f"⬇️ {v/10:.1f}" if v < 0 else "–")
)
players_df["display_label"] = players_df["web_name"] + " (" + players_df["team_short"] + ") – £" + players_df["now_cost"].astype(str) + "m"

def get_photo(code):
    if not code or not isinstance(code, str):
        return "https://resources.premierleague.com/premierleague/photos/players/110x140/Photo-Missing.png"
    return f"https://resources.premierleague.com/premierleague/photos/players/110x140/p{code.replace('.jpg','').replace('.png','')}.png"

players_df["photo_url"] = players_df.get("photo", "").apply(get_photo)

team_fixtures = {}
team_fixture_details = {}
for f in fixtures_data:
    gw = f.get("event")
    if not gw: continue
    h, a = f["team_h"], f["team_a"]
    team_fixtures.setdefault(h, {})[gw] = f["team_h_difficulty"]
    team_fixtures.setdefault(a, {})[gw] = f["team_a_difficulty"]
    team_fixture_details.setdefault(h, {})[gw] = {"opponent": team_short_map.get(a,"?"), "venue":"H", "fdr":f["team_h_difficulty"], "opp_id":a}
    team_fixture_details.setdefault(a, {})[gw] = {"opponent": team_short_map.get(h,"?"), "venue":"A", "fdr":f["team_a_difficulty"], "opp_id":h}

def get_next_fixture(tid, from_gw):
    for gw in range(from_gw, 39):
        m = team_fixture_details.get(tid, {}).get(gw)
        if m: return f"{m['opponent']} ({m['venue']})"
    return "–"

us_df = load_understat_players(UNDERSTAT_SEASON)
players_df = merge_understat(players_df, us_df)

players_df["xgi_p90_final"] = np.where(
    players_df["us_xGI90"].notna(),
    UNDERSTAT_BLEND * players_df["us_xGI90"] + (1 - UNDERSTAT_BLEND) * players_df["xgi_p90"],
    players_df["xgi_p90"]
)

# =============================================================================
# xP MODEL
# =============================================================================
def compute_xp(df, max_gw=MAX_GW_HORIZON):
    out = df.copy()
    base = out["ep_next"].fillna(0)
    xgi = out["position"].map(XGI_WEIGHT).fillna(0) * out["xgi_p90_final"]
    form = out["form"].fillna(0) * FORM_WEIGHT
    blended = EP_BLEND * base + (1 - EP_BLEND) * (base + xgi) + form
    mins = (out["avg_minutes"] / MINUTES_THRESHOLD).clip(0.2, 1)
    chance = out["chance_of_playing_next_round"].replace(0, 100) / 100
    chance = chance.fillna(1).clip(0.15, 1)
    status_pen = out["status"].map({"a":1,"d":0.7,"i":0.15,"s":0.1,"u":0.2,"n":0.1}).fillna(1)
    unadj = blended * mins * chance * status_pen

    for gw in range(1, max_gw + 1):
        fdr = out["team"].map(lambda t: team_fixtures.get(t, {}).get(gw, 3))
        fdr_mod = 1 + (3 - fdr) * FDR_WEIGHT

        def str_mod(row):
            meta = team_fixture_details.get(row["team"], {}).get(gw)
            if not meta: return 1.0
            opp, venue = meta["opp_id"], meta["venue"]
            if row["position"] in ["MID", "FWD"]:
                att = team_att_home.get(row["team"], 3) if venue == "H" else team_att_away.get(row["team"], 3)
                opp_def = team_def_away.get(opp, 3) if venue == "H" else team_def_home.get(opp, 3)
                return 1 + (att - opp_def) * TEAM_STRENGTH_WEIGHT * 0.15
            else:
                deff = team_def_home.get(row["team"], 3) if venue == "H" else team_def_away.get(row["team"], 3)
                opp_att = team_att_away.get(opp, 3) if venue == "H" else team_att_home.get(opp, 3)
                return 1 + (deff - opp_att) * TEAM_STRENGTH_WEIGHT * 0.12

        strength = out.apply(str_mod, axis=1)
        out[f"GW{gw}_xP"] = (unadj * fdr_mod * strength).clip(0).round(2)
    return out

players_df = compute_xp(players_df)

def find_player(name, team_hint=None):
    n = name.lower().replace("ö","o").replace("ü","u").replace("á","a").replace("é","e")
    m = players_df[players_df["web_name"].str.lower().str.contains(n[:4], na=False)]
    if team_hint and not m.empty:
        tm = m[m["team_name"].str.contains(team_hint, case=False, na=False)]
        if not tm.empty: return tm.iloc[0]
    return m.iloc[0] if not m.empty else None

# =============================================================================
# SIDEBAR
# =============================================================================
if st.sidebar.button("⚽ PL-Kameratene", type="tertiary", use_container_width=True):
    st.session_state.menu_selection = "📊 Dashboard Overview"
    st.rerun()

st.sidebar.markdown(f"**GW:** {current_gw} → {next_gw}")
selected_gw_label = st.sidebar.selectbox(
    "🎯 Target GW",
    [f"GW{i}" for i in range(1, MAX_GW_HORIZON + 1)],
    index=min(max(next_gw - 1, 0), MAX_GW_HORIZON - 1)
)
selected_gw_col = f"{selected_gw_label}_xP"
selected_gw_num = int(selected_gw_label.replace("GW", ""))
players_df["xP"] = players_df[selected_gw_col]

menu_options = [
    "📊 Dashboard Overview",
    "🛡️ My Squad & Pitch View",
    "👑 Captain What-If",
    "🔄 Transfer Planner",
    "💡 Transfer Recommendations",
    "📅 Multi-GW Transfer Plan",
    "📅 Fixture Analyzer",
    "🎯 Set-Piece Takers",
    "🔍 Player Explorer",
    "🎰 Chip Simulator",
]

menu = st.sidebar.radio(
    "Navigation",
    menu_options,
    index=menu_options.index(st.session_state.menu_selection)
    if st.session_state.menu_selection in menu_options else 0
)
st.session_state.menu_selection = menu

st.sidebar.markdown("---")
manager_id = st.sidebar.text_input("Manager ID", value=DEFAULT_MANAGER_ID)
use_manual = st.sidebar.checkbox("Manual squad builder", value=not st.session_state.use_official_squad)

if st.sidebar.button("Reset to Official"):
    st.session_state.custom_squad_ids = None
    st.session_state.use_official_squad = True
    st.rerun()

if st.session_state.custom_squad_ids:
    st.sidebar.download_button(
        "⬇️ Download squad",
        json.dumps({"ids": st.session_state.custom_squad_ids, "bank": st.session_state.bank_balance}),
        "plk_squad.json"
    )

uploaded = st.sidebar.file_uploader("⬆️ Load squad", type="json")
if uploaded:
    try:
        d = json.load(uploaded)
        st.session_state.custom_squad_ids = d.get("ids")
        st.session_state.bank_balance = float(d.get("bank", 0))
        st.rerun()
    except Exception:
        st.sidebar.error("Bad JSON")

entry = fetch_entry(manager_id) if manager_id else None
picks_data = fetch_picks(manager_id, current_gw) if manager_id else None

if entry:
    bank_raw = entry.get("last_deadline_bank") or 0
    st.session_state.manager_meta = {
        "name": f"{entry.get('player_first_name','')} {entry.get('player_last_name','')}".strip(),
        "team_name": entry.get("name",""),
        "overall_rank": entry.get("summary_overall_rank"),
        "overall_points": entry.get("summary_overall_points"),
    }
    if picks_data and "entry_history" in picks_data:
        st.session_state.bank_balance = (picks_data["entry_history"].get("bank") or bank_raw) / 10
    else:
        st.session_state.bank_balance = bank_raw / 10

# =============================================================================
# HELPERS
# =============================================================================
def select_xi(squad, xp_col="xP", formation=None):
    if squad.empty or len(squad) < 11:
        return squad, pd.DataFrame()
    gkp = squad[squad["position"] == "GKP"].sort_values(xp_col, ascending=False)
    defs = squad[squad["position"] == "DEF"].sort_values(xp_col, ascending=False)
    mids = squad[squad["position"] == "MID"].sort_values(xp_col, ascending=False)
    fwds = squad[squad["position"] == "FWD"].sort_values(xp_col, ascending=False)

    if formation is None:
        best, best_xi = -1, None
        for nd, nm, nf in LEGAL_FORMATIONS:
            if len(defs) < nd or len(mids) < nm or len(fwds) < nf or len(gkp) < 1:
                continue
            xi = pd.concat([gkp.head(1), defs.head(nd), mids.head(nm), fwds.head(nf)])
            sc = xi[xp_col].sum()
            if sc > best:
                best, best_xi = sc, xi
        if best_xi is None:
            best_xi = squad.sort_values(xp_col, ascending=False).head(11)
    else:
        nd, nm, nf = formation
        if len(defs) < nd or len(mids) < nm or len(fwds) < nf or len(gkp) < 1:
            return select_xi(squad, xp_col, None)
        best_xi = pd.concat([gkp.head(1), defs.head(nd), mids.head(nm), fwds.head(nf)])

    bench = squad[~squad["id"].isin(best_xi["id"])]
    return best_xi, bench

def generate_pitch(xi, bench, capt_id, vice_id=None, gw=1):
    fig = go.Figure()
    fig.add_shape(type="rect", x0=0, y0=0, x1=100, y1=130, fillcolor="#2d8a4e", line_width=0, layer="below")
    fig.add_shape(type="rect", x0=2, y0=4, x1=98, y1=126, line=dict(color="white", width=2.5), fillcolor="rgba(0,0,0,0)")
    fig.add_shape(type="line", x0=2, y0=65, x1=98, y1=65, line=dict(color="white", width=2))
    fig.add_shape(type="circle", x0=42, y0=55, x1=58, y1=75, line=dict(color="white", width=2))

    pos_y = {"GKP": 18, "DEF": 42, "MID": 72, "FWD": 102}

    def card(x, y, p, bench=False):
        fig.add_layout_image(dict(
            source=p.get("photo_url") or get_photo(p.get("photo", "")),
            x=x - 0.04, y=y + 0.05, sizex=0.08, sizey=0.1,
            xref="x", yref="y", sizing="contain", layer="above"
        ))
        is_c = p["id"] == capt_id
        is_v = vice_id and p["id"] == vice_id
        if is_c or is_v:
            fig.add_annotation(
                x=x + 0.035, y=y + 0.09,
                text="<b>C</b>" if is_c else "<b>V</b>",
                showarrow=False, font=dict(size=10, color="#000"),
                bgcolor="#FFD700" if is_c else "#00BFFF", borderpad=2
            )
        fig.add_annotation(
            x=x, y=y - 0.04,
            text=f"<b>{p['web_name']}</b><br><span style='font-size:9px'>{get_next_fixture(p['team'], gw)}</span>",
            showarrow=False, font=dict(size=10, color="#111"),
            bgcolor="rgba(255,255,255,0.9)", borderpad=2
        )

    for pos, y in pos_y.items():
        ps = xi[xi["position"] == pos]
        xs = np.linspace(15, 85, len(ps)) if len(ps) > 1 else [50]
        for i, (_, p) in enumerate(ps.iterrows()):
            card(xs[i], y, p)

    if not bench.empty:
        xs = np.linspace(15, 85, len(bench))
        for i, (_, p) in enumerate(bench.iterrows()):
            card(xs[i], -8, p, True)

    fig.update_layout(
        xaxis=dict(range=[-2, 102], visible=False),
        yaxis=dict(range=[-18, 135], visible=False, scaleanchor="x"),
        height=750, margin=dict(l=5, r=5, t=20, b=5),
        plot_bgcolor="#1a0a2e", paper_bgcolor="#1a0a2e"
    )
    return fig

# =============================================================================
# PAGES
# =============================================================================
if menu == "📊 Dashboard Overview":
    st.title(f"📊 Dashboard — {selected_gw_label}")

    if UNDERSTAT_AVAILABLE and not us_df.empty:
        st.caption(f"✅ Understat xG/xA blended (season {UNDERSTAT_SEASON})")
    elif not UNDERSTAT_AVAILABLE:
        st.caption("ℹ️ Install `understatapi` for richer xG/xA data")

    cols = st.columns(4)
    for pos, col, em in zip(["GKP", "DEF", "MID", "FWD"], cols, ["🧤", "🛡️", "⚙️", "🎯"]):
        t = players_df[players_df["position"] == pos].sort_values("xP", ascending=False).iloc[0]
        col.metric(f"{em} Top {pos}", t["web_name"], f"{t['xP']} pts")

    st.subheader("👑 Best Captains")
    cap = players_df.sort_values("xP", ascending=False).head(10).copy()
    cap["Capt xP"] = (cap["xP"] * 2).round(1)
    st.dataframe(
        cap[["web_name", "position", "team_short", "now_cost", "selected_by_percent", "xP", "Capt xP", "status_badge"]],
        use_container_width=True, hide_index=True
    )

    st.subheader("🚀 Top 15")
    top = players_df.sort_values("xP", ascending=False).head(15)
    fig = px.bar(
        top, x="web_name", y="xP", color="position", text="xP",
        template="plotly_dark",
        color_discrete_map={"GKP": "#FFD700", "DEF": "#00BFFF", "MID": "#00FF7F", "FWD": "#FF4500"}
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

elif menu == "🛡️ My Squad & Pitch View":
    st.title("🛡️ My Squad & Pitch")
    official = [p["element"] for p in picks_data.get("picks", [])] if picks_data else []

    if use_manual or not official:
        st.info("**Manual mode** – Build a valid 15-man squad (2 GKP · 5 DEF · 5 MID · 3 FWD)")

        current_ids = st.session_state.custom_squad_ids or []
        current_squad = players_df[players_df["id"].isin(current_ids)] if current_ids else pd.DataFrame()

        counts = {"GKP": 0, "DEF": 0, "MID": 0, "FWD": 0}
        if not current_squad.empty:
            vc = current_squad["position"].value_counts().to_dict()
            counts = {k: vc.get(k, 0) for k in ["GKP", "DEF", "MID", "FWD"]}

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("🧤 GKP", f"{counts['GKP']}/2")
        c2.metric("🛡️ DEF", f"{counts['DEF']}/5")
        c3.metric("⚙️ MID", f"{counts['MID']}/5")
        c4.metric("🎯 FWD", f"{counts['FWD']}/3")
        total_cost = current_squad["now_cost"].sum() if not current_squad.empty else 0.0
        c5.metric("💰 Value", f"£{total_cost:.1f}m")

        st.markdown("---")

        search = st.text_input("🔍 Search player", placeholder="Type name…", key="squad_search")
        pos_filter = st.multiselect("Position filter", ["GKP", "DEF", "MID", "FWD"], default=["GKP", "DEF", "MID", "FWD"])

        available = players_df[
            (~players_df["id"].isin(current_ids)) &
            (players_df["position"].isin(pos_filter))
        ].copy()

        if search:
            available = available[available["web_name"].str.contains(search, case=False, na=False)]

        available = available.sort_values(["position", "now_cost"])

        max_allowed = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}

        if not available.empty:
            available["label"] = (
                available["web_name"] + " (" + available["team_short"] + ") – £" +
                available["now_cost"].astype(str) + "m  |  " + available["status_badge"]
            )

            for pos, emoji in [("GKP", "🧤"), ("DEF", "🛡️"), ("MID", "⚙️"), ("FWD", "🎯")]:
                pos_df = available[available["position"] == pos]
                remaining = max_allowed[pos] - counts[pos]
                if pos_df.empty or remaining <= 0:
                    continue

                with st.expander(f"{emoji} {pos} — {remaining} slot(s) left", expanded=(remaining > 0 and counts[pos] < max_allowed[pos])):
                    selected = st.multiselect(
                        f"Add {pos}",
                        options=pos_df["id"].tolist(),
                        format_func=lambda x: pos_df.loc[pos_df["id"] == x, "label"].values[0],
                        key=f"add_{pos}",
                        max_selections=remaining
                    )
                    if selected:
                        new_ids = list(dict.fromkeys(current_ids + selected))  # preserve order, unique
                        st.session_state.custom_squad_ids = new_ids
                        st.rerun()
        else:
            st.info("No more players match the current filter.")

        if current_ids:
            st.markdown("### Current Squad")
            st.dataframe(
                current_squad[["web_name", "position", "team_short", "now_cost", "status_badge", "xP"]]
                .sort_values(["position", "now_cost"]),
                use_container_width=True, hide_index=True
            )

            col_a, col_b = st.columns(2)
            with col_a:
                remove_id = st.selectbox(
                    "Remove a player",
                    current_ids,
                    format_func=lambda x: players_df.loc[players_df["id"] == x, "display_label"].values[0]
                )
                if st.button("Remove selected"):
                    st.session_state.custom_squad_ids = [i for i in current_ids if i != remove_id]
                    st.rerun()
            with col_b:
                if st.button("🗑️ Clear entire squad", type="secondary"):
                    st.session_state.custom_squad_ids = []
                    st.rerun()

        st.markdown("### Quick actions")
        qa1, qa2, qa3 = st.columns(3)
        with qa1:
            if st.button("Auto-fill cheapest valid 15"):
                g = players_df[players_df["position"] == "GKP"].nsmallest(2, "now_cost")["id"].tolist()
                d = players_df[players_df["position"] == "DEF"].nsmallest(5, "now_cost")["id"].tolist()
                m = players_df[players_df["position"] == "MID"].nsmallest(5, "now_cost")["id"].tolist()
                f = players_df[players_df["position"] == "FWD"].nsmallest(3, "now_cost")["id"].tolist()
                st.session_state.custom_squad_ids = g + d + m + f
                st.rerun()
        with qa2:
            if st.button("Auto-fill highest xP"):
                g = players_df[players_df["position"] == "GKP"].nlargest(2, "xP")["id"].tolist()
                d = players_df[players_df["position"] == "DEF"].nlargest(5, "xP")["id"].tolist()
                m = players_df[players_df["position"] == "MID"].nlargest(5, "xP")["id"].tolist()
                f = players_df[players_df["position"] == "FWD"].nlargest(3, "xP")["id"].tolist()
                st.session_state.custom_squad_ids = g + d + m + f
                st.rerun()
        with qa3:
            if official and st.button("Load official squad"):
                st.session_state.custom_squad_ids = official
                st.session_state.use_official_squad = True
                st.rerun()

        full = players_df[players_df["id"].isin(st.session_state.custom_squad_ids or [])]
    else:
        ids = st.session_state.custom_squad_ids or official
        full = players_df[players_df["id"].isin(ids)]

    if len(full) >= 11:
        form_opts = {
            "Auto (best xP)": None,
            "3-4-3": (3,4,3), "3-5-2": (3,5,2), "4-3-3": (4,3,3),
            "4-4-2": (4,4,2), "4-5-1": (4,5,1), "5-3-2": (5,3,2), "5-4-1": (5,4,1)
        }
        f_label = st.selectbox("📐 Formation", list(form_opts.keys()))
        xi, bench = select_xi(full, "xP", form_opts[f_label])
        st.caption(f"On pitch: {len(xi[xi.position=='DEF'])}-{len(xi[xi.position=='MID'])}-{len(xi[xi.position=='FWD'])}")

        st.markdown("### 🔄 Quick Swap")
        ca, cb, cc = st.columns([2, 2, 1])
        with ca:
            st_id = st.selectbox("Starter", xi["id"], format_func=lambda x: xi.loc[xi["id"]==x, "web_name"].values[0])
        with cb:
            b_id = st.selectbox(
                "Bench",
                bench["id"] if not bench.empty else [],
                format_func=lambda x: bench.loc[bench["id"]==x, "web_name"].values[0] if not bench.empty else ""
            )
        with cc:
            st.write(""); st.write("")
            if st.button("Swap ⇄") and b_id:
                st.success("Swap noted – re-select formation or use Manual mode for permanent change.")

        capt = xi.sort_values("xP", ascending=False).iloc[0]["id"]
        if picks_data:
            for p in picks_data.get("picks", []):
                if p.get("is_captain"):
                    capt = p["element"]
        if capt not in xi["id"].values:
            capt = xi.sort_values("xP", ascending=False).iloc[0]["id"]

        crow = xi[xi["id"] == capt].iloc[0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("XI / Bench", f"{len(xi)} / {len(bench)}")
        m2.metric("Value", f"£{full['now_cost'].sum():.1f}m")
        m3.metric("Captain", crow["web_name"], f"{crow['xP']*2:.1f}")
        m4.metric("Projected", f"{(xi['xP'].sum() + crow['xP']):.1f}")

        st.plotly_chart(generate_pitch(xi, bench, capt, gw=selected_gw_num), use_container_width=True)

elif menu == "👑 Captain What-If":
    st.title("👑 Captain What-If Calculator")

    ids = st.session_state.custom_squad_ids or (
        [p["element"] for p in picks_data.get("picks", [])] if picks_data else []
    )
    if len(ids) < 11:
        st.warning("Load a full squad first (My Squad & Pitch View).")
        st.stop()

    squad = players_df[players_df["id"].isin(ids)].copy()
    xi, _ = select_xi(squad, "xP")

    current_capt_id = None
    if picks_data:
        for p in picks_data.get("picks", []):
            if p.get("is_captain"):
                current_capt_id = p["element"]
                break
    if current_capt_id is None or current_capt_id not in xi["id"].values:
        current_capt_id = xi.sort_values("xP", ascending=False).iloc[0]["id"]

    col1, col2 = st.columns(2)
    with col1:
        capt_a = st.selectbox(
            "Current / Option A (doubled)",
            xi["id"],
            index=list(xi["id"]).index(current_capt_id) if current_capt_id in xi["id"].values else 0,
            format_func=lambda x: f"{xi.loc[xi['id']==x,'web_name'].values[0]}  ({xi.loc[xi['id']==x,'xP'].values[0]:.1f} xP)"
        )
    with col2:
        options_b = [i for i in xi["id"] if i != capt_a]
        capt_b = st.selectbox(
            "Alternative / Option B",
            options_b if options_b else xi["id"],
            format_func=lambda x: f"{xi.loc[xi['id']==x,'web_name'].values[0]}  ({xi.loc[xi['id']==x,'xP'].values[0]:.1f} xP)"
        )

    a_xp = float(xi.loc[xi["id"] == capt_a, "xP"].values[0])
    b_xp = float(xi.loc[xi["id"] == capt_b, "xP"].values[0])
    rest_xp = xi.loc[~xi["id"].isin([capt_a, capt_b]), "xP"].sum()

    total_a = rest_xp + a_xp * 2 + b_xp
    total_b = rest_xp + b_xp * 2 + a_xp
    diff = total_b - total_a

    m1, m2, m3 = st.columns(3)
    m1.metric("Captain A total", f"{total_a:.1f}")
    m2.metric("Captain B total", f"{total_b:.1f}", delta=f"{diff:+.1f}")
    m3.metric("Difference", f"{diff:+.1f} pts")

    if abs(diff) < 0.15:
        st.info("Essentially identical — pick higher ceiling / lower ownership if you want.")
    elif diff > 0:
        name_b = xi.loc[xi["id"] == capt_b, "web_name"].values[0]
        st.success(f"**Switch to {name_b}** for **+{diff:.1f}** expected points.")
    else:
        name_a = xi.loc[xi["id"] == capt_a, "web_name"].values[0]
        st.success(f"**Keep {name_a}** — alternative is **{abs(diff):.1f}** worse.")

    st.markdown("#### Fixture context")
    for pid, label in [(capt_a, "A"), (capt_b, "B")]:
        row = xi[xi["id"] == pid].iloc[0]
        fix = get_next_fixture(row["team"], selected_gw_num)
        us_info = f" | US xGI90: {row['us_xGI90']:.2f}" if pd.notna(row.get("us_xGI90")) else ""
        st.write(
            f"**{label}: {row['web_name']}** → {fix} | "
            f"xP {row['xP']:.1f} | Own% {row['selected_by_percent']:.1f}%{us_info}"
        )

elif menu == "🎯 Set-Piece Takers":
    st.title("🎯 Set-Piece Takers (2026/27)")
    st.caption("Source: FPL Assistant + official FPL expected list (updated Aug 2026). % = estimated role strength.")

    roles = st.multiselect("Roles", ["Penalties", "Free Kicks", "Corners"], default=["Penalties", "Free Kicks", "Corners"])
    rows = []
    for team, data in SET_PIECE_DATA.items():
        for role, takers in data.items():
            if role not in roles:
                continue
            for name, pct in takers:
                p = find_player(name, team)
                rows.append({
                    "Team": team,
                    "Role": role,
                    "Player": p["web_name"] if p is not None else name,
                    "Pos": p["position"] if p is not None else "–",
                    "% Chance": f"{pct}%",
                    "Price": p["now_cost"] if p is not None else None,
                    "Own%": round(p["selected_by_percent"], 1) if p is not None else None,
                    "xP": p["xP"] if p is not None else None,
                    "Status": p["status_badge"] if p is not None else "–",
                })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

elif menu == "📅 Fixture Analyzer":
    st.title("📅 Fixture Analyzer")
    start = st.slider("From GW", 1, MAX_GW_HORIZON, selected_gw_num)
    n = st.slider("GWs to show", 4, 10, 6)
    end = min(start + n - 1, 38)

    if st.button("📊 Rank teams: Easiest → Hardest", type="primary"):
        rank = []
        for tid, name in team_short_map.items():
            fdrs = [team_fixtures.get(tid, {}).get(g) for g in range(start, end + 1) if team_fixtures.get(tid, {}).get(g)]
            if fdrs:
                rank.append({"Team": name, "Avg FDR": round(sum(fdrs) / len(fdrs), 2), "Fixtures": len(fdrs)})
        rdf = pd.DataFrame(rank).sort_values("Avg FDR")
        st.dataframe(rdf, use_container_width=True, hide_index=True)
        fig = px.bar(
            rdf, x="Team", y="Avg FDR", color="Avg FDR",
            color_continuous_scale=["#00FF7F", "#E0E0E0", "#FF4500"], template="plotly_dark"
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    rows = []
    for tid, name in team_short_map.items():
        row = {"Team": name}
        tot = cnt = 0
        for g in range(start, end + 1):
            m = team_fixture_details.get(tid, {}).get(g)
            if m:
                row[f"GW{g}"] = f"{m['opponent']} ({m['venue']}) [{m['fdr']}]"
                tot += m["fdr"]
                cnt += 1
            else:
                row[f"GW{g}"] = "–"
        row["Avg FDR"] = round(tot / cnt, 2) if cnt else None
        rows.append(row)
    st.dataframe(pd.DataFrame(rows).sort_values("Avg FDR"), use_container_width=True, hide_index=True)

elif menu == "📅 Multi-GW Transfer Plan":
    st.title("📅 Multi-GW Transfer Plan")
    ids = st.session_state.custom_squad_ids or (
        [p["element"] for p in picks_data.get("picks", [])] if picks_data else []
    )
    if len(ids) < 15:
        st.warning("Need a full squad first.")
        st.stop()

    active = players_df[players_df["id"].isin(ids)]
    bank = float(st.session_state.bank_balance)
    ft = st.number_input("Free Transfers", 0, 5, 1)

    c1, c2, c3 = st.columns(3)
    with c1:
        out_id = st.selectbox("Sell", active["id"], format_func=lambda x: active.loc[active["id"]==x, "display_label"].values[0])
    with c2:
        maxp = active.loc[active["id"] == out_id, "now_cost"].values[0] + bank
        tgts = players_df[
            (~players_df["id"].isin(ids))
            & (players_df["now_cost"] <= maxp)
            & (players_df["position"] == active.loc[active["id"]==out_id, "position"].values[0])
        ]
        in_id = st.selectbox(
            "Buy",
            tgts["id"] if not tgts.empty else [],
            format_func=lambda x: tgts.loc[tgts["id"]==x, "display_label"].values[0] if not tgts.empty else ""
        )
    with c3:
        pgw = st.selectbox("For GW", list(range(selected_gw_num, min(selected_gw_num + 6, 39))))

    if st.button("Add to plan") and in_id:
        po = players_df[players_df["id"] == out_id].iloc[0]
        pi = players_df[players_df["id"] == in_id].iloc[0]
        st.session_state.multi_gw_plan.append({
            "gw": pgw, "out": po["web_name"], "in": pi["web_name"],
            "cost": round(pi["now_cost"] - po["now_cost"], 1),
            "xp": round(pi[f"GW{pgw}_xP"] - po[f"GW{pgw}_xP"], 2)
        })
        st.rerun()

    if st.session_state.multi_gw_plan:
        st.dataframe(pd.DataFrame(st.session_state.multi_gw_plan), hide_index=True)
        hits = max(0, len(st.session_state.multi_gw_plan) - ft) * 4
        st.metric("Projected hits", f"-{hits}")
        if st.button("Clear plan"):
            st.session_state.multi_gw_plan = []
            st.rerun()

elif menu == "💡 Transfer Recommendations":
    st.title("💡 Transfer Recommendations")
    ids = st.session_state.custom_squad_ids or (
        [p["element"] for p in picks_data.get("picks", [])] if picks_data else []
    )
    if len(ids) < 15:
        st.warning("Need full squad")
        st.stop()

    squad = players_df[players_df["id"].isin(ids)].copy()
    bank = float(st.session_state.bank_balance)
    hcols = [f"GW{g}_xP" for g in range(selected_gw_num, min(MAX_GW_HORIZON + 1, selected_gw_num + 5))]
    players_df["hx"] = players_df[hcols].mean(axis=1)
    squad["hx"] = squad[hcols].mean(axis=1)

    recs = []
    for _, o in squad.iterrows():
        tg = players_df[
            (players_df["position"] == o["position"])
            & (~players_df["id"].isin(ids))
            & (players_df["now_cost"] <= o["now_cost"] + bank)
            & (players_df["status"].isin(["a", "d"]))
        ]
        if tg.empty:
            continue
        b = tg.sort_values("hx", ascending=False).iloc[0]
        gain = round(b["hx"] - o["hx"], 2)
        if gain > 0.25:
            recs.append({
                "out_id": o["id"], "in_id": b["id"],
                "Out": o["web_name"], "In": b["web_name"],
                "Team": b["team_short"],
                "Cost": round(b["now_cost"] - o["now_cost"], 1),
                "Gain": gain
            })

    if recs:
        for r in sorted(recs, key=lambda x: -x["Gain"])[:8]:
            c = st.columns([3, 2, 1.5, 1])
            c[0].write(f"**{r['Out']}** → **{r['In']}** ({r['Team']})")
            c[1].write(f"+{r['Gain']}")
            c[2].write(f"£{r['Cost']:+.1f}")
            if c[3].button("Apply", key=f"{r['out_id']}_{r['in_id']}"):
                st.session_state.custom_squad_ids = [i for i in ids if i != r["out_id"]] + [r["in_id"]]
                st.session_state.bank_balance = round(bank - r["Cost"], 1)
                st.rerun()
    else:
        st.info("No strong upgrades.")

elif menu == "🔄 Transfer Planner":
    st.title("🔄 Manual Transfer Planner")
    st.info("Use Recommendations or Multi-GW Plan for smarter suggestions.")

elif menu == "🎰 Chip Simulator":
    st.title("🎰 Chip Simulator")
    ids = st.session_state.custom_squad_ids or (
        [p["element"] for p in picks_data.get("picks", [])] if picks_data else []
    )
    if len(ids) < 11:
        st.warning("Need squad")
        st.stop()

    sq = players_df[players_df["id"].isin(ids)]
    xi, bench = select_xi(sq)
    base, capt = xi["xP"].sum(), xi["xP"].max()
    st.metric("Normal", f"{base + capt:.1f}")
    st.write(f"Triple Captain ≈ {base + capt * 2:.1f}")
    st.write(f"Bench Boost ≈ {base + capt + bench['xP'].sum():.1f}")

elif menu == "🔍 Player Explorer":
    st.title("🔍 Player Explorer")
    q = st.text_input("Search")
    pos = st.multiselect("Pos", ["GKP", "DEF", "MID", "FWD"], default=["GKP", "DEF", "MID", "FWD"])
    mx = st.slider("Max price", 4.0, 15.0, 15.0, 0.5)
    diff = st.toggle("Differentials only")
    own = st.slider("Max own%", 1.0, 50.0, 12.0) if diff else 100.0

    f = players_df[players_df["position"].isin(pos) & (players_df["now_cost"] <= mx)]
    if diff:
        f = f[f["selected_by_percent"] <= own]
    if q:
        f = f[f["web_name"].str.lower().str.contains(q.lower(), na=False)]
    f = f.sort_values(selected_gw_col, ascending=False)

    gcols = [f"GW{i}_xP" for i in range(selected_gw_num, MAX_GW_HORIZON + 1)]
    show_cols = ["web_name", "position", "team_short", "now_cost", "selected_by_percent", "status_badge"] + gcols
    if "us_xGI90" in f.columns:
        show_cols.insert(6, "us_xGI90")

    show = f[show_cols].head(40)
    rename = {
        "web_name": "Player", "position": "Pos", "team_short": "Team",
        "now_cost": "Price", "selected_by_percent": "Own%", "status_badge": "Status",
        "us_xGI90": "US xGI90"
    }
    for i in range(selected_gw_num, MAX_GW_HORIZON + 1):
        rename[f"GW{i}_xP"] = f"GW{i}"
    show = show.rename(columns=rename)
    st.dataframe(show, use_container_width=True, hide_index=True)
