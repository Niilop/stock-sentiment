from datetime import date, timedelta
import streamlit as st
import requests

# Configuration
API_URL = "http://backend:8000/"

# Initialize session state
if "access_token" not in st.session_state:
    st.session_state.access_token = None

def get_headers():
    if st.session_state.access_token:
        return {"Authorization": f"Bearer {st.session_state.access_token}"}
    return {}

st.set_page_config(page_title="Stock Sentiment Analysis API Tester", layout="wide")
st.title("🚀 Stock Sentiment Analysis API Tester")

# ==========================================
# Sidebar: Authentication
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

        if st.button("Get My Profile"):
            response = requests.get(f"{API_URL}/auth/me", headers=get_headers())
            if response.status_code == 200:
                st.json(response.json())
            else:
                st.error("Failed to fetch profile. Token might be expired.")

        if st.button("Logout"):
            st.session_state.access_token = None
            st.rerun()

# ==========================================
# Sentiment Timeframe Analysis
# ==========================================
st.divider()
st.header("Sentiment Analysis")
st.write("Select a ticker and date range to get an AI-powered sentiment summary of stored news.")

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

        if resp.status_code == 404:
            st.warning(resp.json().get("detail", "No articles found for this selection."))
        elif resp.status_code != 200:
            st.error(f"Error {resp.status_code}: {resp.text}")
        else:
            data = resp.json()
            bd = data["sentiment_breakdown"]

            st.subheader(f"{data['ticker']} — {start_date} to {end_date}")

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Articles", data["articles_found"])
            m2.metric("Positive", bd["positive"])
            m3.metric("Negative", bd["negative"])
            m4.metric("Neutral", bd["neutral"])
            m5.metric("Unscored", bd["unscored"])

            st.markdown("### Summary")
            st.write(data["summary"])
