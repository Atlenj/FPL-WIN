import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go

# --- PAGE CONFIGURATION & DARK THEME SETUP ---
st.set_page_config(
    page_title="FPL AI Coach",
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
    .stat-card {
        background: #1E222D;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #00FF7F;
        margin-bottom: 20px;
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
    
    # Check manager validity
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
pos_map = dict(zip(positions_df['id'], positions_df['singular_name_short']))

players_df['team_name'] = players_df['team'].map(team_map)
players_df['position'] = players_df['element_type'].map(pos_map)
players_df['now_cost'] = players_df['now_cost'] / 10.0

# Numeric Types
players_df['form'] = pd.to_numeric(players_df['form'], errors='coerce').fillna(0)
players_df['points_per_game'] = pd.to_numeric(players_df['points_per_game'], errors='coerce').fillna(0)
players_df['chance_of_playing_next_round'] = players_df['chance_of_playing_next_round'].fillna(100) / 100.0

# Base Expected Points for single Gameweek
base_xp = (
    (players_df['form'] * 0.45) + 
    (players_df['points_per_game'] * 0.40) + 
    (players_df['chance_of_playing_next_round'] * 1.5)
)

# Generate single-GW predictions for GW1 through GW10
# (Includes slight realistic fixture variance decay per gameweek)
for gw in range(1, 11):
    decay_factor = 1.0 - ((gw - 1) * 0.015)  # Slight form decay further into the future
    players_df[f'GW{gw}_xP'] = (base_xp * decay_factor).round(2)

# Add display label for select boxes
players_df['display_label'] = players_df['web_name'] + " (" + players_df['team_name'] + ") - £" + players_df['now_cost'].astype(str) + "m"

# --- SIDEBAR CONTROLS ---
st.sidebar.title("⚽ FPL AI Coach")
st.sidebar.markdown(f"**Current Gameweek:** GW{current_gw}")

# Single Gameweek Selector
selected_gw = st.sidebar.selectbox(
    "🎯 Select Target Gameweek", 
    options=[f"GW{i}" for i in range(1, 11)],
    index=0,
    help="Choose which single Gameweek to view predictions for."
)

# Active single-GW prediction column
selected_gw_col = f"{selected_gw}_xP"
players_df['xP'] = players_df[selected_gw_col]

# --- ENHANCED PITCH GENERATOR FUNCTION ---
def generate_fpl_pitch(starting_11_df, target_gw):
    fig = go.Figure()

    # Pitch surface (Dark tactical green gradient tone)
    fig.add_shape(type="rect", x0=0, y0=0, x1=100, y1=100, 
                  fillcolor="#12251a", line=dict(color="#2e593f", width=2))
    
    # Outer pitch boundary line
    fig.add_shape(type="rect", x0=3, y0=3, x1=97, y1=97, 
                  line=dict(color="#458a60", width=2))

    # Halfway line
    fig.add_shape(type="line", x0=3, y0=50, x1=97, y1=50, 
                  line=dict(color="#458a60", width=2))

    # Center circle & spot
    fig.add_shape(type="circle", x0=38, y0=40, x1=62, y1=60, 
                  line=dict(color="#458a60", width=2))
    fig.add_shape(type="circle", x0=49.2, y0=49.2, x1=50.8, y1=50.8, 
                  fillcolor="#458a60", line=dict(color="#458a60"))

    # Penalty box (Bottom - GK area)
    fig.add_shape(type="rect", x0=22, y0=3, x1=78, y1=20, 
                  line=dict(color="#458a60", width=2))
    fig.add_shape(type="rect", x0=36, y0=3, x1=64, y1=9, 
                  line=dict(color="#458a60", width=1.5))

    # Penalty box (Top - Opponent area)
    fig.add_shape(type="rect", x0=22, y0=80, x1=78, y1=97, 
                  line=dict(color="#458a60", width=2))
    fig.add_shape(type="rect", x0=36, y0=91, x1=64, y1=97, 
                  line=dict(color="#458a60", width=1.5))

    # Dynamic Position Y-coordinates
    pos_y_map = {'GKP': 11, 'DEF': 32, 'MID': 60, 'FWD': 84}

    # Map positions and add player nodes
    for pos, y_val in pos_y_map.items():
        pos_players = starting_11_df[starting_11_df['position'] == pos]
        count = len(pos_players)
        
        if count > 0:
            x_coords = [3 + (94 * (i + 1) / (count + 1)) for i in range(count)]
            
            for idx, (_, player) in enumerate(pos_players.iterrows()):
                x_val = x_coords[idx]
                
                # HTML formatted pitch badge card displaying SINGLE GW points
                card_text = (
                    f"<b>{player['web_name']}</b><br>"
                    f"<span style='font-size:11px; color:#00FF7F;'>{player['xP']} pts ({target_gw})</span>"
                    f" | <span style='font-size:10px; color:#B0B0B0;'>£{player['now_cost']}m</span>"
                )
                
                # Outer glow marker (Jersey node)
                fig.add_trace(go.Scatter(
                    x=[x_val],
                    y=[y_val],
                    mode="markers+text",
                    marker=dict(
                        size=28, 
                        color="#37003c", 
                        line=dict(width=2.5, color="#00FF7F")
                    ),
                    text=[card_text],
                    textposition="bottom center",
                    hoverinfo="text",
                    showlegend=False
                ))

    fig.update_layout(
        xaxis=dict(range=[0, 100], showgrid=False, zeroline=False, showticklabels=False, fixedrange=True),
        yaxis=dict(range=[0, 100], showgrid=False, zeroline=False, showticklabels=False, fixedrange=True),
        height=680,
        margin=dict(l=5, r=5, t=5, b=5),
        plot_bgcolor="#12251a",
        paper_bgcolor="#0E1117"
    )
    return fig

# --- NAVIGATION ROUTING ---
menu = st.sidebar.radio(
    "Navigation", 
    ["📊 Dashboard Overview", "🛡️ My Squad & Pitch View", "🔍 Player Explorer"]
)

st.sidebar.markdown("---")
manager_id_input = st.sidebar.text_input("Enter FPL Manager ID", value="475093")
use_manual_picker = st.sidebar.checkbox("🛠️ Pre-Season Pitch Builder", value=True, help="Check this to manually select your 11 players before Gameweek 1 starts!")

if menu == "📊 Dashboard Overview":
    st.title(f"📊 Single-Gameweek Insights ({selected_gw})")

    col1, col2, col3, col4 = st.columns(4)
    top_overall = players_df.sort_values(by='xP', ascending=False).iloc[0]
    top_mid = players_df[players_df['position'] == 'MID'].sort_values(by='xP', ascending=False).iloc[0]
    top_def = players_df[players_df['position'] == 'DEF'].sort_values(by='xP', ascending=False).iloc[0]
    top_val = players_df[players_df['minutes'] > 450].sort_values(by='xP', ascending=False).iloc[0]

    col1.metric(f"Top Pick ({selected_gw})", top_overall['web_name'], f"{top_overall['xP']} pts")
    col2.metric(f"Top Midfielder", top_mid['web_name'], f"{top_mid['xP']} pts")
    col3.metric(f"Top Defender", top_def['web_name'], f"{top_def['xP']} pts")
    col4.metric("Top Form Pick", top_val['web_name'], f"£{top_val['now_cost']}m")

    st.markdown("---")
    st.subheader(f"🚀 Top 15 Projected Scorers for {selected_gw}")
    top_15 = players_df.sort_values(by='xP', ascending=False).head(15)

    fig = px.bar(
        top_15, x='web_name', y='xP', color='position', text='xP', template='plotly_dark',
        color_discrete_map={'GKP': '#FFD700', 'DEF': '#00BFFF', 'MID': '#00FF7F', 'FFWD': '#FF4500'}
    )
    fig.update_traces(texttemplate='%{text}', textposition='outside')
    fig.update_layout(xaxis_title="Player", yaxis_title=f"Expected Points in {selected_gw}", height=450)
    st.plotly_chart(fig, use_container_width=True)

elif menu == "🛡️ My Squad & Pitch View":
    st.title("🛡️ My Squad & Pitch View")

    starting_11 = pd.DataFrame()

    # Manual Selection Mode (Pre-Season)
    if use_manual_picker:
        st.info("💡 **Pre-Season Mode:** Pick your starting 11 below to preview your team on the pitch!")
        
        gkps = players_df[players_df['position'] == 'GKP']
        defs = players_df[players_df['position'] == 'DEF']
        mids = players_df[players_df['position'] == 'MID']
        fwds = players_df[players_df['position'] == 'FWD']

        col_gkp, col_def, col_mid, col_fwd = st.columns(4)

        with col_gkp:
            st.markdown("### 🧤 Goalkeeper (1)")
            selected_gkp = st.selectbox(
                "GKP 1", 
                options=gkps['id'].tolist(), 
                index=0,
                format_func=lambda x: gkps[gkps['id']==x]['display_label'].values[0]
            )
            
        with col_def:
            st.markdown("### 🛡️ Defenders (3-5)")
            default_defs = defs['id'].tolist()[:4] if len(defs) >= 4 else defs['id'].tolist()
            selected_defs = st.multiselect(
                "Defenders", 
                options=defs['id'].tolist(), 
                default=default_defs, 
                format_func=lambda x: defs[defs['id']==x]['display_label'].values[0], 
                max_selections=5
            )

        with col_mid:
            st.markdown("### ⚙️ Midfielders (3-5)")
            default_mids = mids['id'].tolist()[:4] if len(mids) >= 4 else mids['id'].tolist()
            selected_mids = st.multiselect(
                "Midfielders", 
                options=mids['id'].tolist(), 
                default=default_mids, 
                format_func=lambda x: mids[mids['id']==x]['display_label'].values[0], 
                max_selections=5
            )

        with col_fwd:
            st.markdown("### 🎯 Forwards (1-3)")
            default_fwds = fwds['id'].tolist()[:2] if len(fwds) >= 2 else fwds['id'].tolist()
            selected_fwds = st.multiselect(
                "Forwards", 
                options=fwds['id'].tolist(), 
                default=default_fwds, 
                format_func=lambda x: fwds[fwds['id']==x]['display_label'].values[0], 
                max_selections=3
            )

        selected_ids = [selected_gkp] + selected_defs + selected_mids + selected_fwds
        starting_11 = players_df[players_df['id'].isin(selected_ids)].copy()

    # API Automatic Selection Mode
    else:
        if not manager_id_input:
            st.info("👈 Enter your FPL Manager ID in the sidebar.")
        else:
            user_data = fetch_user_squad(manager_id_input, current_gw)
            if not user_data:
                st.warning("⚠️ API squad lookup is currently locked for pre-season. Toggle '🛠️ Pre-Season Pitch Builder' in the sidebar to manually select your squad!")
            else:
                picks = user_data.get('picks', [])
                my_player_ids = [p['element'] for p in picks]
                my_squad_df = players_df[players_df['id'].isin(my_player_ids)].copy()
                pick_order = {p['element']: p['position'] for p in picks}
                my_squad_df['squad_order'] = my_squad_df['id'].map(pick_order)
                my_squad_df = my_squad_df.sort_values(by='squad_order')
                starting_11 = my_squad_df[my_squad_df['squad_order'] <= 11]

    # Render Pitch & Metrics if starting XI selected
    if not starting_11.empty:
        total_xp = starting_11['xP'].sum().round(2)
        total_cost = starting_11['now_cost'].sum().round(1)
        
        m_col1, m_col2, m_col3 = st.columns(3)
        m_col1.metric("Selected Players", len(starting_11))
        m_col2.metric("Starting XI Cost", f"£{total_cost:.1f}m")
        m_col3.metric(f"Predicted Points ({selected_gw})", f"{total_xp:.2f} pts")

        st.subheader(f"🏟️ Pitch View — {selected_gw} Predictions")
        pitch_fig = generate_fpl_pitch(starting_11, selected_gw)
        st.plotly_chart(pitch_fig, use_container_width=True)

        # Gameweek 1 to 10 Individual Breakdown Table
        st.markdown("---")
        st.subheader("📅 Single Gameweek Breakdown (GW1 – GW10)")
        gw_cols = [f'GW{i}_xP' for i in range(1, 11)]
        squad_breakdown = starting_11[['web_name', 'position', 'team_name'] + gw_cols].copy()
        squad_breakdown.columns = ['Player', 'Pos', 'Team'] + [f'GW{i}' for i in range(1, 11)]
        st.dataframe(squad_breakdown, use_container_width=True)

elif menu == "🔍 Player Explorer":
    st.title("🔍 Player Comparison")
    st.markdown("*(Showing predicted points for single Gameweeks GW1 through GW10)*")
    
    gw_cols = [f'GW{i}_xP' for i in range(1, 11)]
    explorer_df = players_df[['web_name', 'team_name', 'position', 'now_cost', selected_gw_col] + gw_cols].copy()
    
    col_rename = {
        'web_name': 'Player',
        'team_name': 'Team',
        'position': 'Pos',
        'now_cost': 'Cost (£m)',
        selected_gw_col: f'Active ({selected_gw})'
    }
    for i in range(1, 11):
        col_rename[f'GW{i}_xP'] = f'GW{i}'
        
    explorer_df = explorer_df.rename(columns=col_rename).sort_values(by=f'Active ({selected_gw})', ascending=False)
    st.dataframe(explorer_df, use_container_width=True)
