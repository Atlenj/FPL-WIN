import streamlit as st
import pandas as pd
import requests
import plotly.express as px

# Set page layout
st.set_page_config(
    page_title="FPL Expected Points Predictor",
    page_icon="⚽",
    layout="wide"
)

st.title("⚽ FPL Expected Points ($xP$) Predictor")
st.markdown("Live player projections powered by official Fantasy Premier League data.")

# Cache data fetching to make the app fast
@st.cache_data(ttl=3600)
def fetch_fpl_data():
    url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        st.error("Failed to fetch data from FPL API.")
        return None

data = fetch_fpl_data()

if data:
    # Process elements (players) and element_types (positions)
    players_df = pd.DataFrame(data['elements'])
    teams_df = pd.DataFrame(data['teams'])
    positions_df = pd.DataFrame(data['element_types'])

    # Map team names and position names
    team_map = dict(zip(teams_df['id'], teams_df['name']))
    pos_map = dict(zip(positions_df['id'], positions_df['singular_name_short']))

    players_df['team_name'] = players_df['team'].map(team_map)
    players_df['position'] = players_df['element_type'].map(pos_map)

    # Clean numeric columns
    players_df['now_cost'] = players_df['now_cost'] / 10.0
    players_df['form'] = pd.to_numeric(players_df['form'], errors='coerce')
    players_df['selected_by_percent'] = pd.to_numeric(players_df['selected_by_percent'], errors='coerce')
    players_df['points_per_game'] = pd.to_numeric(players_df['points_per_game'], errors='coerce')

    # Simple xP Model Algorithm:
    # xP = (Form * 0.5) + (Points per Game * 0.3) + (Availability Chance * 0.2)
    players_df['chance_of_playing_next_round'] = players_df['chance_of_playing_next_round'].fillna(100) / 100.0
    players_df['xP'] = (
        (players_df['form'] * 0.5) + 
        (players_df['points_per_game'] * 0.3) + 
        (players_df['chance_of_playing_next_round'] * 2.0)
    ).round(2)

    # --- SIDEBAR FILTERS ---
    st.sidebar.header("Filter Options")

    # Position Filter
    selected_positions = st.sidebar.multiselect(
        "Position",
        options=list(pos_map.values()),
        default=list(pos_map.values())
    )

    # Max Price Filter
    max_price = st.sidebar.slider(
        "Max Price (£m)",
        min_value=float(players_df['now_cost'].min()),
        max_value=float(players_df['now_cost'].max()),
        value=float(players_df['now_cost'].max()),
        step=0.5
    )

    # Minimum Minutes Filter
    min_minutes = st.sidebar.slider(
        "Min Minutes Played",
        min_value=0,
        max_value=int(players_df['minutes'].max()),
        value=180,
        step=90
    )

    # Apply Filters
    filtered_df = players_df[
        (players_df['position'].isin(selected_positions)) &
        (players_df['now_cost'] <= max_price) &
        (players_df['minutes'] >= min_minutes)
    ].sort_values(by='xP', ascending=False)

    # --- METRICS DASHBOARD ---
    col1, col2, col3, col4 = st.columns(4)
    if not filtered_df.empty:
        top_player = filtered_df.iloc[0]
        col1.metric("Predicted Top Scorer", top_player['web_name'], f"{top_player['xP']} xP")
        col2.metric("Top Scorer Team", top_player['team_name'])
        col3.metric("Top Scorer Cost", f"£{top_player['now_cost']}m")
        col4.metric("Selected By", f"{top_player['selected_by_percent']}%")

    st.markdown("---")

    # --- VISUAL CHART ---
    st.subheader("📊 Expected Points Projections")
    
    top_20 = filtered_df.head(20)
    
    fig = px.bar(
        top_20,
        x='web_name',
        y='xP',
        color='position',
        text='xP',
        title="Top 20 Predicted Players for Next Gameweek",
        labels={'web_name': 'Player', 'xP': 'Expected Points (xP)', 'position': 'Position'},
        color_discrete_map={'GKP': '#FFD700', 'DEF': '#00BFFF', 'MID': '#00FF7F', 'FWD': '#FF4500'}
    )
    fig.update_traces(texttemplate='%{text}', textposition='outside')
    fig.update_layout(xaxis_tickangle=-45, height=500)
    
    st.plotly_chart(fig, use_container_width=True)

    # --- DATA TABLE ---
    st.subheader("📋 Player Projections Table")
    display_cols = ['web_name', 'team_name', 'position', 'now_cost', 'xP', 'form', 'total_points', 'selected_by_percent']
    
    st.dataframe(
        filtered_df[display_cols].rename(columns={
            'web_name': 'Player',
            'team_name': 'Team',
            'position': 'Pos',
            'now_cost': 'Cost (£m)',
            'xP': 'Expected Points',
            'form': 'Form (Last 5)',
            'total_points': 'Total Points',
            'selected_by_percent': 'Selected %'
        }),
        use_container_width=True
    )
