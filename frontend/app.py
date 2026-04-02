from datetime import date, timedelta
import plotly.graph_objects as go
import streamlit as st
import requests

# Configuration
API_URL = "http://backend:8000/"

# Initialize session state
if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "current_result" not in st.session_state:
    st.session_state.current_result = None

def get_headers():
    if st.session_state.access_token:
        return {"Authorization": f"Bearer {st.session_state.access_token}"}
    return {}

def show_result(data: dict):
    bd = data["sentiment_breakdown"]
    start = data["start"][:10]
    end = data["end"][:10]

    st.subheader(f"{data['ticker']} — {start} to {end}")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Articles", data["articles_found"])
    m2.metric("Positive", bd["positive"])
    m3.metric("Negative", bd["negative"])
    m4.metric("Neutral", bd["neutral"])
    m5.metric("Unscored", bd["unscored"])

    weekly = data.get("weekly_sentiment", [])
    if weekly:
        weeks = [w["week"] for w in weekly]
        scores = [w["avg_score"] for w in weekly]

        fig = go.Figure()
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
        fig.add_trace(go.Scatter(
            x=weeks,
            y=scores,
            mode="lines+markers",
            fill="tozeroy",
            fillcolor="rgba(0,200,100,0.15)",
            line=dict(color="#00c864", width=2),
            marker=dict(size=6),
            name="Avg sentiment",
        ))
        fig.update_layout(
            title=f"{data['ticker']} weekly sentiment",
            yaxis=dict(title="Score", range=[-1.1, 1.1], tickvals=[-1, 0, 1], ticktext=["Negative", "Neutral", "Positive"]),
            xaxis=dict(title="Week"),
            showlegend=False,
            margin=dict(t=40, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Summary")
    st.write(data["summary"])

st.set_page_config(page_title="Stock Sentiment Analysis", layout="wide")
st.title("Stock Sentiment Analysis")

# ==========================================
# Sidebar: Authentication + History
# ==========================================
with st.sidebar:
    st.header("Authentication")

    if st.session_state.access_token is None:
        auth_mode = st.radio("Choose Action", ["Login", "Register"])

        if auth_mode == "Login":
            with st.form("login_form"):
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                submit = st.form_submit_button("Login")

                if submit:
                    response = requests.post(
                        f"{API_URL}/auth/login",
                        data={"username": email, "password": password}
                    )
                    if response.status_code == 200:
                        st.session_state.access_token = response.json().get("access_token")
                        st.success("Logged in successfully!")
                        st.rerun()
                    else:
                        st.error(f"Login failed: {response.text}")

        else:
            with st.form("register_form"):
                new_email = st.text_input("Email")
                new_username = st.text_input("Username")
                new_password = st.text_input("Password", type="password")
                submit = st.form_submit_button("Register")

                if submit:
                    response = requests.post(
                        f"{API_URL}/auth/register",
                        json={"email": new_email, "username": new_username, "password": new_password}
                    )
                    if response.status_code == 200:
                        st.success("Registration successful! You can now log in.")
                    else:
                        st.error(f"Registration failed: {response.text}")
    else:
        st.success("You are authenticated.")

        if st.button("Logout"):
            st.session_state.access_token = None
            st.session_state.current_result = None
            st.rerun()

        # ── Sentiment history ──────────────────────────────
        st.divider()
        st.subheader("History")

        history_resp = requests.get(f"{API_URL}/sentiment/history", headers=get_headers())
        if history_resp.status_code == 200:
            history = history_resp.json()
            if not history:
                st.caption("No analyses yet.")
            else:
                for item in history:
                    label = f"{item['ticker']}  {item['start'][:10]} → {item['end'][:10]}"
                    col_load, col_del = st.columns([5, 1])
                    with col_load:
                        if st.button(label, key=f"history_{item['id']}", use_container_width=True):
                            detail = requests.get(
                                f"{API_URL}/sentiment/history/{item['id']}",
                                headers=get_headers(),
                            )
                            if detail.status_code == 200:
                                st.session_state.current_result = detail.json()
                                st.rerun()
                    with col_del:
                        if st.button("🗑", key=f"delete_{item['id']}"):
                            requests.delete(
                                f"{API_URL}/sentiment/history/{item['id']}",
                                headers=get_headers(),
                            )
                            if st.session_state.current_result and st.session_state.current_result.get("id") == item["id"]:
                                st.session_state.current_result = None
                            st.rerun()

# ==========================================
# Main: Sentiment Analysis
# ==========================================
st.header("Sentiment Analysis")

if st.session_state.access_token is None:
    st.warning("Please log in from the sidebar.")
    st.stop()

# Fetch available tickers
tickers_resp = requests.get(f"{API_URL}/news/tickers", headers=get_headers())
if tickers_resp.status_code != 200:
    st.error("Could not load tickers from the database.")
    st.stop()

tickers = tickers_resp.json()
if not tickers:
    st.info("No news articles found in the database yet. Fetch some news first.")
    st.stop()

col1, col2, col3 = st.columns([2, 2, 2])
with col1:
    selected_ticker = st.selectbox("Ticker", tickers)
with col2:
    start_date = st.date_input("From", value=date.today() - timedelta(days=30))
with col3:
    end_date = st.date_input("To", value=date.today())

run_analysis = st.button("Analyze Sentiment", type="primary")

if run_analysis:
    if start_date > end_date:
        st.error("'From' date must be before 'To' date.")
    else:
        with st.spinner(f"Analyzing {selected_ticker} sentiment from {start_date} to {end_date}…"):
            try:
                resp = requests.post(
                    f"{API_URL}/sentiment/summary",
                    json={
                        "ticker": selected_ticker,
                        "start": f"{start_date}T00:00:00",
                        "end": f"{end_date}T23:59:59",
                    },
                    headers=get_headers(),
                    timeout=120,
                )
            except requests.exceptions.RequestException as e:
                st.error(f"Connection error: {e}")
                st.stop()

        if resp.status_code in (429, 503):
            st.error(resp.json().get("detail", "LLM provider unavailable."))
        elif resp.status_code == 404:
            st.warning(resp.json().get("detail", "No articles found for this selection."))
        elif resp.status_code != 200:
            st.error(f"Error {resp.status_code}: {resp.text}")
        else:
            st.session_state.current_result = resp.json()
            st.rerun()

if st.session_state.current_result:
    show_result(st.session_state.current_result)
