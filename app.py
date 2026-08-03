import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go

# --- PAGE CONFIGURATION & DARK THEME SETUP ---
st.set_page_config(
    page_title="PL-Kameratene",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern dark-mode sports analytics style
st.markdown("""
    <style>
    .main {
        background-color: #0E1117;
        color: #FFFFFF;
    }
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
    
    /* Style sidebar header button to look like a prominent, larger title */
    div[data-testid="stSidebar"] button[kind="tertiary"] {
        padding: 5px 0px !important;
        text-align: left !important;
        justify-content: flex-start !important;
    }
    
    div[data-testid="stSidebar"] button[kind="tertiary"] p {
        font-size: 32px !important;       /* Larger title font size */
        font-weight: 900 !important;       /* Extra bold */
        color: #00FF7F !important;         /* FPL Accent Green */
        letter-spacing: -0.5px !important;
        line-height: 1.2 !important;
    }
    </style>
""", unsafe_allow_html=True)

# Initialize navigation state
if "menu_selection" not in st.session_state:
    st.session_state.menu_selection = "📊 Dashboard Overview"

# --- API DATA FETCHING ---
@st.cache_data(ttl=3600)
def load_fpl_bootstrap():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

@st.cache_data(ttl=3600)
def load_fpl_fixtures():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    url = "https://fantasy.premierleague.com/api/fixtures/"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    return []

def fetch_user_squad(manager_id, current_gw):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    gw = max(1, current_gw)
    
    entry_url = f"https://fantasy.premierleague.com/api/entry/{manager_id}/"
    entry_res = requests.get(entry_url, headers=headers)
    if entry_res.status_code != 200:
        return None
        
    picks_url = f"https://fantasy.premierleague.com/api/entry/{manager_id}/event/{gw}/picks/"
    response = requests.get(picks_url, headers=headers)
    
    if response.status_code == 404 and gw > 1:
        picks_url = f"https://fantasy.premierleague.com/api/entry/{manager_id}/event/{gw - 1}/picks/"
        response = requests.get(picks_url, headers=headers)
        
    if response.status_code == 200:
        return response.json()
        
    return None

# Load base data
raw_data = load_fpl_bootstrap()
fixtures_data = load_fpl_fixtures()

if not raw_data:
    st.error("⚠️ Failed to load data from official FPL API. Please refresh or try again later.")
    st.stop()

# --- DATA PROCESSING ---
players_df = pd.DataFrame(raw_data['elements'])
teams_df = pd.DataFrame(raw_data['teams'])
positions_df = pd.DataFrame(raw_data['element_types'])
events_df = pd.DataFrame(raw_data['events'])

# Find current gameweek
current_gw = 1
for _, event in events_df.iterrows():
    if event['is_current']:
        current_gw = event['id']
        break
    elif event['is_next']:
        current_gw = max(1, event['id'] - 1)
        break

# Mappings
team_map = dict(zip(teams_df['id'], teams_df['name']))
team_short_map = dict(zip(teams_df['id'], teams_df['short_name']))
pos_map = dict(zip(positions_df['id'], positions_df['singular_name_short']))

players_df['team_name'] = players_df['team'].map(team_map)
players_df['team_short'] = players_df['team'].map(team_short_map)
players_df['position'] = players_df['element_type'].map(pos_map)
players_df['now_cost'] = players_df['now_cost'] / 10.0
players_df['selected_by_percent'] = pd.to_numeric(players_df['selected_by_percent'], errors='coerce').fillna(0.0)

# Clean FPL stats
players_df['expected_goals'] = pd.to_numeric(players_df.get('expected_goals', 0), errors='coerce').fillna(0.0)
players_df['expected_assists'] = pd.to_numeric(players_df.get('expected_assists', 0), errors='coerce').fillna(0.0)
players_df['expected_goal_involvements'] = pd.to_numeric(players_df.get('expected_goal_involvements', 0), errors='coerce').fillna(0.0)
players_df['expected_goals_conceded'] = pd.to_numeric(players_df.get('expected_goals_conceded', 0), errors='coerce').fillna(0.0)
players_df['minutes'] = pd.to_numeric(players_df['minutes'], errors='coerce').fillna(0)
players_df['games_played'] = (players_df['minutes'] / 90.0).clip(lower=1.0)
players_df['avg_minutes'] = players_df['minutes'] / players_df['games_played']

# --- OFFICIAL API EXPECTED POINTS + FDR FIXTURE DYNAMICS ---
players_df['ep_next'] = pd.to_numeric(players_df['ep_next'], errors='coerce').fillna(0.0)

# Build dynamic team fixture dictionary (GW1–GW10)
team_fixtures = {}
for f in fixtures_data:
    gw = f.get('event')
    if gw and 1 <= gw <= 10:
        team_fixtures.setdefault(f['team_h'], {})[gw] = f['team_h_difficulty']
        team_fixtures.setdefault(f['team_a'], {})[gw] = f['team_a_difficulty']

# Project expected points for GW1–GW10 scaling ep_next via FDR
for gw in range(1, 11):
    def calculate_gw_xp(row):
        base_ep = row['ep_next']
        team_id = row['team']
        
        # Get fixture difficulty rating for this team in the specified GW (Default 3 if blank)
        fdr = team_fixtures.get(team_id, {}).get(gw, 3)
        
        # FDR modifier: FDR 1 -> +20%, FDR 3 -> Baseline, FDR 5 -> -20%
        fixture_modifier = 1.0 + ((3 - fdr) * 0.10)
        
        return round(base_ep * fixture_modifier, 2)

    players_df[f'GW{gw}_xP'] = players_df.apply(calculate_gw_xp, axis=1)

players_df['display_label'] = players_df['web_name'] + " (" + players_df['team_short'] + ") - £" + players_df['now_cost'].astype(str) + "m"

# --- SIDEBAR CONTROLS ---
if st.sidebar.button("⚽ PL-Kameratene", type="tertiary", use_container_width=True):
    st.session_state.menu_selection = "📊 Dashboard Overview"
    st.rerun()

st.sidebar.markdown(f"**Current Gameweek:** GW{current_gw}")

selected_gw = st.sidebar.selectbox(
    "🎯 Select Target Gameweek", 
    options=[f"GW{i}" for i in range(1, 11)],
    index=0
)

selected_gw_col = f"{selected_gw}_xP"
players_df['xP'] = players_df[selected_gw_col]

# Synchronized navigation menu
menu_options = [
    "📊 Dashboard Overview", 
    "🛡️ My Squad & Pitch View", 
    "🔍 Player Explorer & Differentials"
]

menu = st.sidebar.radio(
    "Navigation", 
    options=menu_options,
    index=menu_options.index(st.session_state.menu_selection),
    key="nav_radio"
)

st.session_state.menu_selection = menu

st.sidebar.markdown("---")
manager_id_input = st.sidebar.text_input("Enter FPL Manager ID", value="475093")
use_manual_picker = st.sidebar.checkbox("🛠️ Pre-Season Pitch Builder", value=True)

# --- RE-ENGINEERED FPL PITCH VISUALIZER (NO OVERLAPS / FIXED PIXEL YSHIFT) ---
def generate_fpl_pitch(starting_11_df, bench_df, target_gw, captain_id):
    fig = go.Figure()

    # --- 1. PITCH GEOMETRY & BACKGROUND ---
    fig.add_shape(type="rect", x0=0, y0=20, x1=100, y1=140, 
                  fillcolor="#0a1a12", line=dict(color="#1f422e", width=2))
    
    fig.add_shape(type="rect", x0=4, y0=24, x1=96, y1=136, line=dict(color="#2e6345", width=2))
    
    fig.add_shape(type="line", x0=4, y0=80, x1=96, y1=80, line=dict(color="#2e6345", width=2))
    fig.add_shape(type="circle", x0=36, y0=68, x1=64, y1=92, line=dict(color="#2e6345", width=2))
    fig.add_shape(type="circle", x0=49, y0=79, x1=51, y1=81, fillcolor="#2e6345", line=dict(color="#2e6345"))
    
    fig.add_shape(type="rect", x0=22, y0=24, x1=78, y1=45, line=dict(color="#2e6345", width=2))
    fig.add_shape(type="rect", x0=36, y0=24, x1=64, y1=31, line=dict(color="#2e6345", width=2))
    
    fig.add_shape(type="rect", x0=22, y0=115, x1=78, y1=136, line=dict(color="#2e6345", width=2))
    fig.add_shape(type="rect", x0=36, y0=129, x1=64, y1=136, line=dict(color="#2e6345", width=2))

    fig.add_shape(type="rect", x0=0, y0=0, x1=100, y1=18, 
                  fillcolor="#060c08", line=dict(color="#1f422e", width=1.5))
    fig.add_annotation(x=4, y=15.5, text="<b>SUBSTITUTES BENCH</b>", showarrow=False, 
                       font=dict(color="#5a826b", size=10, family="Arial"), xanchor="left")

    # --- 2. POSITION Y-COORDINATES ---
    pos_y_map = {'GKP': 32, 'DEF': 58, 'MID': 88, 'FWD': 118}

    def render_player(x, y, player, is_bench=False):
        is_captain = (player['id'] == captain_id) and not is_bench
        
        card_bg = "#1f1800" if is_captain else "#11161d"
        card_border = "#FFD700" if is_captain else "#2B313E"
        pts_color = "#FFD700" if is_captain else "#00FF7F"
        node_bg = "#FFD700" if is_captain else "#37003c"
        
        capt_badge = " <b style='color:#FFD700;'>(C)</b>" if is_captain else ""
        
        # Jersey Node Circle
        fig.add_trace(go.Scatter(
            x=[x], y=[y],
            mode="markers+text",
            marker=dict(
                size=22 if not is_bench else 16, 
                color=node_bg, 
                line=dict(width=2, color=card_border)
            ),
            text=["<b>C</b>" if is_captain else ""],
            textposition="middle center",
            textfont=dict(color="#000000" if is_captain else "#FFFFFF", size=11, family="Arial"),
            hoverinfo="text",
            hovertext=f"{player['web_name']} (£{player['now_cost']}m) - {player['xP']} pts",
            showlegend=False
        ))

        # Compact Player Card
        card_text = (
            f"<b>{player['web_name']}</b>{capt_badge}<br>"
            f"<span style='color:{pts_color}; font-weight:bold;'>{player['xP']} pts</span>"
            f"<span style='color:#8b949e; font-size:9px;'> | £{player['now_cost']}m</span>"
        ) if not is_bench else (
            f"<b>{player['web_name']}</b><br>"
            f"<span style='color:#00FF7F;'>{player['xP']} pts</span>"
        )

        fig.add_annotation(
            x=x, y=y,
            yshift=-32 if not is_bench else -24,
            text=card_text,
            showarrow=False,
            font=dict(family="Arial", size=10),
            align="center",
            bgcolor=card_bg,
            bordercolor=card_border,
            borderwidth=1,
            borderpad=3
        )

    # --- 3. RENDER STARTING XI ---
    for pos, y_val in pos_y_map.items():
        pos_players = starting_11_df[starting_11_df['position'] == pos]
        count = len(pos_players)
        
        if count > 0:
            x_coords = [8 + (84 * (i + 1) / (count + 1)) for i in range(count)]
            for idx, (_, player) in enumerate(pos_players.iterrows()):
                render_player(x_coords[idx], y_val, player, is_bench=False)

    # --- 4. RENDER BENCH ---
    if not bench_df.empty:
        b_count = len(bench_df)
        b_x_coords = [10 + (80 * (i + 1) / (b_count + 1)) for i in range(b_count)]
        for idx, (_, player) in enumerate(bench_df.iterrows()):
            render_player(b_x_coords[idx], 8, player, is_bench=True)

    # --- 5. CANVAS SETTINGS ---
    fig.update_layout(
        xaxis=dict(range=[-2, 102], showgrid=False, zeroline=False, showticklabels=False, fixedrange=True),
        yaxis=dict(
            range=[-2, 142], 
            showgrid=False, 
            zeroline=False, 
            showticklabels=False, 
            fixedrange=True,
            scaleanchor="x",
            scaleratio=1.28
        ),
        height=800,
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="#0E1117",
        paper_bgcolor="#0E1117"
    )
    return fig

# --- DASHBOARD OVERVIEW PAGE ---
if menu == "📊 Dashboard Overview":
    st.title(f"📊 PL-Kameratene Dashboard ({selected_gw})")

    col_gkp, col_def, col_mid, col_fwd = st.columns(4)
    
    top_gkp = players_df[players_df['position'] == 'GKP'].sort_values(by='xP', ascending=False).iloc[0]
    top_def = players_df[players_df['position'] == 'DEF'].sort_values(by='xP', ascending=False).iloc[0]
    top_mid = players_df[players_df['position'] == 'MID'].sort_values(by='xP', ascending=False).iloc[0]
    top_fwd = players_df[players_df['position'] == 'FWD'].sort_values(by='xP', ascending=False).iloc[0]

    col_gkp.metric("🧤 Top Goalkeeper", top_gkp['web_name'], f"{top_gkp['xP']} pts")
    col_def.metric("🛡️ Top Defender", top_def['web_name'], f"{top_def['xP']} pts")
    col_mid.metric("⚙️ Top Midfielder", top_mid['web_name'], f"{top_mid['xP']} pts")
    col_fwd.metric("🎯 Top Forward", top_fwd['web_name'], f"{top_fwd['xP']} pts")

    st.markdown("---")
    st.subheader(f"🚀 Top 15 Projected Scorers for {selected_gw}")
    st.caption("👇 Select a player from the dropdown or click a bar in the chart to inspect stats!")

    top_15 = players_df.sort_values(by='xP', ascending=False).head(15).copy()

    fig = px.bar(
        top_15, x='web_name', y='xP', color='position', text='xP', template='plotly_dark',
        hover_data=['team_name', 'now_cost', 'selected_by_percent', 'form'],
        color_discrete_map={'GKP': '#FFD700', 'DEF': '#00BFFF', 'MID': '#00FF7F', 'FWD': '#FF4500'}
    )
    fig.update_traces(texttemplate='%{text}', textposition='outside')
    fig.update_layout(xaxis_title="Player", yaxis_title=f"Expected Points in {selected_gw}", height=450)
    
    chart_selection = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points")

    selected_player_name = None
    if chart_selection and "selection" in chart_selection and chart_selection["selection"]["points"]:
        point_data = chart_selection["selection"]["points"][0]
        selected_player_name = point_data.get("x")
        
    col_select, _ = st.columns([1, 2])
    with col_select:
        chosen_player = st.selectbox(
            "🔍 Inspect Player Stats:",
            options=top_15['web_name'].tolist(),
            index=top_15['web_name'].tolist().index(selected_player_name) if selected_player_name in top_15['web_name'].tolist() else 0
        )

    p_data = players_df[players_df['web_name'] == chosen_player].iloc[0]
    
    st.markdown(f"### 📋 {p_data['web_name']} ({p_data['team_name']}) — Performance Stats")
    
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Position", p_data['position'])
    c2.metric("Cost", f"£{p_data['now_cost']}m")
    c3.metric(f"Projected xP ({selected_gw})", f"{p_data['xP']} pts")
    c4.metric("Avg Minutes", f"{int(p_data['avg_minutes'])} mins")
    c5.metric("Ownership", f"{p_data['selected_by_percent']}%")

    st.markdown("#### 📊 Official FPL Metrics Breakdown")
    
    fpl_stats_table = pd.DataFrame([{
        "Official ep_next": p_data.get('ep_next', 0),
        "GS": p_data.get('goals_scored', 0),
        "A": p_data.get('assists', 0),
        "xG": f"{p_data.get('expected_goals', 0):.2f}",
        "xA": f"{p_data.get('expected_assists', 0):.2f}",
        "xGI": f"{p_data.get('expected_goal_involvements', 0):.2f}",
        "CS": p_data.get('clean_sheets', 0),
        "GC": p_data.get('goals_conceded', 0),
        "xGC": f"{p_data.get('expected_goals_conceded', 0):.2f}",
        "S": p_data.get('saves', 0),
        "BP": p_data.get('bonus', 0),
        "BPS": p_data.get('bps', 0),
        "I": p_data.get('influence', 0),
        "C": p_data.get('creativity', 0),
        "T": p_data.get('threat', 0),
        "YC": p_data.get('yellow_cards', 0),
        "RC": p_data.get('red_cards', 0),
        "OG": p_data.get('own_goals', 0),
        "PM": p_data.get('penalties_missed', 0),
        "PS": p_data.get('penalties_saved', 0)
    }])
    
    st.dataframe(fpl_stats_table, use_container_width=True, hide_index=True)

# --- SQUAD & PITCH VIEW PAGE ---
elif menu == "🛡️ My Squad & Pitch View":
    st.title("🛡️ My Squad, Bench & Pitch View")

    starting_11 = pd.DataFrame()
    bench_df = pd.DataFrame()

    if use_manual_picker:
        st.info("💡 **Pre-Season Mode:** Pick your squad below!")
        
        gkps = players_df[players_df['position'] == 'GKP']
        defs = players_df[players_df['position'] == 'DEF']
        mids = players_df[players_df['position'] == 'MID']
        fwds = players_df[players_df['position'] == 'FWD']

        col_gkp, col_def, col_mid, col_fwd = st.columns(4)

        with col_gkp:
            st.markdown("### 🧤 Goalkeepers (2)")
            selected_gkps = st.multiselect("GKP", options=gkps['id'].tolist(), default=gkps['id'].tolist()[:2], format_func=lambda x: gkps[gkps['id']==x]['display_label'].values[0], max_selections=2)
            
        with col_def:
            st.markdown("### 🛡️ Defenders (5)")
            selected_defs = st.multiselect("DEF", options=defs['id'].tolist(), default=defs['id'].tolist()[:5], format_func=lambda x: defs[defs['id']==x]['display_label'].values[0], max_selections=5)

        with col_mid:
            st.markdown("### ⚙️ Midfielders (5)")
            selected_mids = st.multiselect("MID", options=mids['id'].tolist(), default=mids['id'].tolist()[:5], format_func=lambda x: mids[mids['id']==x]['display_label'].values[0], max_selections=5)

        with col_fwd:
            st.markdown("### 🎯 Forwards (3)")
            selected_fwds = st.multiselect("FWD", options=fwds['id'].tolist(), default=fwds['id'].tolist()[:3], format_func=lambda x: fwds[fwds['id']==x]['display_label'].values[0], max_selections=3)

        all_selected_ids = selected_gkps + selected_defs + selected_mids + selected_fwds
        full_squad = players_df[players_df['id'].isin(all_selected_ids)].copy()

        if len(full_squad) >= 11:
            gkp_sorted = full_squad[full_squad['position'] == 'GKP'].sort_values(by='xP', ascending=False)
            def_sorted = full_squad[full_squad['position'] == 'DEF'].sort_values(by='xP', ascending=False)
            mid_sorted = full_squad[full_squad['position'] == 'MID'].sort_values(by='xP', ascending=False)
            fwd_sorted = full_squad[full_squad['position'] == 'FWD'].sort_values(by='xP', ascending=False)

            starting_gkp = gkp_sorted.head(1)
            starting_def = def_sorted.head(min(4, len(def_sorted)))
            starting_mid = mid_sorted.head(min(4, len(mid_sorted)))
            starting_fwd = fwd_sorted.head(min(2, len(fwd_sorted)))

            starting_11 = pd.concat([starting_gkp, starting_def, starting_mid, starting_fwd])
            bench_df = full_squad[~full_squad['id'].isin(starting_11['id'])]
        else:
            starting_11 = full_squad

    else:
        if manager_id_input:
            user_data = fetch_user_squad(manager_id_input, current_gw)
            if user_data:
                picks = user_data.get('picks', [])
                my_player_ids = [p['element'] for p in picks]
                my_squad_df = players_df[players_df['id'].isin(my_player_ids)].copy()
                pick_order = {p['element']: p['position'] for p in picks}
                my_squad_df['squad_order'] = my_squad_df['id'].map(pick_order)
                
                starting_11 = my_squad_df[my_squad_df['squad_order'] <= 11]
                bench_df = my_squad_df[my_squad_df['squad_order'] > 11]

    if not starting_11.empty:
        captain_row = starting_11.sort_values(by='xP', ascending=False).iloc[0]
        captain_id = captain_row['id']
        
        total_xp = (starting_11['xP'].sum() + captain_row['xP']).round(2)
        total_cost = (starting_11['now_cost'].sum() + (bench_df['now_cost'].sum() if not bench_df.empty else 0)).round(1)
        
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("Squad Size", f"{len(starting_11)} Start / {len(bench_df)} Bench")
        m_col2.metric("Total Squad Cost", f"£{total_cost:.1f}m")
        m_col3.metric("Captain Pick 👑", captain_row['web_name'], f"{captain_row['xP'] * 2:.1f} pts (x2)")
        m_col4.metric("Projected GW Points", f"{total_xp:.2f} pts")

        st.subheader(f"🏟️ Pitch & Bench View — {selected_gw}")
        pitch_fig = generate_fpl_pitch(starting_11, bench_df, selected_gw, captain_id)
        st.plotly_chart(pitch_fig, use_container_width=True)

        st.markdown("---")
        st.subheader("📅 Single Gameweek Breakdown (GW1 – GW10)")
        gw_cols = [f'GW{i}_xP' for i in range(1, 11)]
        squad_breakdown = pd.concat([starting_11, bench_df])[['web_name', 'position', 'team_short', 'now_cost'] + gw_cols].copy()
        squad_breakdown.columns = ['Player', 'Pos', 'Team', 'Cost'] + [f'GW{i}' for i in range(1, 11)]
        st.dataframe(squad_breakdown, use_container_width=True)

# --- PLAYER EXPLORER PAGE ---
elif menu == "🔍 Player Explorer & Differentials":
    st.title("🔍 Player Explorer & Differential Finder")
    
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        only_differentials = st.checkbox("🌟 Show Differentials Only (< 10% Ownership)", value=False)
    with col_f2:
        pos_filter = st.selectbox("Filter by Position", options=["All", "GKP", "DEF", "MID", "FWD"])

    explorer_df = players_df[['web_name', 'team_short', 'position', 'now_cost', 'selected_by_percent', selected_gw_col, 'ep_next', 'avg_minutes']].copy()
    
    if only_differentials:
        explorer_df = explorer_df[explorer_df['selected_by_percent'] < 10.0]
    if pos_filter != "All":
        explorer_df = explorer_df[explorer_df['position'] == pos_filter]

    explorer_df = explorer_df.rename(columns={
        'web_name': 'Player',
        'team_short': 'Team',
        'position': 'Pos',
        'now_cost': 'Cost (£m)',
        'selected_by_percent': 'Ownership (%)',
        selected_gw_col: f'Active ({selected_gw})',
        'ep_next': 'Official ep_next',
        'avg_minutes': 'Avg Mins'
    }).sort_values(by=f'Active ({selected_gw})', ascending=False)
    
    st.dataframe(explorer_df, use_container_width=True)
