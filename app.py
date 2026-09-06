import streamlit as st
import pandas as pd
from supabase import create_client, Client

st.set_page_config(page_title="Prop Compound", page_icon="⚾", layout="wide")

@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

st.title("⚾ Prop Compound: MLB Strikeout Dashboard")
st.caption("Live edge tracking connected to Supabase")

def load_predictions():
    response = (
        supabase.table("predictions")
        .select("*")
        .eq("status", "APPROVED")
        .order("edge", desc=True)
        .execute()
    )
    return pd.DataFrame(response.data)

try:
    df = load_predictions()

    if df.empty:
        st.info("No active model edges flagged in Supabase.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Active Edges", len(df))
        col2.metric("Top Edge", f"{(float(df.iloc[0]['edge']) * 100):.1f}%")
        col3.metric("Top Pick", f"{df.iloc[0]['player_name']} O/U {df.iloc[0]['line']}")

        st.subheader("Actionable Edges")
        
        display_df = df[[
            "player_name", "matchup", "line", "odds", "projected", "edge"
        ]].copy()
        display_df["edge"] = display_df["edge"].apply(lambda x: f"{float(x) * 100:.1f}%")
        display_df.columns = ["Player", "Matchup", "Line", "Odds", "Projected", "Edge"]
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)

except Exception as e:
    st.error(f"Database error: {e}")
