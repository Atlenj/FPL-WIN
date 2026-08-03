import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go

# --- PAGE CONFIGURATION & DARK THEME SETUP ---
st.set_page_config(
    page_title="FPL AI Coach Pro",
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
    </style>
""", unsafe_allow_html=True)

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

# Extract official FPL stats cleanly
players_df['expected_goals'] = pd.to_numeric(players_df.get('expected_goals', 0), errors='coerce').fillna(0.0)
players_df['expected_assists'] = pd.to_numeric(players_df.get('expected_assists', 0), errors='coerce').fillna(0.0)
players_df['expected_goal_involvements'] = pd.to_numeric(players_df.get('expected_goal_involvements', 0), errors='coerce').fillna(0.0)
players_df['expected_goals_conceded'] = pd.to_numeric(players_df.get('expected_goals_conceded', 0), errors='coerce').fillna(0.0)

# --- REFINED XP FORMULA WITH PER-GAME XG/XA & MINUTES WEIGHTING ---
players_df['form'] = pd.to_numeric(players_df['form'], errors='coerce').fillna(0)
players_df['points_per_game'] = pd.to_numeric(players_df['points_per_game'], errors='coerce').fillna(0)
players_df['chance_of_playing_next_round'] = players_df['chance_of_playing_next_round'].fillna(100) / 100.0

players_df['minutes'] = pd.to_numeric(players_df['minutes'], errors='coerce').fillna(0)
players_df['games_played'] = (players_df['minutes'] / 90.0).clip(lower=1.0)
players_df['avg_minutes'] = players_df['minutes'] / players_df['games_played']

minutes_factor = (players_df['avg_minutes'] / 90.0).clip(upper=1.0)

players_df['xg_per_game'] = players_df['expected_goals'] / players_df['games_played']
players_df['xa_per_game'] = players_df['expected_assists'] / players_df['games_played']

xg_xa_threat_per_game = (players_df['xg_per_game'] * 4.0) + (players_df['xa_per_game'] * 3.0)

base_xp = (
    (players_df['form'] * 0.35) + 
    (players_df['points_per_game'] * 0.35) + 
    (xg_xa_threat_per_game * 0.20) + 
    (players_df['chance_of_playing_next_round'] * 0.5)
) * minutes_factor

for gw in range(1, 11):
    decay_factor = 1.0 - ((gw - 1) * 0.015)
    players_df[f'GW{gw}_xP'] = (base_xp * decay_factor).round(2)

players_df['display_label'] = players_df['web_name'] + " (" + players_df['team_short'] + ") - £" + players_df['now_cost'].astype(str) + "m"

# --- SIDEBAR CONTROLS ---
st.sidebar.title("⚽ FPL AI Coach Pro")
st.sidebar.markdown(f"**Current Gameweek:** GW{current_gw}")

selected_gw = st.sidebar.selectbox(
    "🎯 Select Target Gameweek", 
    options=[f"GW{i}" for i in range(1, 11)],
    index=0
)

selected_gw_col = f"{selected_gw}_xP"
players_df['xP'] = players_df[selected_gw_col]

# --- PITCH GENERATOR FUNCTION ---
def generate_fpl_pitch(starting_11_df, bench_df, target_gw, captain_id):
    fig = go.Figure()

    fig.add_shape(type="rect", x0=0, y0=18, x1=100, y1=100, 
                  fillcolor="#12251a", line=dict(color="#2e593f", width=2))
    
    fig.add_shape(type="rect", x0=3, y0=21, x1=97, y1=97, line=dict(color="#458a60", width=2))
    fig.add_shape(type="line", x0=3, y0=59, x1=97, y1=59, line=dict(color="#458a60", width=2))
    fig.add_shape(type="circle", x0=38, y0=49, x1=62, y1=69, line=dict(color="#458a60", width=2))
    fig.add_shape(type="circle", x0=49.2, y0=58.2, x1=50.8, y1=59.8, fillcolor="#458a60", line=dict(color="#458a60"))
    fig.add_shape(type="rect", x0=22, y0=21, x1=78, y1=38, line=dict(color="#458a60", width=2))
    fig.add_shape(type="rect", x0=22, y0=80, x1=78, y1=97, line=dict(color="#458a60", width=2))

    fig.add_shape(type="rect", x0=0, y0=0, x1=100, y1=16, 
                  fillcolor="#0b1610", line=dict(color="#1f3829", width=2))
    fig.add_shape(type="line", x0=0, y0=16, x1=100, y1=16, line=dict(color="#2e593f", width=1, dash="dash"))
    fig.add_annotation(x=5, y=14, text="<b>SUBSTITUTES BENCH</b>", showarrow=False, font=dict(color="#8fa396", size=10), xanchor="left")

    pos_y_map = {'GKP': 27, 'DEF': 47, 'MID': 70, 'FWD': 89}

    for pos, y_val in pos_y_map.items():
        pos_players = starting_11_df[starting_11_df['position'] == pos]
        count = len(pos_players)
        
        if count > 0:
            x_coords = [3 + (94 * (i + 1) / (count + 1)) for i in range(count)]
            
            for idx, (_, player) in enumerate(pos_players.iterrows()):
                x_val = x_coords[idx]
                is_captain = (player['id'] == captain_id)
                
                badge_label = " (C)" if is_captain else ""
                border_color = "#FFD700" if is_captain else "#00FF7F"
                marker_color = "#5c4000" if is_captain else "#37003c"

                card_text = (
                    f"<b>{player['web_name']}{badge_label}</b><br>"
                    f"<span style='font-size:11px; color:#00FF7F;'>{player['xP']} pts</span>"
                    f" | <span style='font-size:10px; color:#B0B0B0;'>£{player['now_cost']}m</span>"
                )
                
                fig.add_trace(go.Scatter(
                    x=[x_val], y=[y_val],
                    mode="markers+text",
                    marker=dict(size=30, color=marker_color, line=dict(width=3, color=border_color)),
                    text=[card_text], textposition="bottom center",
                    hoverinfo="text", showlegend=False
                ))

    if not bench_df.empty:
        bench_count = len(bench_df)
        bench_x_coords = [10 + (80 * (i + 1) / (bench_count + 1)) for i in range(bench_count)]
        
        for idx, (_, player) in enumerate(bench_df.iterrows()):
            x_val = bench_x_coords[idx]
            card_text = (
                f"<b>{player['web_name']} (Sub)</b><br>"
                f"<span style='font-size:10px; color:#00FF7F;'>{player['xP']} pts</span>"
            )
            fig.add_trace(go.Scatter(
                x=[x_val], y=[7],
                mode="markers+text",
                marker=dict(size=22, color="#1b2a22", line=dict(width=1.5, color="#6b8e7b")),
                text=[card_text], textposition="bottom center",
                hoverinfo="text", showlegend=False
            ))

    fig.update_layout(
        xaxis=dict(range=[0, 100], showgrid=False, zeroline=False, showticklabels=False, fixedrange=True),
        yaxis=dict(range=[0, 100], showgrid=False, zeroline=False, showticklabels=False, fixedrange=True),
        height=720,
        margin=dict(l=5, r=5, t=5, b=5),
        plot_bgcolor="#12251a",
        paper_bgcolor="#0E1117"
    )
    return fig

# --- NAVIGATION ROUTING ---
menu = st.sidebar.radio(
    "Navigation", 
    ["📊 Dashboard Overview", "🛡️ My Squad & Pitch View", "🔍 Player Explorer & Differentials"]
)

st.sidebar.markdown("---")
manager_id_input = st.sidebar.text_input("Enter FPL Manager ID", value="475093")
use_manual_picker = st.sidebar.checkbox("🛠️ Pre-Season Pitch Builder", value=True)

# --- DASHBOARD OVERVIEW PAGE ---
if menu == "📊 Dashboard Overview":
    st.title(f"📊 FPL Dashboard & Insights ({selected_gw})")

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
    
    st.markdown(f"### 📋 {p_data['web_name']} ({p_data['team_name']}) — Complete Performance Stats")
    
    # 1. Summary Header Bar
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Position", p_data['position'])
    c2.metric("Cost", f"£{p_data['now_cost']}m")
    c3.metric(f"Projected xP ({selected_gw})", f"{p_data['xP']} pts")
    c4.metric("Avg Minutes", f"{int(p_data['avg_minutes'])} mins")
    c5.metric("Ownership", f"{p_data['selected_by_percent']}%")

    st.markdown("#### 📊 Official FPL Metrics Breakdown")
    
    # 2. Compact FPL Stats Table (GS, A, xG, xA, xGI, CS, GC, xGC, BPS, Yellow/Red Cards, etc.)
    fpl_stats_table = pd.DataFrame([{
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

    explorer_df = players_df[['web_name', 'team_short', 'position', 'now_cost', 'selected_by_percent', selected_gw_col, 'form', 'avg_minutes']].copy()
    
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
        'form': 'Form',
        'avg_minutes': 'Avg Mins'
    }).sort_values(by=f'Active ({selected_gw})', ascending=False)
    
    st.dataframe(explorer_df, use_container_width=True)
