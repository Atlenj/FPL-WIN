import streamlit as st
import pandas as pd
import requests
import plotly.express as px

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
    .css-1r6slb0, .css-12w0qpk {
        background-color: #1E222D;
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

# --- API DATA FETCHING (CACHED) ---
@st.cache_data(ttl=3600)
def load_fpl_bootstrap():
    url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None

def fetch_user_squad(manager_id, current_gw):
    url = f"https://fantasy.premierleague.com/api/entry/{manager_id}/event/{current_gw}/picks/"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None

# Load base data
raw_data = load_fpl_bootstrap()

if not raw_data:
    st.error("⚠️ Failed to load data from the official FPL API. Please refresh or try again later.")
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
        current_gw = event['id'] - 1
        break

# Mappings
team_map = dict(zip(teams_df['id'], teams_df['name']))
pos_map = dict(zip(positions_df['id'], positions_df['singular_name_short']))

players_df['team_name'] = players_df['team'].map(team_map)
players_df['position'] = players_df['element_type'].map(pos_map)
players_df['now_cost'] = players_df['now_cost'] / 10.0

# Ensure numeric types
players_df['form'] = pd.to_numeric(players_df['form'], errors='coerce').fillna(0)
players_df['points_per_game'] = pd.to_numeric(players_df['points_per_game'], errors='coerce').fillna(0)
players_df['selected_by_percent'] = pd.to_numeric(players_df['selected_by_percent'], errors='coerce').fillna(0)
players_df['chance_of_playing_next_round'] = players_df['chance_of_playing_next_round'].fillna(100) / 100.0

# Expected Points (xP) Model Calculation
players_df['xP'] = (
    (players_df['form'] * 0.50) + 
    (players_df['points_per_game'] * 0.35) + 
    (players_df['chance_of_playing_next_round'] * 1.5)
).round(2)

# --- SIDEBAR & NAVIGATION ---
st.sidebar.title("⚽ FPL AI Coach")
st.sidebar.markdown(f"**Current Gameweek:** GW{current_gw}")

menu = st.sidebar.radio(
    "Navigation", 
    ["📊 Dashboard Overview", "🛡️ My Squad & Coach", "🔍 Player Explorer", "⚔️ Team & Fixture Analytics"]
)

st.sidebar.markdown("---")
manager_id_input = st.sidebar.text_input("Enter FPL Manager ID", placeholder="e.g. 1234567")

# --- NAVIGATION ROUTING ---

# 1. DASHBOARD OVERVIEW
if menu == "📊 Dashboard Overview":
    st.title("📊 Gameweek Projections & Insights")
    st.markdown("Top statistical picks for the upcoming Gameweek.")

    # Key Metrics
    col1, col2, col3, col4 = st.columns(4)
    top_overall = players_df.sort_values(by='xP', ascending=False).iloc[0]
    top_mid = players_df[players_df['position'] == 'MID'].sort_values(by='xP', ascending=False).iloc[0]
    top_def = players_df[players_df['position'] == 'DEF'].sort_values(by='xP', ascending=False).iloc[0]
    top_val = players_df[players_df['minutes'] > 450].sort_values(by='xP', ascending=False).iloc[0]

    col1.metric("Highest xP Player", top_overall['web_name'], f"{top_overall['xP']} xP")
    col2.metric("Top Midfielder", top_mid['web_name'], f"{top_mid['xP']} xP")
    col3.metric("Top Defender", top_def['web_name'], f"{top_def['xP']} xP")
    col4.metric("Top Form Pick", top_val['web_name'], f"£{top_val['now_cost']}m")

    st.markdown("---")

    # Chart Section
    st.subheader("🚀 Top 15 Projected Scorers")
    top_15 = players_df.sort_values(by='xP', ascending=False).head(15)

    fig = px.bar(
        top_15,
        x='web_name',
        y='xP',
        color='position',
        text='xP',
        template='plotly_dark',
        color_discrete_map={'GKP': '#FFD700', 'DEF': '#00BFFF', 'MID': '#00FF7F', 'FWD': '#FF4500'}
    )
    fig.update_traces(texttemplate='%{text}', textposition='outside')
    fig.update_layout(xaxis_title="Player", yaxis_title="Expected Points (xP)", height=450)
    st.plotly_chart(fig, use_container_width=True)

# 2. MY SQUAD & COACH RECOMMENDATIONS
elif menu == "🛡️ My Squad & Coach":
    st.title("🛡️ My Squad & AI Recommendations")

    if not manager_id_input:
        st.info("👈 Enter your **FPL Manager ID** in the sidebar to load your squad.")
    else:
        user_data = fetch_user_squad(manager_id_input, current_gw)
        if not user_data:
            st.error("Could not find squad for this Manager ID. Make sure the ID is correct and your team is public.")
        else:
            picks = user_data.get('picks', [])
            my_player_ids = [p['element'] for p in picks]
            
            my_squad_df = players_df[players_df['id'].isin(my_player_ids)].copy()
            
            # Map picks order & starting 11 vs bench
            pick_order = {p['element']: p['position'] for p in picks}
            is_captain = {p['element']: p['is_captain'] for p in picks}
            
            my_squad_df['squad_order'] = my_squad_df['id'].map(pick_order)
            my_squad_df['is_captain'] = my_squad_df['id'].map(is_captain)
            my_squad_df = my_squad_df.sort_values(by='squad_order')

            starting_11 = my_squad_df[my_squad_df['squad_order'] <= 11]
            bench = my_squad_df[my_squad_df['squad_order'] > 11]

            # Projected Points Summary
            total_xp = starting_11['xP'].sum().round(2)
            c_player = my_squad_df[my_squad_df['is_captain'] == True]
            if not c_player.empty:
                total_xp += c_player.iloc[0]['xP'] # Add captain double points

            st.markdown(f"### 🎯 Total Team Projected xP: **{total_xp:.2f} pts**")

            # Captain Recommendation Engine
            recommended_captain = starting_11.sort_values(by='xP', ascending=False).iloc[0]

            st.markdown(f"""
                <div class="stat-card">
                    <h4>👑 AI Captaincy Recommendation</h4>
                    <p>Armband <b>{recommended_captain['web_name']}</b> ({recommended_captain['team_name']}) for <b>{recommended_captain['xP']} xP</b> this Gameweek.</p>
                </div>
            """, unsafe_allow_html=True)

            # Display Starting XI
            st.subheader("📋 Starting 11")
            st.dataframe(
                starting_11[['web_name', 'team_name', 'position', 'now_cost', 'xP', 'form']].rename(
                    columns={'web_name': 'Player', 'team_name': 'Team', 'position': 'Pos', 'now_cost': 'Cost (£m)', 'xP': 'Expected Pts'}
                ),
                use_container_width=True
            )

            # Display Bench
            st.subheader("🪑 Bench")
            st.dataframe(
                bench[['web_name', 'team_name', 'position', 'now_cost', 'xP']].rename(
                    columns={'web_name': 'Player', 'team_name': 'Team', 'position': 'Pos', 'now_cost': 'Cost (£m)', 'xP': 'Expected Pts'}
                ),
                use_container_width=True
            )

# 3. PLAYER EXPLORER
elif menu == "🔍 Player Explorer":
    st.title("🔍 Player Comparison & Search")

    col_filters = st.columns(3)
    pos_filter = col_filters[0].multiselect("Filter Position", options=list(pos_map.values()), default=list(pos_map.values()))
    price_filter = col_filters[1].slider("Max Price (£m)", 4.0, 15.0, 15.0, 0.5)
    search_query = col_filters[2].text_input("Search Player Name", "")

    filtered_df = players_df[
        (players_df['position'].isin(pos_filter)) &
        (players_df['now_cost'] <= price_filter)
    ]

    if search_query:
        filtered_df = filtered_df[filtered_df['web_name'].str.contains(search_query, case=False)]

    st.dataframe(
        filtered_df[['web_name', 'team_name', 'position', 'now_cost', 'xP', 'form', 'total_points', 'selected_by_percent']]
        .sort_values(by='xP', ascending=False)
        .rename(columns={
            'web_name': 'Player', 'team_name': 'Team', 'position': 'Pos', 
            'now_cost': 'Cost (£m)', 'xP': 'Expected Pts', 'form': 'Form (Last 5)',
            'total_points': 'Total Pts', 'selected_by_percent': 'Selected %'
        }),
        use_container_width=True
    )

# 4. TEAM & FIXTURE ANALYTICS
elif menu == "⚔️ Team & Fixture Analytics":
    st.title("⚔️ Team Power Rankings")
    
    team_stats = players_df.groupby('team_name').agg(
        Total_xP=('xP', 'sum'),
        Avg_Form=('form', 'mean'),
        Total_Goals=('goals_scored', 'sum')
    ).reset_index().sort_values(by='Total_xP', ascending=False)

    fig_teams = px.bar(
        team_stats,
        x='team_name',
        y='Total_xP',
        title="Total Team Expected Points Rank",
        template='plotly_dark',
        color='Total_xP',
        color_continuous_scale='Greens'
    )
    st.plotly_chart(fig_teams, use_container_width=True)
