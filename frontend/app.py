import json
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
# Main Content: AI Summarizer
# ==========================================
st.header("AI Summarizer")
st.write("Tests the `/llm/summarize/stream` endpoint. Note: The backend has a rate limit of 5 requests per minute.")

if st.session_state.access_token is None:
    st.warning("Please log in from the sidebar to use the summarizer.")
    st.stop()

with st.form("llm_form"):
    text_to_summarize = st.text_area("Text to summarize", height=150)
    run_llm = st.form_submit_button("Summarize")

if run_llm:
    if not text_to_summarize:
        st.warning("Please enter some text first.")
    else:
        output = st.empty()
        full_response = ""
        try:
            with requests.post(
                f"{API_URL}/llm/summarize/stream",
                json={"text": text_to_summarize},
                headers=get_headers(),
                stream=True,
                timeout=60,
            ) as res:
                if res.status_code == 429:
                    st.error("Rate limit exceeded! Please wait a minute.")
                elif res.status_code != 200:
                    st.error(f"Error: {res.text}")
                else:
                    for line in res.iter_lines():
                        if not line:
                            continue
                        decoded = line.decode("utf-8")
                        if not decoded.startswith("data: "):
                            continue
                        data = decoded[6:]
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        if chunk.startswith("[ERROR]"):
                            st.error(chunk)
                            break
                        full_response += chunk
                        output.info(full_response + " ▌")
                    output.info(full_response)
        except requests.exceptions.RequestException as e:
            st.error(f"Connection error: {e}")
